// Phase N2 (train.js's seated passengers, kept as simple low-poly primitives — they're barely visible through the
// train windows, not worth the SkinnedMesh cost) / N3->B3 (wandering pedestrians, now the real Blender-modelled,
// rigged character from blender/character_male20s.py — see main.js's pedestrian_N.glb loading and PLAYER_SPEED
// below) driven by the same A* pathfinding the minimap's "walk here" guide already uses.
import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { clone as cloneSkinned } from 'three/examples/jsm/utils/SkeletonUtils.js';
import { findPath } from './nav.js';
import { U } from './fx.js';
import { SPEED as PLAYER_SPEED } from './player.js';

function tint(geo, hex) {
  const g = geo.toNonIndexed();
  const n = g.attributes.position.count;
  const c = new THREE.Color(hex);
  const arr = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    arr[i * 3] = c.r;
    arr[i * 3 + 1] = c.g;
    arr[i * 3 + 2] = c.b;
  }
  g.setAttribute('color', new THREE.BufferAttribute(arr, 3));
  return g;
}

/** Head (fixed skin tone) + shoulders + torso (white, tinted by the InstancedMesh's per-instance colour for
 *  clothing variety): the same block `train.js` builds its seated passengers from. */
export function makeTorsoGeometry() {
  const head = new THREE.SphereGeometry(0.105, 8, 6);
  head.translate(0, 0.60, 0);
  const shoulders = new THREE.BoxGeometry(0.44, 0.13, 0.25);
  shoulders.translate(0, 0.415, 0);
  const body = new THREE.BoxGeometry(0.32, 0.40, 0.21);
  body.translate(0, 0.155, 0);
  return mergeGeometries([tint(head, 0xd9a577), tint(shoulders, 0xffffff), tint(body, 0xffffff)]);
}

/** One leg, hip-hinged at y=0 (its own local origin), for a standing/walking pedestrian (seated passengers don't need one). */
function legGeometry() {
  const g = new THREE.BoxGeometry(0.11, 0.42, 0.13);
  g.translate(0, -0.21, 0);
  return g;
}

const WALK_SPEED = 1.0; // m/s: a stroll, well under the player's own walk speed so they read as background characters

/** Vertex-shader leg swing (same "InstancedMesh + onBeforeCompile" trick as the tree WIND shader): each instance's
 *  own position (baked into instanceMatrix) seeds a phase so a crowd doesn't swing in lockstep; `signOffset` puts
 *  the left/right leg of the same body half a cycle apart. */
function legMaterial(color, signOffset) {
  const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.85 });
  mat.customProgramCacheKey = () => `leg${signOffset}`;
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uTime = U.uTime;
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nuniform float uTime;')
      .replace(
        '#include <begin_vertex>',
        `#include <begin_vertex>
        {
          float phase = instanceMatrix[3].x * 0.7 + instanceMatrix[3].z * 0.9;
          float swing = sin(uTime * 6.2 + phase + ${signOffset.toFixed(1)}) * 0.30;
          transformed.z += swing * (-transformed.y);
        }`,
      );
  };
  return mat;
}

const WAYPOINT_NAMES = ['1号踏切', '鎌倉高校前駅', '海沿いの歩道', '国道134号'];
const ANIM_LOD_DIST = 45; // beyond this, freeze the walk pose (still moves/faces correctly, just stops animating) — cheap and unnoticeable that far out

/** A small wandering crowd: each pedestrian A*-paths (nav.js: findPath, the same routine the minimap guide uses)
 *  between a few fixed points of interest and loops. Each instance is a SkeletonUtils clone of one of a handful of
 *  pedestrian_N.glb variants (blender/character_male20s.py --seed/--outfit — same rigged, real-texture-baked
 *  pipeline as the player, see B1/B3), playing its own baked Walk cycle at a speed-matched timeScale so footfalls
 *  don't slide. Kept few (main.js: PEOPLE_COUNT) and shadow-less: a handful of real SkinnedMeshes already costs
 *  much more than the old box-primitive crowd did. */
