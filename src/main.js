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
import { makeRain } from './weather.js';
import { installFog } from './atmos.js';
import { wetMats } from './fx.js';
import { makePetals, makeGulls } from './critters.js';
import { Pedestrians } from './people.js';
import { Traffic } from './traffic.js';
import { makeDeckPools } from './lights.js';
import { StepFx } from './steps.js';
import { Guide, makeBeacon } from './guide.js';

installFog(); // must run before any material compiles
import { makeLoaders, makeEnvironment, tunePBR, styleWorld, styleCharacter } from './world.js';

const BASE = import.meta.env.BASE_URL;
const $ = (id) => document.getElementById(id);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const ZERO = { x: 0, y: 0, run: false, sprint: false };
const UP = new THREE.Vector3(0, 1, 0);
const TIMES = ['day', 'dusk', 'night'];
const PEOPLE_COUNT = [0, 4, 6]; // by preset.detail (low/medium/high+ultra): now real rigged SkinnedMesh extras (B3), so kept fewer than the old box-primitive crowd
const CAR_COUNT = [0, 4, 6];
const isTouch = typeof matchMedia === 'function' && matchMedia('(pointer: coarse)').matches;
/** short taptic buzz for jump / alarm / train hit; a no-op where Vibration API isn't available (iOS Safari) */
const vibrate = (pattern) => {
  try {
    navigator.vibrate?.(pattern);
  } catch {
    /* unsupported */
  }
};

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
document.body.dataset.handed = settings.handed;

// ---------------------------------------------------------------------------------------------------- renderer / scene
const canvas = $('c');
const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0xe9c6a0, 0.00085);
const camera = new THREE.PerspectiveCamera(58, innerWidth / innerHeight, 0.3, 150000);
let renderer;
try {
  renderer = new Renderer(canvas, preset, { govern: !params.has('nogov'), scene, camera });
} catch (err) {
  $('loadtext').textContent = t('nowebgl');
  throw err;
}
const gl = renderer.gl;
renderer.setMotionBlur(settings.quality === 'ultra' && settings.motionBlur);
renderer.setDof(settings.quality === 'ultra' && settings.dof);
const hemi = new THREE.HemisphereLight(0xffffff, 0x888888, 0.6);
const sunLight = new THREE.DirectionalLight(0xffffff, 3);
sunLight.castShadow = true;
sunLight.shadow.bias = -0.0006;
sunLight.shadow.normalBias = 0.05;
sunLight.shadow.camera.near = 1;
sunLight.shadow.camera.far = 320;
sunLight.shadow.autoUpdate = false; // refreshed only when something inside the box moved (see updateShadow)
scene.add(hemi, sunLight, sunLight.target);
const sky = makeSky(preset.clouds, preset.skyPhysical);
scene.add(sky);
const lampsPos = [];
let pointLights = [];
let rain = null;
let petals = null;
let gulls = null;
let deckPools = null;
let stepFx = null;
let guide = null;
let beacon = null;
let autoFwd = false;
const sunNdc = new THREE.Vector3();
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
let pedestrians;
let traffic;
let carsG;
let pedestrianTemplates;
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
const trainLookPos = new THREE.Vector3();

