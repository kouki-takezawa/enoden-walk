import * as THREE from 'three';
import { PRESETS, loadSettings, saveSettings, autoPreset, makeT } from './config.js';
import { Ground } from './ground.js';
import { Input } from './input.js';
import { Player, SPEED } from './player.js';
import { Train } from './train.js';
import { Sound } from './audio.js';
import { Renderer } from './render.js';
import { makeSky, TimeOfDay, makeLampGlow } from './sky.js';
import { makeSea } from './sea.js';
import { makeTrees, updateTreeLOD } from './trees.js';
import { chunkWorld } from './optimize.js';
import { U } from './fx.js';
import { UI } from './ui.js';
import { makeLoaders, makeEnvironment, tunePBR, styleWorld } from './world.js';

const BASE = import.meta.env.BASE_URL;
const $ = (id) => document.getElementById(id);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const ZERO = { x: 0, y: 0, run: false, sprint: false };
const UP = new THREE.Vector3(0, 1, 0);
const TIMES = ['day', 'dusk', 'night'];
const isTouch = typeof matchMedia === 'function' && matchMedia('(pointer: coarse)').matches;

// ---------------------------------------------------------------------------------------------------- settings
const params = new URLSearchParams(location.search);
const settings = loadSettings();
if (params.has('lang')) settings.lang = params.get('lang') === 'en' ? 'en' : 'ja';
if (params.has('q')) settings.quality = params.get('q');
if (params.has('t')) settings.time = params.get('t');
if (params.has('fps')) settings.fps = true;
const t = makeT(() => settings.lang);
const resolveLevel = () => (PRESETS[settings.quality] ? settings.quality : autoPreset());
let level = resolveLevel();
let preset = PRESETS[level];
if (isTouch) document.body.classList.add('touch');

// ---------------------------------------------------------------------------------------------------- renderer / scene
const canvas = $('c');
const renderer = new Renderer(canvas, preset, { govern: !params.has('nogov') });
const gl = renderer.gl;
const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0xe9c6a0, 0.00085);
const camera = new THREE.PerspectiveCamera(58, innerWidth / innerHeight, 0.3, 150000);
const hemi = new THREE.HemisphereLight(0xffffff, 0x888888, 0.6);
const sunLight = new THREE.DirectionalLight(0xffffff, 3);
sunLight.castShadow = true;
sunLight.shadow.bias = -0.0006;
sunLight.shadow.normalBias = 0.05;
sunLight.shadow.camera.near = 1;
sunLight.shadow.camera.far = 320;
sunLight.shadow.autoUpdate = false; // refreshed only when something inside the box moved (see updateShadow)
scene.add(hemi, sunLight, sunLight.target);
const sky = makeSky(preset.clouds);
scene.add(sky);
const lampsPos = [];
let pointLights = [];
let envRT = null;
function rebuildEnv() {
  const rt = makeEnvironment(gl, sky);
  scene.environment = rt.texture;
  envRT?.dispose();
  envRT = rt;
}
const tod = new TimeOfDay({ scene, renderer: gl, sky, sunLight, hemi, lampsPos, pointLights, glowPoints: null, onEnv: rebuildEnv });

function applyShadow() {
  const sh = sunLight.shadow;
  sh.mapSize.set(preset.shadow, preset.shadow);
  const r = preset.shadowRange;
  const c = sh.camera;
  c.left = c.bottom = -r;
  c.right = c.top = r;
  c.updateProjectionMatrix();
  sh.map?.dispose();
  sh.map = null;
  shadowForce = true;
}
let shadowForce = true;
applyShadow();

// ---------------------------------------------------------------------------------------------------- state
let meta;
let ground;
let player;
let train;
let worldRoot;
let treesGroup;
let treesData;
let sea;
let glow;
let ui;
let input;
let ready = false;
let started = false;
let photo = false;
let photoFov = 50;
let wantShot = false;
let modalOpen = false;
const sound = new Sound();