export class Pedestrians {
  constructor(templates, ground, meta, count) {
    this.ground = ground;
    this.group = new THREE.Group();
    this.waypoints = meta.poi.filter((p) => WAYPOINT_NAMES.includes(p.name)).map((p) => [p.x, -p.y]);
    this.people = [];
    if (this.waypoints.length < 2 || !templates.length) return;

    const rnd = (seed) => Math.abs(Math.sin(seed * 12.9898) * 43758.5453) % 1;
    for (let i = 0; i < count; i++) {
      const tpl = templates[i % templates.length];
      const model = cloneSkinned(tpl.scene);
      model.traverse((o) => {
        if (o.name.startsWith('Rig')) o.position.set(0, 0, 0); // same origin-offset quirk player.js works around
        if (o.isMesh || o.isSkinnedMesh) {
          o.castShadow = false; // background extras — not worth the shadow-pass triangles at this count x real-mesh cost
          o.receiveShadow = false;
          o.frustumCulled = false;
        }
      });
      this.group.add(model);
      const mixer = new THREE.AnimationMixer(model);
      const clip = tpl.animations.find((c) => c.name === 'Male_Walk');
      const action = clip ? mixer.clipAction(clip) : null;
      const speed = WALK_SPEED * (0.8 + rnd(i) * 0.4);
      if (action) {
        action.play();
        action.timeScale = speed / PLAYER_SPEED.walk; // the clip was authored around the player's own walk speed
        action.time = rnd(i + 80) * (clip.duration || 1); // desync the crowd's gait phase
      }
      const p = { model, mixer, action, path: null, seg: 0, t: 0, pos: new THREE.Vector2(), yaw: 0, speed };
      const from = this.waypoints[i % this.waypoints.length];
      p.pos.set(from[0], from[1]);
      this._retarget(p, i);
      this.people.push(p);
    }
    this._apply(0, null); // first frame's transforms before the initial render
  }

  _retarget(p, seed) {
    this._tick = (this._tick || 0) + 1;
    const others = this.waypoints.filter((w) => Math.hypot(w[0] - p.pos.x, w[1] - p.pos.y) > 5);
    const pick = others.length ? others : this.waypoints;
    const r = Math.abs(Math.sin((seed + this._tick) * 7.13));
    const to = pick[Math.floor(r * pick.length) % pick.length];
    const result = findPath(this.ground, p.pos.x, p.pos.y, to[0], to[1]);
    p.path = result && result.points.length > 1 ? result.points : null;
    p.seg = 0;
    p.t = 0;
  }

  update(dt, refPos) {
    if (!this.people.length) return;
    for (let i = 0; i < this.people.length; i++) {
      const p = this.people[i];
      if (!p.path) {
        this._retarget(p, i);
        continue;
      }
      const a = p.path[p.seg];
      const b = p.path[p.seg + 1];
      if (!b) {
        this._retarget(p, i);
        continue;
      }
      const segLen = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1e-6;
      p.t += (p.speed * dt) / segLen;
      if (p.t >= 1) {
        p.seg++;
        p.t = 0;
        if (p.seg >= p.path.length - 1) {
          p.pos.set(b[0], b[1]);
          this._retarget(p, i);
          continue;
        }
      }
      const cur = p.path[p.seg];
      const nxt = p.path[p.seg + 1];
      p.pos.set(cur[0] + (nxt[0] - cur[0]) * p.t, cur[1] + (nxt[1] - cur[1]) * p.t);
      p.yaw = Math.atan2(nxt[0] - cur[0], nxt[1] - cur[1]);
    }
    this._apply(dt, refPos);
  }

  _apply(dt, refPos) {
    for (const p of this.people) {
      const gy = this.ground.height(p.pos.x, -p.pos.y);
      const y = gy === gy ? gy : 0;
      p.model.position.set(p.pos.x, y, -p.pos.y);
      p.model.rotation.y = p.yaw;
      const near = !refPos || Math.hypot(p.pos.x - refPos.x, -p.pos.y - refPos.z) < ANIM_LOD_DIST;
      if (near && dt > 0) p.mixer.update(dt);
    }
  }
}