// ---------------------------------------------------------------------------------------------------- loading
// decoded sizes in bytes: progress is measured against them because the server compresses (content-length is the encoded size)
const SIZES = {
  meta: 2393, ground: 492984, surface: 123246, solid: 123246, trees: 103893, world: 4100056, train: 303360,
  character: 1429804, cars: 201536, ped0: 4961024, ped1: 4926104,
};
const PED_FILES = ['ped0', 'ped1'];
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
  const M = (f) => `${BASE}models/${f}?v=${__BUILD__}`;
  meta = await (await fetch(M('meta.json'))).json();
  progress('meta', 1);
  const [gbuf, sbuf, obuf, trees, wbuf, tbuf, cbuf, carbuf, ...pedbufs] = await Promise.all([
    fetchBuf('ground', M('ground.bin')),
    fetchBuf('surface', M('surface.bin')),
    fetchBuf('solid', M('solid.bin')),
    fetch(M('trees.json')).then((r) => r.json()).then((j) => (progress('trees', 1), j)),
    fetchBuf('world', M('world.glb')),
    fetchBuf('train', M('train.glb')),
    fetchBuf('character', M('character.glb')),
    fetchBuf('cars', M('cars.glb')),
    ...PED_FILES.map((name) => fetchBuf(name, M(`${name}.glb`))),
  ]);
  $('loadtext').textContent = t('assembling');
  await new Promise((r) => setTimeout(r, 30));
  treesData = trees;
  ground = new Ground(meta.grid, gbuf, sbuf, obuf);
  ground.clearDeck(meta.platform);
  // the only way onto the platform is the ramp at its west end: make it a teleport spot too
  meta.poi.push({ name: 'ホーム入口（西のスロープ）', en: 'Platform entrance (west ramp)', x: meta.platform.x0 - 2.5, y: (meta.platform.y0 + meta.platform.y1) / 2 });
  ground.addTrees(trees.trees);
  const [worldG, trainG, charG, carsGltf, ...pedG] = await Promise.all([parse(wbuf), parse(tbuf), parse(cbuf), parse(carbuf), ...pedbufs.map(parse)]);
  carsG = carsGltf;
  pedestrianTemplates = pedG;

  worldRoot = worldG.scene;
  tunePBR(worldRoot);
  chunkWorld(worldRoot); // spatial chunks: culling works for the main view and the shadow view
  styleWorld(worldRoot, preset);
  scene.add(worldRoot);
  treesGroup = makeTrees(trees, preset);
  scene.add(treesGroup);
  sea = makeSea(ground, meta.sea_level, preset.seaDepth, preset.waves);
  scene.add(sea);
  rain = makeRain();
  scene.add(rain);
  petals = makePetals();
  scene.add(petals);
  gulls = makeGulls();
  scene.add(gulls);
  beacon = makeBeacon();
  scene.add(beacon);

  // street lamps + the fluorescent tubes under the platform canopy glow at night
  lampsPos.push(...meta.lamps);
  for (let k = 0; k < 10; k++) lampsPos.push([meta.platform.x0 + 2.25 + 4.5 * k, meta.platform.height + 2.35, -(meta.platform.y0 + meta.platform.y1) / 2]);
  deckPools = makeDeckPools(meta);
  scene.add(deckPools.mesh);
  glow = makeLampGlow(lampsPos);
  glow.visible = false;
  scene.add(glow);
  tod.glowPoints = glow;
  buildPointLights();

  train = new Train(trainG, worldRoot, meta);
  train.style(preset);
  scene.add(train.group);
  pedestrians = new Pedestrians(pedestrianTemplates, ground, meta, PEOPLE_COUNT[preset.detail] ?? 0);
  scene.add(pedestrians.group);
  traffic = new Traffic(carsG, ground, meta, CAR_COUNT[preset.detail] ?? 0);
  scene.add(traffic.group);
  const sp = meta.spawn;
  player = new Player(charG, ground, { x: sp.x, z: -sp.y, yaw: Math.atan2(-sp.x, sp.y) });
  stepFx = new StepFx(scene, ground);
  guide = new Guide(ground);
  player.onStep = (surf, speed) => {
    sound.step(surf, speed);
    stepFx.step(surf, speed, player);
  };
  player.setDetail(preset.detail);
  styleCharacter(player.model, preset);
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
  applyLinkParams();
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
  sky.material.defines.PHYSICAL = preset.skyPhysical ? 1 : 0;
  sky.material.needsUpdate = true;
  if (!ready) return;
  styleWorld(worldRoot, preset);
  disposeGroup(treesGroup);
  treesGroup = makeTrees(treesData, preset);
  scene.add(treesGroup);
  updateTreeLOD(treesGroup, player.pos.x, player.pos.z, preset.shadowRange);
  player.setDetail(preset.detail);
  styleCharacter(player.model, preset);
  train.style(preset);
  disposeGroup(sea);
  sea = makeSea(ground, meta.sea_level, preset.seaDepth, preset.waves);
  scene.add(sea);
  disposeGroup(pedestrians.group);
  pedestrians = new Pedestrians(pedestrianTemplates, ground, meta, PEOPLE_COUNT[preset.detail] ?? 0);
  scene.add(pedestrians.group);
  disposeGroup(traffic.group);
  traffic = new Traffic(carsG, ground, meta, CAR_COUNT[preset.detail] ?? 0);
  scene.add(traffic.group);
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
    guide?.cancel();
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