let camYaw = 0.61;
let camPitch = 0.32;
let camDist = 5.2;
let camDistEff = 5.2;
let rideYaw = Math.PI;
let ridePitch = 0.05;
let camSnap = true;
const camPos = new THREE.Vector3();
const camTarget = new THREE.Vector3();
const tmpA = new THREE.Vector3();
const tmpB = new THREE.Vector3();

// ---------------------------------------------------------------------------------------------------- loading
// decoded sizes in bytes: progress is measured against them because the server compresses (content-length is the encoded size)
const SIZES = { meta: 2400, ground: 492984, surface: 123246, solid: 123246, trees: 103893, world: 4097256, train: 271868, character: 852648 };
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
  if (!res.body) {
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
    progress(name, Math.min(0.99, got / SIZES[name]));
  }
  const out = new Uint8Array(got);
  let o = 0;
  for (const c of chunks) {
    out.set(c, o);
    o += c.length;
  }
  progress(name, 1);
  return out.buffer;
}
const gltfLoader = makeLoaders();
const parse = (buf) => new Promise((ok, err) => gltfLoader.parse(buf, `${BASE}models/`, ok, err));

async function load() {
  meta = await (await fetch(`${BASE}models/meta.json`)).json();
  progress('meta', 1);
  const M = (f) => `${BASE}models/${f}`;
  const [gbuf, sbuf, obuf, trees, wbuf, tbuf, cbuf] = await Promise.all([
    fetchBuf('ground', M('ground.bin')),
    fetchBuf('surface', M('surface.bin')),
    fetchBuf('solid', M('solid.bin')),
    fetch(M('trees.json')).then((r) => r.json()).then((j) => (progress('trees', 1), j)),
    fetchBuf('world', M('world.glb')),
    fetchBuf('train', M('train.glb')),
    fetchBuf('character', M('character.glb')),
  ]);
  $('loadtext').textContent = t('assembling');
  await new Promise((r) => setTimeout(r, 30));
  treesData = trees;
  ground = new Ground(meta.grid, gbuf, sbuf, obuf);
  ground.addTrees(trees.trees);
  const [worldG, trainG, charG] = await Promise.all([parse(wbuf), parse(tbuf), parse(cbuf)]);

  worldRoot = worldG.scene;
  tunePBR(worldRoot);
  chunkWorld(worldRoot); // spatial chunks: culling works for the main view and the shadow view
  styleWorld(worldRoot, preset);
  scene.add(worldRoot);
  treesGroup = makeTrees(trees, preset);
  scene.add(treesGroup);
  sea = makeSea(ground, meta.sea_level, preset.seaDepth);
  scene.add(sea);

  // street lamps + the fluorescent tubes under the platform canopy glow at night
  lampsPos.push(...meta.lamps);
  for (let k = 0; k < 10; k++) lampsPos.push([meta.platform.x0 + 2.25 + 4.5 * k, meta.platform.height + 2.35, -(meta.platform.y0 + meta.platform.y1) / 2]);
  glow = makeLampGlow(lampsPos);
  glow.visible = false;
  scene.add(glow);
  tod.glowPoints = glow;
  buildPointLights();

  train = new Train(trainG, worldRoot, meta);
  scene.add(train.group);
  const sp = meta.spawn;
  player = new Player(charG, ground, { x: sp.x, z: -sp.y, yaw: Math.atan2(-sp.x, sp.y) });
  player.onStep = (surf, speed) => sound.step(surf, speed);
  player.setDetail(preset.detail);
  scene.add(player.root);
  camYaw = player.yaw + Math.PI;

  ui.attach(meta, ground);
  tod.set(settings.time, true);
  ui.setTimeIcon(settings.time);
  rebuildEnv();
  try {
    await gl.compileAsync(scene, camera);
  } catch (e) {
    console.warn('compileAsync', e);
  }
  $('loadtext').textContent = t('ready');
  $('start').disabled = false;
  ready = true;
}

