import * as THREE from 'three';

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const smooth = (e0, e1, x) => {
  const t = clamp((x - e0) / (e1 - e0), 0, 1);
  return t * t * (3 - 2 * t);
};

export const SPEED = { walk: 1.25, run: 2.9, sprint: 6.0 };            // m/s = design speeds of the baked cycles
const NOMINAL = { walk: 32 / 30, run: 22 / 30, sprint: 15 / 30, idle: 4.0 };
const STRIDE = { walk: 1.25 * NOMINAL.walk, run: 2.9 * NOMINAL.run, sprint: 6.0 * NOMINAL.sprint };
const JUMP_HEIGHT = 0.42;

/** The Blender-baked man: cross-faded idle / walk / run / sprint cycles driven by the ground speed, plus a jump. */
export class Player {
  constructor(gltf, ground, spawn) {
    this.ground = ground;
    this.root = new THREE.Group();
    this.model = gltf.scene;
    this.model.traverse((o) => {
      if (o.isMesh || o.isSkinnedMesh) {
        o.castShadow = true;
        o.receiveShadow = true;
        o.frustumCulled = false;
      }
    });
    this.root.add(this.model);
    this.pos = new THREE.Vector3(spawn.x, 0, spawn.z);
    this.yaw = spawn.yaw;
    this.speed = 0;
    this.phase = 0;
    this.idleT = 0;
    this.jumpT = null;
    this.vel = new THREE.Vector3();
    this.lastDir = new THREE.Vector2(0, -1);
    this.groundY = ground.height(spawn.x, spawn.z);
    this.pos.y = this.groundY;

    this.mixer = new THREE.AnimationMixer(this.model);
    this.act = {};
    for (const clip of gltf.animations) {
      const key = clip.name.replace('Male_', '').toLowerCase();
      const a = this.mixer.clipAction(clip);
      a.play();
      a.paused = true;
      a.enabled = true;
      a.setEffectiveWeight(0);
      this.act[key] = a;
    }
    this.jumpDur = this.act.jump ? this.act.jump.getClip().duration : 1.5;
    this.apply();
  }

  jump() {
    if (this.jumpT === null) this.jumpT = 0;
  }

  /** input: {x, y} in [-1,1] (right / forward), run, sprint.  camYaw: camera azimuth.  gate(x, z): true when the position is closed off. */
  update(dt, input, camYaw, gate) {
    const mag = Math.min(1, Math.hypot(input.x, input.y));
    let target = 0;
    if (mag > 0.08) target = (input.sprint ? SPEED.sprint : input.run ? SPEED.run : SPEED.walk) * (input.run || input.sprint ? 1 : Math.max(0.55, mag));
    const acc = target > this.speed ? 7 : 10;
    this.speed += clamp(target - this.speed, -acc * dt, acc * dt);

    if (mag > 0.08) {
      const fx = -Math.sin(camYaw);
      const fz = -Math.cos(camYaw);
      const rx = -fz;
      const rz = fx;
      const dx = fx * input.y + rx * input.x;
      const dz = fz * input.y + rz * input.x;
      const l = Math.hypot(dx, dz) || 1;
      this.lastDir.set(dx / l, dz / l);
      const ty = Math.atan2(this.lastDir.x, this.lastDir.y);
      let d = ty - this.yaw;
      d = Math.atan2(Math.sin(d), Math.cos(d));
      this.yaw += clamp(d, -12 * dt, 12 * dt);
    }

    // ---- move with wall / slope / gate checks (axis-separated sliding)
    if (this.speed > 0.02) {
      const step = this.speed * dt;
      const mx = this.lastDir.x * step;
      const mz = this.lastDir.y * step;
      const tryMove = (nx, nz) => {
        const h1 = this.ground.height(nx, nz);
        if (!(h1 === h1) || h1 < -2.3) return false;
        const dist = Math.hypot(nx - this.pos.x, nz - this.pos.z) || 1e-6;
        if ((h1 - this.groundY) / dist > 1.15 && this.jumpT === null) return false;      // too steep to climb
        if (gate && gate(nx, nz, this.pos.x, this.pos.z)) return false;
        this.pos.x = nx;
        this.pos.z = nz;
        return true;
      };
      if (!tryMove(this.pos.x + mx, this.pos.z + mz)) {
        if (!tryMove(this.pos.x + mx, this.pos.z)) tryMove(this.pos.x, this.pos.z + mz);
      }
    }
    const gh = this.ground.height(this.pos.x, this.pos.z);
    if (gh === gh) this.groundY += (gh - this.groundY) * Math.min(1, dt * 18);

    // ---- jump: crouch (0.43 s), flight (0.57 s) matches the baked clip
    let jumpLift = 0;
    let wj = 0;
    if (this.jumpT !== null) {
      this.jumpT += dt;
      const t = this.jumpT;
      const t0 = 13 / 30;
      const t1 = 30 / 30;
      if (t > t0 && t < t1) {
        const u = (t - t0) / (t1 - t0);
        jumpLift = 4 * JUMP_HEIGHT * u * (1 - u);
      }
      wj = smooth(0, 0.1, t) * (1 - smooth(this.jumpDur - 0.12, this.jumpDur - 0.02, t));
      if (t >= this.jumpDur - 0.02) this.jumpT = null;
    }
    this.pos.y = this.groundY + jumpLift;

    // ---- animation
    this.idleT = (this.idleT + dt) % NOMINAL.idle;
    const s = this.speed;
    if (s > 0.03) {
      const stride = s <= SPEED.walk ? STRIDE.walk : s <= SPEED.run ? STRIDE.walk + (STRIDE.run - STRIDE.walk) * ((s - SPEED.walk) / (SPEED.run - SPEED.walk)) : STRIDE.run + (STRIDE.sprint - STRIDE.run) * clamp((s - SPEED.run) / (SPEED.sprint - SPEED.run), 0, 1);
      this.phase = (this.phase + (dt * s) / stride) % 1;
    }
    const w = { idle: 0, walk: 0, run: 0, sprint: 0 };
    if (s < 0.03) w.idle = 1;
    else if (s <= SPEED.walk) {
      const t = smooth(0.03, 0.75, s);
      w.idle = 1 - t;
      w.walk = t;
    } else if (s <= SPEED.run) {
      const t = smooth(SPEED.walk, SPEED.run, s);
      w.walk = 1 - t;
      w.run = t;
    } else {
      const t = smooth(SPEED.run, SPEED.sprint, s);
      w.run = 1 - t;
      w.sprint = t;
    }
    const setA = (name, weight, time) => {
      const a = this.act[name];
      if (!a) return;
      a.setEffectiveWeight(weight);
      a.time = time;
    };
    setA('idle', w.idle * (1 - wj), this.idleT);
    for (const k of ['walk', 'run', 'sprint']) setA(k, w[k] * (1 - wj), this.phase * NOMINAL[k]);
    setA('jump', wj, Math.min(this.jumpT ?? 0, this.jumpDur - 0.02));
    this.mixer.update(0);
    this.apply();
  }

  apply() {
    this.root.position.copy(this.pos);
    this.root.rotation.y = this.yaw;
  }

  teleport(x, z, yaw) {
    this.pos.set(x, this.ground.height(x, z), z);
    this.groundY = this.pos.y;
    if (yaw !== undefined) this.yaw = yaw;
    this.speed = 0;
    this.jumpT = null;
  }
}