function setTime(name, persist = true) {
  settings.time = name;
  tod.set(name);
  ui.setTimeIcon(name);
  if (persist) saveSettings(settings);
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

/** ?x=&z=&yaw=&cy=&cp=&t= : the place, view and time of day someone shared */
function applyLinkParams() {
  const num = (k) => (params.has(k) && Number.isFinite(+params.get(k)) ? +params.get(k) : null);
  const x = num('x');
  const z = num('z');
  if (x === null || z === null) return;
  const [px, pz] = findWalkable(x, z);
  const yaw = num('yaw') ?? player.yaw;
  player.teleport(px, pz, yaw);
  camYaw = num('cy') ?? yaw + Math.PI;
  camPitch = clamp(num('cp') ?? camPitch, -0.12, 1.25);
  camSnap = true;
  shadowForce = true;
}

function shareUrl() {
  const q = new URLSearchParams();
  if (player && ready) {
    q.set('x', player.pos.x.toFixed(1));
    q.set('z', player.pos.z.toFixed(1));
    q.set('yaw', player.yaw.toFixed(2));
    q.set('cy', camYaw.toFixed(2));
    q.set('cp', camPitch.toFixed(2));
  }
  q.set('t', settings.time);
  return `${location.origin}${location.pathname}?${q}`;
}

async function share() {
  const data = { title: t('title'), text: t('subtitle'), url: shareUrl() };
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
  jump: () => {
    if (isBlocked()) return;
    player.jump();
    vibrate(15);
  },
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
  stick: (a, x, y, dx, dy) => {
    if (a && !$('tutorial').classList.contains('hidden')) {
      $('tutorial').classList.add('hidden');
      try {
        localStorage.setItem('enoden-walk.tutorialSeen.v1', '1');
      } catch {
        /* private mode: ignore */
      }
    }
    ui.stick(a, x, y, dx, dy);
  },
  autoWalk: () => {
    if (isBlocked() || player.riding) return;
    autoFwd = !autoFwd;
    if (autoFwd && guide.active) guide.auto = false;
    ui.showMsg(t(autoFwd ? 'autowalk_on' : 'autowalk_off'), 1600);
  },
  // ---- UI callbacks
  goto: gotoSpot,
  guideTo: (p) => {
    const [x, z] = ground.walkable(p.x, -p.y) && !ground.isSolid(p.x, -p.y) ? [p.x, -p.y] : findWalkable(p.x, -p.y);
    startGuide(x, z, guideName(p), false);
  },
  mapTap: (u, v) => {
    if (isBlocked() || player.riding) return;
    const k = 88 / 62; // minimap pixels per cell
    let x = player.pos.x + ((u - 88) / k) * ground.step;
    let z = player.pos.z + ((v - 88) / k) * ground.step;
    if (!ground.walkable(x, z) || ground.isSolid(x, z)) [x, z] = findWalkable(x, z);
    startGuide(x, z, t('nav_target'), true);
  },
  goPlatform: () => {
    if (isBlocked() || player.riding) return;
    const pf = meta.platform;
    startGuide((pf.x0 + pf.x1) / 2, -(pf.y0 + pf.y1) / 2, t('st_here'), true);
  },
  callTrain: () => {
    if (train.state !== 'wait') return;
    train.timer = Math.min(train.timer, 0.3);
    ui.showMsg(t('train_called'), 2400);
    vibrate(20);
  },
  navAuto: () => {
    if (!guide.active) return;
    guide.auto = !guide.auto;
    autoFwd = false;
  },
  navStop: () => guide.cancel(),
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
    input.enabled = started && !open; // while a dialog is open the keyboard belongs to it (Tab / Esc navigation)
    if (open) document.exitPointerLock?.();
  },
  changed: (key) => {
    if (key === 'quality') {
      const next = resolveLevel();
      if (next !== level) applyQuality(next);
    } else if (key === 'volume') sound.setVolume(settings.volume);
    else if (key === 'announce') {
      sound.announceOn = settings.announce;
      if (!settings.announce) window.speechSynthesis?.cancel();
    } else if (key === 'muted') {
      sound.muted = settings.muted;
      sound.applyVolume();
    } else if (key === 'viewMode' && settings.viewMode !== 'lock') document.exitPointerLock?.();
    else if (key === 'motionBlur') renderer.setMotionBlur(settings.motionBlur);
    else if (key === 'dof') renderer.setDof(settings.dof);
    else if (key === 'lang') {
      ui.lastWhere = '';
      ui.lastTrain = '';
    }
    saveSettings(settings);
  },
};