function buildPointLights() {
  for (const L of pointLights) scene.remove(L);
  pointLights = [];
  for (let i = 0; i < preset.pointLights; i++) {
    const L = new THREE.PointLight(0xffc98a, 0, 24, 2);
    scene.add(L);
    pointLights.push(L);
  }
  tod.pointLights = pointLights;
}

function disposeGroup(g) {
  g.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => (m.map?.dispose(), m.dispose()));
  });
  g.removeFromParent();
}

/** switch quality preset at run time (auto mode uses it to step down when the machine cannot keep up) */
function applyQuality(name) {
  level = name;
  preset = PRESETS[name];
  renderer.apply(preset);
  applyShadow();
  sky.material.defines.CLOUDS = preset.clouds ? 1 : 0;
  sky.material.needsUpdate = true;
  if (!ready) return;
  styleWorld(worldRoot, preset);
  disposeGroup(treesGroup);
  treesGroup = makeTrees(treesData, preset);
  scene.add(treesGroup);
  updateTreeLOD(treesGroup, player.pos.x, player.pos.z, preset.shadowRange);
  player.setDetail(preset.detail);
  disposeGroup(sea);
  sea = makeSea(ground, meta.sea_level, preset.seaDepth);
  scene.add(sea);
  buildPointLights();
}

// ---------------------------------------------------------------------------------------------------- actions
function isBlocked() {
  return !started || modalOpen || photo;
}

function toggleBoard() {
  if (isBlocked()) return;
  if (player.riding) {
    if (train.state !== 'dwell') return;
    const seat = train.seat(tmpA);
    const x = clamp(seat.x, meta.platform.x0 + 1.2, meta.platform.x1 - 1.2);
    train.rider = false;
    train.setFirstPerson(false);
    player.teleport(x, -(meta.platform.y0 + meta.platform.y1) / 2, Math.PI);
    player.root.visible = true;
    camYaw = player.yaw + Math.PI;
    camSnap = true;
    ui.showMsg(t('alighted'), 2200);
  } else if (train.canBoard(player.pos)) {
    train.rider = true;
    train.setFirstPerson(true);
    train.timer = Math.max(train.timer, 6);
    player.riding = true;
    player.speed = 0;
    player.root.visible = false;
    rideYaw = Math.PI;
    ridePitch = 0.05;
    ui.showMsg(t('boarded'), 3200);
  }
}

function findWalkable(x, z) {
  for (let r = 0; r <= 16; r += 1) {
    for (let a = 0; a < (r === 0 ? 1 : 12); a++) {
      const th = (a / 12) * Math.PI * 2 + r * 0.7;
      const px = x + Math.cos(th) * r;
      const pz = z + Math.sin(th) * r;
      if (ground.walkable(px, pz) && !ground.isSolid(px, pz) && ground.surface(px, pz) > 0) return [px, pz];
    }
  }
  return [meta.spawn.x, -meta.spawn.y];
}

function gotoSpot(p) {
  ui.fade(() => {
    if (player.riding) {
      train.rider = false;
      train.setFirstPerson(false);
      player.riding = false;
      player.root.visible = true;
    }
    const [x, z] = findWalkable(p.x, -p.y);
    const yaw = Math.hypot(x, z) < 6 ? Math.atan2(-3.6, -5.2) : Math.atan2(-x, -z);
    player.teleport(x, z, yaw);
    camYaw = yaw + Math.PI;
    camPitch = 0.32;
    camSnap = true;
    shadowForce = true;
  });
}

function setTime(name) {
  settings.time = name;
  tod.set(name);
  ui.setTimeIcon(name);
  saveSettings(settings);
  const sel = document.getElementById('sTime') || document.getElementById('pTime');
  if (sel) sel.value = name;
}

function togglePhoto() {
  if (!started || modalOpen) return;
  if (!photo) {
    photo = true;
    photoFov = 50;
    ui.enterPhoto({ fov: photoFov, time: settings.time });
    document.exitPointerLock?.();
  } else {
    photo = false;
    ui.exitPhoto(isTouch);
    player.root.visible = !player.riding;
    shadowForce = true;
  }
}

