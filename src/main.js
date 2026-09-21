import * as THREE from 'three';
import { makeLoaders, sunDirection, makeSky, makeSea, makeTrees, makeEnvironment, tunePBR } from './world.js';
import { Ground } from './ground.js';
import { Player } from './player.js';
import { Train } from './train.js';
import { Sound } from './audio.js';

const BASE = import.meta.env.BASE_URL;
const $ = (id) => document.getElementById(id);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

// ---------------------------------------------------------------------------------------------------- renderer / scene
const canvas = $('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;               // linear lighting -> sRGB display
renderer.toneMapping = THREE.ACESFilmicToneMapping;               // filmic roll-off: no clipped highlights, richer colour
renderer.toneMappingExposure = 1.15;
renderer.shadowMap.enabled = true;                                // real-time shadows (sun + player-following shadow frustum)
renderer.shadowMap.type = THREE.PCFSoftShadowMap;                 // soft edges

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0xe9c6a0, 0.00085);
const camera = new THREE.PerspectiveCamera(58, window.innerWidth / window.innerHeight, 0.35, 150000);

// ---------------------------------------------------------------------------------------------------- loading
const SIZES = { meta: 0.002, ground: 0.5, trees: 0.1, world: 1.7, train: 0.05, character: 4.4 };
const TOTAL = Object.values(SIZES).reduce((a, b) => a + b, 0);
const done = {};
function progress(name, frac) {
  done[name] = clamp(frac, 0, 1) * SIZES[name];
  const sum = Object.values(done).reduce((a, b) => a + b, 0);
  $('barfill').style.width = `${Math.round((100 * sum) / TOTAL)}%`;
}
async function fetchBuf(name, url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  const len = Number(res.headers.get('content-length')) || 0;
  const enc = res.headers.get('content-encoding');
  if (!res.body || !len || enc) {
    const b = await res.arrayBuffer();
    progress(name, 1);
    return b;
  }
  const reader = res.body.getReader();
  const chunks = [];
  let got = 0;
  for (;;) {
    const { done: fin, value } = await reader.read();
    if (fin) break;
    chunks.push(value);
    got += value.length;
    progress(name, got / len);
  }
  const out = new Uint8Array(got);
  let o = 0;
  for (const c of chunks) {
    out.set(c, o);
    o += c.length;
  }
  return out.buffer;
}
const gltfLoader = makeLoaders();
const parse = (buf) => new Promise((ok, err) => gltfLoader.parse(buf, BASE + 'models/', ok, err));

let meta;
let ground;
let player;
let train;
let sound;
let sun;
let sky;
let sea;
let worldRoot;
let sunDir;

async function load() {
  meta = await (await fetch(BASE + 'models/meta.json')).json();
  progress('meta', 1);
  const [gbuf, trees, wbuf, tbuf, cbuf] = await Promise.all([
    fetchBuf('ground', BASE + 'models/ground.bin'),
    fetch(BASE + 'models/trees.json').then((r) => r.json()).then((j) => (progress('trees', 1), j)),
    fetchBuf('world', BASE + 'models/world.glb'),
    fetchBuf('train', BASE + 'models/train.glb'),
    fetchBuf('character', BASE + 'models/character.glb'),
  ]);
  $('loadtext').textContent = '街を組み立て中…';
  await new Promise((r) => setTimeout(r, 30));
  ground = new Ground(meta.grid, gbuf);
  const [worldG, trainG, charG] = await Promise.all([parse(wbuf), parse(tbuf), parse(cbuf)]);

  // lights, sky, sea
  sunDir = sunDirection(meta);
  scene.environment = makeEnvironment(renderer, sunDir);        // sky-based IBL: reflections + ambient gradient
  scene.environmentIntensity = 0.55;
  scene.add(new THREE.HemisphereLight(0xffe6cc, 0x8a7560, 0.6));
  sun = new THREE.DirectionalLight(0xffd6a8, 3.4);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  const sc = sun.shadow.camera;
  sc.left = -45;
  sc.right = 45;
  sc.top = 45;
  sc.bottom = -45;
  sc.near = 1;
  sc.far = 320;
  sun.shadow.bias = -0.0006;
  sun.shadow.normalBias = 0.05;
  scene.add(sun, sun.target);
  sky = makeSky(sunDir);
  scene.add(sky);
  sea = makeSea(meta.sea_level);
  scene.add(sea);

  // static world
  worldRoot = worldG.scene;
  worldRoot.traverse((o) => {
    if (!o.isMesh) return;
    const far = o.name.includes('FarLand');
    o.castShadow = !far;
    o.receiveShadow = !far;
    if (far) {                                   // distant headlands / Enoshima / Fuji: hazy blue silhouettes
      o.material = new THREE.MeshBasicMaterial({ color: 0x8b98ad, fog: false });
      return;
    }
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    for (const m of mats) if (m.transparent) m.depthWrite = false;
  });
  tunePBR(worldRoot);
  scene.add(worldRoot);
  scene.add(makeTrees(trees));

  train = new Train(trainG, worldRoot, meta);
  scene.add(train.group);

  const sp = meta.spawn;
  player = new Player(charG, ground, { x: sp.x, z: -sp.y, yaw: Math.atan2(-3.6, -5.2) });
  scene.add(player.root);
  sound = new Sound();
  $('loadtext').textContent = '準備できました';
  $('start').disabled = false;
}