ui = new UI({ t, settings, hooks, touch: isTouch });
input = new Input(canvas, settings, hooks);
input.enabled = false; // until the walk starts (the title panel keeps normal keyboard navigation)
$('fps').classList.toggle('hidden', !settings.fps);
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
  if (train.alarm && !wasAlarm) {
    ui.showMsg(t('alarm'), 3000);
    vibrate([40, 60, 40, 60, 40]);
  }
  wasAlarm = train.alarm;
  if (train.hits(p)) {
    // knocked back to the nearer verge instead of being sent home
    const side = p.z >= 0 ? 1 : -1;
    const z = side * 2.5;
    if (ground.walkable(p.x, z) && !ground.isSolid(p.x, z)) player.teleport(p.x, z, player.yaw);
    else player.teleport(meta.spawn.x, -meta.spawn.y, player.yaw);
    ui.showMsg(t('hit'), 3200);
    vibrate(120);
    return;
  }
  if (train.alarm && Math.abs(p.x) < 4.2 && Math.abs(p.z) < 3.6) {
    const open = (x, z) => ground.walkable(x, z) && !ground.isSolid(x, z);
    let s = p.z >= 0 ? 1 : -1;
    if (!open(p.x, p.z + s * 1.2) && open(p.x, p.z - s * 1.2)) s = -s; // the nearer verge is walled off: leave by the other one
    const nz = p.z + s * 2.6 * dt;
    if (open(p.x, nz)) p.z = nz;
    else p.x += (p.x >= 0 ? 1 : -1) * 2.6 * dt;
    if (!pushMsg) {
      pushMsg = true;
      ui.showMsg(t('clearCrossing'), 2200);
    }
  } else pushMsg = false;
}

// ---------------------------------------------------------------------------------------------------- announcements
let prevState = 'wait';
let prevStopping = false;
let hintShown = false;
let autoTimeT = 0;
let trainDist = 1e9;

function announce(key, vars, text = true) {
  const msg = t(key, vars);
  if (text) ui.showMsg(msg, 4200);
  sound.announce(msg, settings.lang);
}