function savePhoto() {
  canvas.toBlob((blob) => {
    if (!blob) return;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `enoden-walk-${Date.now()}.png`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    ui.showMsg(t('saved'), 1800);
  }, 'image/png');
}

async function share() {
  const data = { title: t('title'), text: t('subtitle'), url: `${location.origin}${location.pathname}` };
  try {
    if (navigator.share) await navigator.share(data);
    else {
      await navigator.clipboard.writeText(data.url);
      ui.showMsg(t('copied'), 1800);
    }
  } catch {
    /* cancelled */
  }
}

const hooks = {
  jump: () => !isBlocked() && player.jump(),
  board: toggleBoard,
  photo: togglePhoto,
  mute: () => {
    settings.muted = sound.toggle();
    saveSettings(settings);
    ui.showMsg(t(settings.muted ? 'sound_off' : 'sound_on'), 1200);
  },
  help: () => (ui.modalOpen === 'help' ? ui.closeModal() : ui.openModal('help')),
  toggleMenu: () => (ui.modalOpen ? ui.closeModal() : ui.openModal('spots')),
  cycleTime: () => setTime(TIMES[(TIMES.indexOf(settings.time) + 1) % TIMES.length]),
  recenter: () => {
    camYaw = player.yaw + Math.PI;
  },
  escape: () => photo && togglePhoto(),
  stick: (a, x, y, dx, dy) => ui.stick(a, x, y, dx, dy),
  // ---- UI callbacks
  goto: gotoSpot,
  setTime,
  share,
  photoFov: (v) => (photoFov = v),
  photoHide: (h) => {
    player.root.visible = !h && !player.riding;
    shadowForce = true;
  },
  capture: () => (wantShot = true),
  modal: (open) => {
    modalOpen = open;
    if (open) document.exitPointerLock?.();
  },
  changed: (key) => {
    if (key === 'quality') {
      const next = resolveLevel();
      if (next !== level) applyQuality(next);
    } else if (key === 'volume') sound.setVolume(settings.volume);
    else if (key === 'muted') {
      sound.muted = settings.muted;
      sound.applyVolume();
    } else if (key === 'viewMode' && settings.viewMode !== 'lock') document.exitPointerLock?.();
    else if (key === 'lang') {
      ui.lastWhere = '';
      ui.lastTrain = '';
    }
    saveSettings(settings);
  },
};

ui = new UI({ t, settings, hooks });
input = new Input(canvas, settings, hooks);
$('fps').classList.toggle('hidden', !settings.fps);
$('bRun').addEventListener('pointerdown', (e) => {
  e.preventDefault();
  input.touch.run = !input.touch.run;
  $('bRun').classList.toggle('on', input.touch.run);
});
$('bJump').addEventListener('pointerdown', (e) => {
  e.preventDefault();
  hooks.jump();
});

// ---------------------------------------------------------------------------------------------------- crossing rules
function gate(nx, nz, ox, oz) {
  // the crossing is closed while the alarm rings: one cannot walk in from outside
  if (!train.alarm) return false;
  const inNew = Math.abs(nx) < 4.2 && Math.abs(nz) < 3.6;
  const inOld = Math.abs(ox) < 4.2 && Math.abs(oz) < 3.6;
  return inNew && !inOld;
}

let pushMsg = false;
let wasAlarm = false;
function crossingRules(dt) {
  const p = player.pos;
  if (train.alarm && !wasAlarm) ui.showMsg(t('alarm'), 3000);
  wasAlarm = train.alarm;
  if (train.hits(p)) {
    // knocked back to the nearer verge instead of being sent home
    const side = p.z >= 0 ? 1 : -1;
    const z = side * 2.5;
    if (ground.walkable(p.x, z) && !ground.isSolid(p.x, z)) player.teleport(p.x, z, player.yaw);
    else player.teleport(meta.spawn.x, -meta.spawn.y, player.yaw);
    ui.showMsg(t('hit'), 3200);
    return;
  }
  if (train.alarm && Math.abs(p.x) < 4.2 && Math.abs(p.z) < 3.6) {
    const s = p.z >= 0 ? 1 : -1;
    const nz = p.z + s * 2.6 * dt;
    if (ground.walkable(p.x, nz) && !ground.isSolid(p.x, nz)) p.z = nz;
    else p.x += (p.x >= 0 ? 1 : -1) * 2.6 * dt;
    if (!pushMsg) {
      pushMsg = true;
      ui.showMsg(t('clearCrossing'), 2200);
    }
  } else pushMsg = false;
}