// ---------------------------------------------------------------------------------------------------- input
const keys = {};
const touch = { x: 0, y: 0, run: false };
let camYaw = 0.61;
let camPitch = 0.32;
let camDist = 5.2;
const camPos = new THREE.Vector3();
let started = false;

addEventListener('keydown', (e) => {
  if (e.code === 'Space') e.preventDefault();
  if (e.repeat) return;
  keys[e.code] = true;
  if (!started) return;
  if (e.code === 'Space') player.jump();
  if (e.code === 'KeyM' && sound) {
    const m = sound.toggle();
    showMsg(m ? '音: オフ' : '音: オン', 1200);
  }
});
addEventListener('keyup', (e) => {
  keys[e.code] = false;
});
addEventListener('blur', () => {
  for (const k in keys) keys[k] = false;
});

let drag = null;
canvas.addEventListener('pointerdown', (e) => {
  drag = { id: e.pointerId, x: e.clientX, y: e.clientY };
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener('pointermove', (e) => {
  if (!drag || drag.id !== e.pointerId) return;
  camYaw -= (e.clientX - drag.x) * 0.0055;
  camPitch = clamp(camPitch + (e.clientY - drag.y) * 0.0045, -0.12, 1.25);
  drag.x = e.clientX;
  drag.y = e.clientY;
});
const endDrag = (e) => {
  if (drag && drag.id === e.pointerId) drag = null;
};
canvas.addEventListener('pointerup', endDrag);
canvas.addEventListener('pointercancel', endDrag);
canvas.addEventListener('wheel', (e) => {
  camDist = clamp(camDist * (1 + e.deltaY * 0.0012), 2.2, 16);
  e.preventDefault();
}, { passive: false });

// on-screen joystick / buttons
const stick = $('stick');
const knob = $('knob');
let stickId = null;
function stickMove(e) {
  const r = stick.getBoundingClientRect();
  let dx = e.clientX - (r.left + r.width / 2);
  let dy = e.clientY - (r.top + r.height / 2);
  const m = Math.hypot(dx, dy);
  const lim = r.width * 0.42;
  if (m > lim) {
    dx = (dx / m) * lim;
    dy = (dy / m) * lim;
  }
  knob.style.transform = `translate(${dx}px, ${dy}px)`;
  touch.x = dx / lim;
  touch.y = -dy / lim;
}
stick.addEventListener('pointerdown', (e) => {
  stickId = e.pointerId;
  stick.setPointerCapture(e.pointerId);
  stickMove(e);
});
stick.addEventListener('pointermove', (e) => {
  if (e.pointerId === stickId) stickMove(e);
});
const stickEnd = (e) => {
  if (e.pointerId !== stickId) return;
  stickId = null;
  touch.x = touch.y = 0;
  knob.style.transform = '';
};
stick.addEventListener('pointerup', stickEnd);
stick.addEventListener('pointercancel', stickEnd);
$('bJump').addEventListener('pointerdown', (e) => {
  e.preventDefault();
  if (started) player.jump();
});
$('bRun').addEventListener('pointerdown', (e) => {
  e.preventDefault();
  touch.run = !touch.run;
  $('bRun').classList.toggle('on', touch.run);
});

function readInput() {
  const x = (keys.KeyD || keys.ArrowRight ? 1 : 0) - (keys.KeyA || keys.ArrowLeft ? 1 : 0) + touch.x;
  const y = (keys.KeyW || keys.ArrowUp ? 1 : 0) - (keys.KeyS || keys.ArrowDown ? 1 : 0) + touch.y;
  return {
    x: clamp(x, -1, 1),
    y: clamp(y, -1, 1),
    run: !!(keys.ShiftLeft || keys.ShiftRight) || touch.run,
    sprint: !!keys.KeyR,
  };
}

// ---------------------------------------------------------------------------------------------------- HUD
let msgTimer = 0;
function showMsg(text, ms = 2600) {
  const el = $('msg');
  el.textContent = text;
  el.classList.add('show');
  clearTimeout(msgTimer);
  msgTimer = setTimeout(() => el.classList.remove('show'), ms);
}
let lastWhere = '';
function updateWhere() {
  let best = null;
  let bd = 1e9;
  for (const p of meta.poi) {
    const d = Math.hypot(p.x - player.pos.x, -p.y - player.pos.z);
    if (d < bd) {
      bd = d;
      best = p;
    }
  }
  const txt = best && bd < 90 ? `${best.name} 付近` : '鎌倉高校前 周辺';
  if (txt !== lastWhere) {
    $('where').textContent = txt;
    lastWhere = txt;
  }
}

// ---------------------------------------------------------------------------------------------------- loop
const clock = new THREE.Clock();
let wasAlarm = false;
const camTarget = new THREE.Vector3();
const desired = new THREE.Vector3();

function gate(nx, nz, ox, oz) {
  // the crossing is closed while the alarm rings: one cannot walk in from outside
  if (!train.alarm) return false;
  const inNew = Math.abs(nx) < 4.2 && Math.abs(nz) < 3.6;
  const inOld = Math.abs(ox) < 4.2 && Math.abs(oz) < 3.6;
  return inNew && !inOld;
}

function frame() {
  requestAnimationFrame(frame);
  const dt = Math.min(clock.getDelta(), 0.05);
  const t = clock.elapsedTime;
  if (sea) {
    sea.userData.normalMap.offset.set((t * 0.0009) % 1, (t * 0.0006) % 1);
    sea.position.x = camera.position.x;
    sea.position.z = camera.position.z;
  }
  if (!player) {
    renderer.render(scene, camera);
    return;
  }
  train.update(dt);
  if (started) {
    player.update(dt, readInput(), camYaw, gate);
    if (train.hits(player.pos)) {
      player.teleport(meta.spawn.x, -meta.spawn.y, Math.atan2(-3.6, -5.2));
      showMsg('電車に注意！ 踏切の外へ戻りました', 3200);
    }
    if (train.alarm && !wasAlarm) showMsg('カンカンカン… 電車が来ます', 3000);
    wasAlarm = train.alarm;
    updateWhere();
    if (sound) sound.update(train.alarm, Math.hypot(player.pos.x, player.pos.z), clamp((player.pos.z - 12) / 25, 0, 1));
  } else {
    player.update(dt, { x: 0, y: 0, run: false, sprint: false }, camYaw, null);
  }

  // follow camera
  camTarget.set(player.pos.x, player.pos.y + 1.45, player.pos.z);
  const cp = Math.cos(camPitch);
  desired.set(camTarget.x + Math.sin(camYaw) * cp * camDist, camTarget.y + Math.sin(camPitch) * camDist + 0.25, camTarget.z + Math.cos(camYaw) * cp * camDist);
  const gh = ground.height(desired.x, desired.z);
  const floor = (gh === gh ? gh : player.pos.y) + 0.55;
  if (desired.y < floor) desired.y = floor;
  camPos.lerp(desired, 1 - Math.exp(-dt * 14));
  if (camPos.lengthSq() === 0) camPos.copy(desired);
  camera.position.copy(camPos);
  camera.lookAt(camTarget);
  sky.position.copy(camera.position);
  sky.scale.setScalar(20000);

  sun.position.copy(player.pos).addScaledVector(sunDir, 160);
  sun.target.position.copy(player.pos);
  sun.target.updateMatrixWorld();

  renderer.render(scene, camera);
}

addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

$('start').addEventListener('click', () => {
  started = true;
  $('loading').classList.add('hidden');
  $('hud').classList.remove('hidden');
  if (matchMedia('(pointer: coarse)').matches) $('touch').classList.remove('hidden');
  sound.init();
  showMsg('散歩をはじめましょう', 2200);
  setTimeout(() => $('help').style.opacity = '0.7', 6000);
});

load()
  .then(() => {
    camPos.set(0, 0, 0);
    frame();
    window.__enoden = { get player() { return player; }, get train() { return train; }, camera, scene, ground, setCam: (y, p, d) => { camYaw = y; camPitch = p; camDist = d; }, start: () => $('start').click() };
  })
  .catch((e) => {
    console.error(e);
    $('loadtext').textContent = `読み込みに失敗しました: ${e.message}`;
  });