function trainEvents(dt) {
  const pf = meta.platform;
  const p = player.pos;
  const nearPlatform = p.x > pf.x0 - 45 && p.x < pf.x1 + 45 && Math.abs(p.z) < 30;
  if (train.state === 'move' && prevState === 'wait' && !player.riding && nearPlatform) announce(train.dir > 0 ? 'say_arriving_east' : 'say_arriving_west');
  if (player.riding) {
    if (train.state === 'move' && prevState === 'dwell') {
      const st = t(train.dir > 0 ? 'st_koshigoe' : 'st_shichiri');
      ui.showMsg(t('depart_next', { st }), 4200);
      sound.announce(t('say_depart', { st }), settings.lang);
    } else if (train.stopping && !prevStopping && train.state === 'move') {
      const st = t('st_here');
      ui.showMsg(t('soon_here', { st }), 4200);
      sound.announce(t('say_soon', { st }), settings.lang);
    }
  }
  prevState = train.state;
  prevStopping = train.stopping;

  // the way onto the platform is easy to miss: say so once when the player lingers near it
  if (!hintShown && elapsed > 4 && !player.riding && p.y < 0.5 && p.x > pf.x0 - 30 && p.x < pf.x1 + 20 && p.z > -12 && p.z < 30) {
    hintShown = true;
    ui.showMsg(t('platform_hint'), 4200);
  }

  // optional day -> dusk -> night cycle
  if (settings.autoTime && started && !photo && !modalOpen) {
    autoTimeT += dt;
    if (autoTimeT > 80) {
      autoTimeT = 0;
      setTime(TIMES[(TIMES.indexOf(settings.time) + 1) % TIMES.length], false);
    }
  }

  // wind gust while a train rushes by
  let g = 0;
  if (train.state !== 'wait') {
    const sp = train.span();
    trainDist = Math.abs(p.x - clamp(p.x, sp[0], sp[1])) + Math.abs(p.z);
    g = clamp(1 - trainDist / 45, 0, 1) * (train.speed / 11);
  } else trainDist = 1e9;
  U.uGust.value += (g - U.uGust.value) * Math.min(1, dt * 2.2);
}

// ---------------------------------------------------------------------------------------------------- guidance
function startGuide(x, z, name, auto) {
  if (!guide) return false;
  autoFwd = false;
  if (!guide.set(player, x, z, name, auto)) {
    ui.showMsg(t('nav_none'), 2600);
    return false;
  }
  const e = guide.takeEvent();
  if (e === 'unreachable') ui.showMsg(t('nav_near'), 3600);
  return true;
}

const guideName = (p) => (settings.lang === 'en' ? p.en : p.name);

/** the movement command actually fed to the player: keyboard / stick, auto-walk forward or the guide's steering */
function steerCommand(dt, cmd) {
  if (!guide) return cmd;
  if (player.riding || photo || !started) {
    if (guide.active) guide.cancel();
    autoFwd = false;
    return cmd;
  }
  const mag = Math.hypot(cmd.x, cmd.y);
  if (mag > 0.15) {
    if (autoFwd) {
      autoFwd = false;
      ui.showMsg(t('autowalk_off'), 1200);
    }
    if (guide.active && guide.auto) {
      guide.auto = false;
      ui.showMsg(t('nav_manual_now'), 2400);
    }
  }
  let out = cmd;
  if (autoFwd && mag <= 0.15) out = { x: 0, y: 1, run: cmd.run, sprint: cmd.sprint };
  const g = guide.update(dt, player, camYaw, train.alarm);
  if (g && mag <= 0.15 && !autoFwd) out = g;
  const ev = guide.takeEvent();
  if (ev === 'arrived' || ev === 'unreachable-arrived') ui.showMsg(t('nav_arrived'), 2400);
  else if (ev === 'lost') ui.showMsg(t('nav_lost'), 3000);
  else if (ev === 'hold') ui.showMsg(t('nav_hold'), 2600);
  return out;
}

let navTimer = 0;
function updateNavHud(dt) {
  navTimer += dt;
  if (navTimer < 0.1) return;
  navTimer = 0;
  if (!guide || !guide.active || photo || player.riding) {
    ui.setNav(null);
    beacon.visible = false;
    return;
  }
  const n = guide.next();
  const dx = n[0] - player.pos.x;
  const dz = n[1] - player.pos.z;
  const fx = -Math.sin(camYaw);
  const fz = -Math.cos(camYaw);
  const angle = Math.atan2(dx * -fz + dz * fx, dx * fx + dz * fz);
  ui.setNav({ name: guide.name, m: guide.remaining(player), angle, auto: guide.auto });
  const [tx, tz] = guide.target;
  const gh = ground.height(tx, tz);
  beacon.position.set(tx, gh === gh ? gh : player.pos.y, tz);
  beacon.visible = Math.hypot(tx - player.pos.x, tz - player.pos.z) > 5;
  beacon.material.uniforms.uT.value = elapsed;
}