// ---------------------------------------------------------------------------------------------------- camera
let fovNow = 58;
function updateCamera(dt, cmd) {
  const look = input.drainLook();
  const zoom = input.drainZoom();
  let fovTarget = 58;
  if (player.riding) {
    // first person from the seat: the walls are back-face culled so the scenery is visible all around
    rideYaw -= look.dx;
    ridePitch = clamp(ridePitch + look.dy, -0.9, 0.9);
    train.seat(tmpA);
    tmpA.y += 1.4 + train.inner.position.y;
    camPos.copy(tmpA);
    const cp = Math.cos(ridePitch);
    tmpB.set(-Math.sin(rideYaw) * cp, -Math.sin(ridePitch), -Math.cos(rideYaw) * cp).add(tmpA);
    camera.position.copy(camPos);
    camera.lookAt(tmpB);
    fovTarget = 68;
    player.pos.copy(tmpA).y -= 1.4;
    camSnap = true;
  } else {
    camYaw -= look.dx;
    camPitch = clamp(camPitch + look.dy, -0.12, 1.25);
    camDist = clamp(camDist * (1 + zoom), photo ? 0.8 : 2.2, photo ? 40 : 16);
    // "steer follow": with analog steering (stick) the camera slowly swings toward the walking direction
    if (settings.autoCam && !settings.reduceMotion && player.speed > 0.8 && cmd.y > 0.4 && Math.abs(cmd.x) < 0.6 && performance.now() - input.lastLook > 1200) {
      let d = player.yaw + Math.PI - camYaw;
      d = Math.atan2(Math.sin(d), Math.cos(d));
      camYaw += clamp(d, -1, 1) * 1.6 * dt;
    }
    camTarget.set(player.pos.x, player.pos.y + 1.45, player.pos.z);
    const cp = Math.cos(camPitch);
    tmpA.set(Math.sin(camYaw) * cp, Math.sin(camPitch), Math.cos(camYaw) * cp);
    // keep the camera outside walls: shorten the boom when the ray crosses a building footprint
    let allowed = camDist;
    const hit = ground.segmentBlocked(camTarget.x, camTarget.z, camTarget.x + tmpA.x * camDist, camTarget.z + tmpA.z * camDist);
    if (hit) allowed = Math.max(1.0, camDist * hit - 0.5);
    camDistEff += (allowed - camDistEff) * (allowed < camDistEff ? 1 - Math.exp(-dt * 20) : 1 - Math.exp(-dt * 3));
    if (camSnap) camDistEff = allowed;
    tmpB.copy(camTarget).addScaledVector(tmpA, camDistEff);
    tmpB.y += 0.25;
    const gh = ground.height(tmpB.x, tmpB.z);
    const floor = (gh === gh ? gh : player.pos.y) + 0.55;
    if (tmpB.y < floor) tmpB.y = floor;
    if (camSnap) camPos.copy(tmpB);
    else camPos.lerp(tmpB, 1 - Math.exp(-dt * 14));
    camera.position.copy(camPos);
    camera.lookAt(camTarget);
    if (photo) fovTarget = photoFov;
    else if (!settings.reduceMotion) fovTarget = 58 + clamp((player.speed - SPEED.walk) / (SPEED.sprint - SPEED.walk), 0, 1) * 9;
  }
  camSnap = false;
  if (photo && !player.riding) fovTarget = photoFov;
  fovNow += (fovTarget - fovNow) * (1 - Math.exp(-dt * 6));
  if (Math.abs(camera.fov - fovNow) > 0.02) {
    camera.fov = fovNow;
    camera.updateProjectionMatrix();
  }
}

