import * as THREE from 'three';
import { findPath, pathLength } from './nav.js';

const CROSSING = { x: 4.2, z: 3.6 }; // half extents of the gated area around the level crossing

/** Route guidance: keeps a path to a target, optionally walks it for the player (auto) and reports what a HUD needs. */
export class Guide {
  constructor(ground) {
    this.ground = ground;
    this.active = false;
    this.auto = false;
    this.target = null; // [x, z]
    this.name = '';
    this.points = [];
    this.i = 0;
    this.reached = true;
    this.replanT = 0;
    this.stuckT = 0;
    this.stuckCount = 0;
    this.last = null;
    this.holding = false;
    this.lastD = 1e9;
    this.event = null; // 'arrived' | 'lost' | 'hold' | 'unreachable', consumed by main.js
  }

  /** start guiding; returns false when no route exists */
  set(player, tx, tz, name, auto) {
    this.target = [tx, tz];
    this.name = name;
    this.auto = auto;
    this.stuckCount = 0;
    if (!this._plan(player)) {
      this.cancel();
      return false;
    }
    this.active = true;
    if (!this.reached) this.event = 'unreachable';
    return true;
  }

  cancel() {
    this.active = false;
    this.auto = false;
    this.points = [];
    this.target = null;
    this.holding = false;
  }

  _plan(player) {
    const r = findPath(this.ground, player.pos.x, player.pos.z, this.target[0], this.target[1]);
    if (!r) return false;
    this.points = r.points;
    this.reached = r.reached;
    this.i = Math.min(1, r.points.length - 1);
    this.lastD = 1e9;
    this.replanT = 0;
    return true;
  }

  /** metres left along the route */
  remaining(player) {
    if (!this.active || !this.points.length) return 0;
    const rest = [[player.pos.x, player.pos.z], ...this.points.slice(this.i)];
    return pathLength(rest);
  }

  /** the point the player should head for now */
  next() {
    return this.points[Math.min(this.i, this.points.length - 1)];
  }

  _blockedByGate(player, alarm) {
    if (!alarm) return false;
    const inside = (x, z) => Math.abs(x) < CROSSING.x && Math.abs(z) < CROSSING.z;
    if (inside(player.pos.x, player.pos.z)) return false;
    const n = this.next();
    if (!n) return false;
    for (let k = 1; k <= 8; k++) {
      const t = k / 8;
      if (inside(player.pos.x + (n[0] - player.pos.x) * t, player.pos.z + (n[1] - player.pos.z) * t)) return true;
    }
    return false;
  }

  /**
   * dt, player, camYaw, alarm.  Returns a movement command {x, y, run, sprint} while auto-walking, otherwise null.
   * Also keeps the route fresh and detects arrival / being stuck.
   */
  update(dt, player, camYaw, alarm) {
    if (!this.active) return null;
    const px = player.pos.x;
    const pz = player.pos.z;
    const goal = this.target;
    // arrival
    if (Math.hypot(px - goal[0], pz - goal[1]) < 1.8 || (!this.reached && this.i >= this.points.length - 1 && Math.hypot(px - this.points[this.points.length - 1][0], pz - this.points[this.points.length - 1][1]) < 1.5)) {
      this.event = this.reached ? 'arrived' : 'unreachable-arrived';
      this.cancel();
      return null;
    }
    this.replanT += dt;
    if (this.replanT > 1.6 && !this.holding) {
      if (!this._plan(player)) {
        this.event = 'lost';
        this.cancel();
        return null;
      }
    }
    // waypoint advance
    for (;;) {
      const n = this.next();
      const last = this.i >= this.points.length - 1;
      if (last) break;
      const d = Math.hypot(px - n[0], pz - n[1]);
      // reached it, or slipped past it (low frame rates): the distance starts growing again right next to it
      if (d < 0.6 || (d < 1.6 && this.lastD < 0.9 && d > this.lastD + 0.02)) {
        this.i++;
        this.lastD = 1e9;
      } else {
        this.lastD = d;
        break;
      }
    }
    if (!this.auto) return null;

    const hold = this._blockedByGate(player, alarm);
    if (hold && !this.holding) this.event = 'hold';
    this.holding = hold;
    if (hold) return { x: 0, y: 0, run: false, sprint: false };

    // stuck detection: no progress for a while -> replan, then give up
    this.stuckT += dt;
    if (this.stuckT > 1.4) {
      if (this.last && Math.hypot(px - this.last[0], pz - this.last[1]) < 0.35) {
        this.stuckCount++;
        if (this.stuckCount >= 4 || !this._plan(player)) {
          this.event = 'lost';
          this.cancel();
          return null;
        }
      } else this.stuckCount = 0;
      this.last = [px, pz];
      this.stuckT = 0;
    }

    const n = this.next();
    let dx = n[0] - px;
    let dz = n[1] - pz;
    const l = Math.hypot(dx, dz) || 1;
    dx /= l;
    dz /= l;
    // world direction -> input relative to the camera (inverse of Player.update's mapping)
    const fx = -Math.sin(camYaw);
    const fz = -Math.cos(camYaw);
    return { x: dz * fx - dx * fz, y: dx * fx + dz * fz, run: this.remaining(player) > 30, sprint: false };
  }

  /** consume the pending event */
  takeEvent() {
    const e = this.event;
    this.event = null;
    return e;
  }
}

/** a soft vertical light column marking the destination */
export function makeBeacon() {
  const geo = new THREE.CylinderGeometry(0.45, 0.45, 26, 20, 1, true);
  geo.translate(0, 13, 0);
  const mat = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
    fog: false,
    uniforms: { uT: { value: 0 } },
    vertexShader: /* glsl */ `
      varying float vY; void main() { vY = position.y / 26.0; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: /* glsl */ `
      uniform float uT; varying float vY;
      void main() { float a = (1.0 - vY) * (0.28 + 0.12 * sin(uT * 3.0 - vY * 8.0)); gl_FragColor = vec4(1.0, 0.72, 0.25, a); }`,
  });
  const m = new THREE.Mesh(geo, mat);
  m.visible = false;
  m.frustumCulled = false;
  m.renderOrder = 8;
  return m;
}