// ---------------------------------------------------------------------------------------------------- visuals
/** everything that follows the time of day / weather / camera and is not part of the scene graph proper */
function updateVisuals(dt) {
  camera.updateMatrixWorld();
  const cur = tod.cur;
  const sunUp = THREE.MathUtils.smoothstep(cur.sunEl, -6, 6);
  U.uSunView.value.copy(tod.sunDir).transformDirection(camera.matrixWorldInverse);
  U.uWet.value += ((settings.rain ? 1 : 0) - U.uWet.value) * Math.min(1, dt * 0.25);
  for (const m of wetMats) m.envMapIntensity = 0.7 + 1.2 * U.uWet.value;
  U.uCloudSh.value = settings.reduceMotion ? 0 : clamp(cur.cloud, 0, 1) * sunUp * (1 - cur.night);

  const a = renderer.atmos;
  if (a) {
    const u = a.uniforms;
    sunNdc.copy(camera.position).addScaledVector(tod.sunDir, 1000).project(camera);
    const front = U.uSunView.value.z < 0 ? 1 : 0;
    const clear = 1 - U.uWet.value * 0.8;
    u.uSunUV.value.set(sunNdc.x * 0.5 + 0.5, sunNdc.y * 0.5 + 0.5);
    u.uShaft.value = cur.shaft * sunUp * front * clear;
    u.uFlare.value = cur.flare * sunUp * front * clear;
    u.uAspect.value = camera.aspect;
    u.uHi.value.copy(cur.gradeHi);
    u.uSh.value.copy(cur.gradeSh);
    u.uSat.value = cur.sat;
    u.uVig.value = cur.vig;
    u.uTime.value = elapsed % 100;
  }
  if (renderer.grade) {
    renderer.grade.uniforms.uAspect.value = camera.aspect;
    renderer.grade.uniforms.uTime.value = elapsed % 100;
  }
  if (renderer.ssao) renderer.updateAoBox(player.pos);
  if (renderer.dof) renderer.setFocus(Math.max(2, camDistEff));

  const pxScale = (0.5 * gl.domElement.height) / Math.tan((camera.fov * Math.PI) / 360);
  deckPools.update(cur.night);
  petals.userData.set(!settings.reduceMotion, camera, pxScale, cur.night);
  gulls.userData.update(dt, cur.night, cur.lightColor);
  stepFx.update(dt, player, player.root.visible && !player.riding, cur.night, pxScale);
  pedestrians.update(dt, player.pos);
  traffic.update(dt, cur.night, train.alarm);
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
let lastSoundD = 1e9;
let rainLevel = 0;
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
  train.update(dt, tod.night, tod.cur.glow);
  trainEvents(dt);
  // C4.3: glance toward an approaching / dwelling train instead of staring straight ahead while waiting
  if (!player.riding && (train.state === 'arriving' || train.state === 'dwell')) {
    trainLookPos.copy(train.group.position).setY(1.5);
    player.lookTarget = trainLookPos;
  } else player.lookTarget = null;
  const eff = steerCommand(dt, cmd);
  if (started && !player.riding && !photo) {
    player.update(dt, eff, camYaw, gate);
    crossingRules(dt);
  } else player.update(dt, ZERO, camYaw, null);
  if (!started) camYaw += dt * 0.06; // slow orbit behind the title panel

  updateCamera(dt, eff);
  tod.update(dt, player.pos);
  rainLevel = rain ? rain.userData.set(settings.rain, camera, tod.night) : 0;
  updateVisuals(dt);
  updateNavHud(dt);
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
    const sdt = soundTimer;
    soundTimer = 0;
    const dTrain = trainDist;
    const pf = meta.platform;
    soundState.approach = lastSoundD < 1e8 && dTrain < 1e8 ? clamp((lastSoundD - dTrain) / (sdt * 11), -1, 1) : 0;
    lastSoundD = dTrain;
    soundState.deck = player.pos.y > 0.6 && player.pos.x > pf.x0 && player.pos.x < pf.x1 && player.pos.z < -1.35 && player.pos.z > -pf.y1 ? 1 : 0;
    soundState.rain = rainLevel;
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
    const pf = meta.platform;
    const onDeck = player.pos.y > 0.6 && player.pos.x > pf.x0 - 3 && player.pos.x < pf.x1 && player.pos.z < -1.4 && player.pos.z > -pf.y1;
    ui.setQuick(!player.riding && !onDeck && !(guide && guide.active), !player.riding && train.state === 'wait');
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
    ui.drawMinimap(player.pos, yaw, trainView, guide && guide.active ? guide : null);
  }

  // auto quality: step down one preset when even a reduced resolution cannot hold the frame rate
  if (settings.quality === 'auto' && !params.has('q') && renderer.govern) {
    if (renderer.ema > 27 && renderer.dpr <= renderer.baseDpr * 0.7) slow += dt;
    else slow = Math.max(0, slow - dt);
    if (slow > 5 && level !== 'low') {
      const STEP_DOWN = { ultra: 'high', high: 'medium', medium: 'low' };
      applyQuality(STEP_DOWN[level] ?? 'low');
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
  input.enabled = true;
  camSnap = true;
  $('loading').classList.add('hidden');
  $('hud').classList.remove('hidden');
  $('installBanner').classList.add('hidden'); // avoid covering the in-game toolbar; it only makes sense on the title screen
  if (isTouch) {
    $('touch').classList.remove('hidden');
    let tutorialSeen = false;
    try {
      tutorialSeen = !!localStorage.getItem('enoden-walk.tutorialSeen.v1');
    } catch {
      /* private mode: ignore */
    }
    if (!tutorialSeen) $('tutorial').classList.remove('hidden');
  }
  sound.volume = settings.volume;
  sound.muted = settings.muted;
  sound.announceOn = settings.announce;
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
  $('retry').classList.remove('hidden');
  $('retry').onclick = () => location.reload();
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
  get pedestrians() { return pedestrians; },
  get traffic() { return traffic; },
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
  U,
  get guide() { return guide; },
  hooks,
  get camYaw() { return camYaw; },
  /** advance the walking simulation without rendering (tests) */
  sim: (dt, cmd = ZERO) => {
    train.update(dt, tod.night, tod.cur.glow);
    trainEvents(dt);
    const eff = steerCommand(dt, cmd);
    player.update(dt, eff, camYaw, gate);
    crossingRules(dt);
  },
};

// model files are addressed by build id, so a cache-first service worker can never serve stale data
if ('serviceWorker' in navigator && location.protocol === 'https:') navigator.serviceWorker.register(`${BASE}sw.js`).catch(() => {});

// ---------------------------------------------------------------------------------------------------- "add to home screen" banner
const INSTALL_DISMISSED_KEY = 'enoden-walk.installDismissed.v1';
const alreadyStandalone = matchMedia('(display-mode: standalone)').matches || navigator.standalone;
let deferredInstallEvent = null;
function dismissInstallBanner() {
  $('installBanner').classList.add('hidden');
  try {
    localStorage.setItem(INSTALL_DISMISSED_KEY, '1');
  } catch {
    /* private mode: ignore */
  }
}
if (!alreadyStandalone) {
  let dismissed = false;
  try {
    dismissed = !!localStorage.getItem(INSTALL_DISMISSED_KEY);
  } catch {
    /* private mode: ignore */
  }
  if (!dismissed) {
    addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      deferredInstallEvent = e;
      $('installText').textContent = t('install_hint');
      $('installBtn').classList.remove('hidden');
      $('installBanner').classList.remove('hidden');
    });
    if (/iPad|iPhone|iPod/.test(navigator.userAgent)) {
      // iOS Safari never fires beforeinstallprompt; show a static how-to instead
      $('installText').textContent = t('install_hint_ios');
      $('installBanner').classList.remove('hidden');
    }
  }
}
$('installBtn').onclick = () => {
  deferredInstallEvent?.prompt();
  dismissInstallBanner();
};
$('installDismiss').onclick = dismissInstallBanner;