// ---------------------------------------------------------------------------------------------------- shadow box
const lightX = new THREE.Vector3();
const lightY = new THREE.Vector3();
const shadowCenter = new THREE.Vector3();
let shadowFrame = 0;
function updateShadow(center) {
  const L = tod.lightDir;
  lightX.crossVectors(UP, L).normalize();
  lightY.crossVectors(L, lightX);
  const texel = (2 * preset.shadowRange) / preset.shadow;
  const a = center.dot(lightX);
  const b = center.dot(lightY);
  shadowCenter.copy(center).addScaledVector(lightX, Math.round(a / texel) * texel - a).addScaledVector(lightY, Math.round(b / texel) * texel - b);
  sunLight.position.copy(shadowCenter).addScaledVector(L, 160);
  sunLight.target.position.copy(shadowCenter);
  sunLight.target.updateMatrixWorld();
  let need = shadowForce || tod.moving || player.speed > 0.03 || player.jumpT !== null || (train.armT > 0.01 && train.armT < 0.99);
  if (!need && train.state !== 'wait' && train.speed > 0.05) {
    const [x0, x1] = train.span();
    need = center.x > x0 - preset.shadowRange - 20 && center.x < x1 + preset.shadowRange + 20;
  }
  if (!need && ++shadowFrame % 4 === 0) need = true; // idle animation / drifting clouds
  sunLight.shadow.needsUpdate = need;
  shadowForce = false;
}

// ---------------------------------------------------------------------------------------------------- loop
let last = performance.now();
let elapsed = 0;
let uiTimer = 0;
let lodTimer = 1;
let soundTimer = 0;
const soundState = { alarm: false, crossDist: 0, sea: 0, night: 0, trainSpeed: 0, trainDist: 1e9, riding: false };
let mapTimer = 0;
let lastPrompt = null;
let slow = 0;
const trainView = { visible: false, span: [0, 0] };

function frame(now) {
  requestAnimationFrame(frame);
  const raw = Math.min((now - last) / 1000, 0.5);
  last = now;
  const dt = Math.min(raw, 0.05);
  elapsed += dt;
  U.uTime.value = elapsed;
  if (raw > 0) renderer.tick(raw);
  ui.fps(raw);

  if (!ready) {
    camera.position.set(0, 3, 0);
    camera.lookAt(0, 3, -1);
    sky.position.copy(camera.position);
    sky.scale.setScalar(20000);
    renderer.render(scene, camera);
    return;
  }

  input.pollPad();
  const cmd = isBlocked() ? ZERO : input.read();
  train.update(dt, tod.night);
  if (started && !player.riding && !photo) {
    player.update(dt, cmd, camYaw, gate);
    crossingRules(dt);
  } else player.update(dt, ZERO, camYaw, null);
  if (!started) camYaw += dt * 0.06; // slow orbit behind the title panel

  updateCamera(dt, cmd);
  tod.update(dt, player.pos);
  sky.position.copy(camera.position);
  sky.scale.setScalar(20000);
  sea.position.x = Math.round(camera.position.x / 50) * 50;
  sea.position.z = Math.round(camera.position.z / 50) * 50;
  sea.userData.normalMap.offset.set((elapsed * 0.0009) % 1, (elapsed * 0.0006) % 1);
  glow.visible = preset.glow && glow.material.opacity > 0.01;
  updateShadow(player.pos);

  lodTimer += dt;
  if (lodTimer > 0.5) {
    lodTimer = 0;
    updateTreeLOD(treesGroup, player.pos.x, player.pos.z, preset.shadowRange);
  }

  // ---- audio + HUD
  soundTimer += dt;
  if (soundTimer > 0.033) {
    soundTimer = 0;
    let dTrain = 1e9;
    if (train.state !== 'wait') {
      const sp = train.span();
      dTrain = Math.abs(player.pos.x - clamp(player.pos.x, sp[0], sp[1])) + Math.abs(player.pos.z);
    }
    soundState.alarm = train.alarm;
    soundState.crossDist = Math.hypot(player.pos.x, player.pos.z);
    soundState.sea = clamp((player.pos.z - 12) / 25, 0, 1);
    soundState.night = tod.night;
    soundState.trainSpeed = train.speed;
    soundState.trainDist = dTrain;
    soundState.riding = player.riding;
    sound.update(soundState);
  }

  uiTimer += dt;
  if (uiTimer > 0.25 && started) {
    uiTimer = 0;
    let best = null;
    let bd = 1e9;
    for (const p of meta.poi) {
      const d = Math.hypot(p.x - player.pos.x, -p.y - player.pos.z);
      if (d < bd) {
        bd = d;
        best = p;
      }
    }
    ui.setWhere(best ? (settings.lang === 'en' ? best.en : best.name) : '', bd);
    ui.setTrain(train.info(), player.riding);
    const prompt = player.riding ? (train.state === 'dwell' ? t('alightPrompt') : null) : train.canBoard(player.pos) ? t('boardPrompt') : null;
    if (prompt !== lastPrompt) {
      lastPrompt = prompt;
      ui.setPrompt(prompt, !isTouch);
    }
  }
  mapTimer += dt;
  if (mapTimer > 0.08 && started && !photo) {
    mapTimer = 0;
    trainView.visible = train.state !== 'wait';
    trainView.span = train.span();
    const yaw = player.riding ? (train.dir > 0 ? Math.PI / 2 : -Math.PI / 2) : player.yaw;
    ui.drawMinimap(player.pos, yaw, trainView);
  }

  // auto quality: step down one preset when even a reduced resolution cannot hold the frame rate
  if (settings.quality === 'auto' && !params.has('q') && renderer.govern) {
    if (renderer.ema > 27 && renderer.dpr <= renderer.baseDpr * 0.7) slow += dt;
    else slow = Math.max(0, slow - dt);
    if (slow > 5 && level !== 'low') {
      applyQuality(level === 'high' ? 'medium' : 'low');
      ui.showMsg(t('quality_now', { q: t(`q_${level}`) }), 2500);
      slow = 0;
    }
  }

  renderer.render(scene, camera);
  if (wantShot) {
    wantShot = false;
    savePhoto();
  }
}

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.resize();
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden) sound.ctx?.suspend();
});

$('start').addEventListener('click', () => {
  started = true;
  camSnap = true;
  $('loading').classList.add('hidden');
  $('hud').classList.remove('hidden');
  if (isTouch) $('touch').classList.remove('hidden');
  sound.volume = settings.volume;
  sound.muted = settings.muted;
  sound.init();
  ui.showMsg(t('start_msg'), 2200);
  setTimeout(() => ($('help').style.opacity = '0.7'), 6000);
  canvas.focus();
});

requestAnimationFrame((n) => {
  last = n;
  frame(n);
});
load().catch((e) => {
  console.error(e);
  $('loadtext').textContent = `${t('failed')}: ${e.message}`;
});

// debug / test handle
window.__enoden = {
  get worldRoot() { return worldRoot; },
  get player() { return player; },
  get train() { return train; },
  get ready() { return ready; },
  get level() { return level; },
  camera,
  scene,
  renderer,
  tod,
  settings,
  get ui() { return ui; },
  get ground() { return ground; },
  setCam: (y, p, d) => {
    camYaw = y;
    camPitch = p;
    camDist = d;
    camSnap = true;
  },
  setTime,
  start: () => $('start').click(),
  goto: (x, z, yaw) => {
    player.teleport(x, z, yaw);
    camYaw = yaw + Math.PI;
    camSnap = true;
    shadowForce = true;
  },
  board: toggleBoard,
  applyQuality,
};
