import * as THREE from 'three';

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const smooth = (e0, e1, x) => {
  const t = clamp((x - e0) / (e1 - e0), 0, 1);
  return t * t * (3 - 2 * t);
};
// bones the procedural pose layer (Phase C4) drives on top of the 5 baked clips; see Player._proceduralPose
const BONE_NAMES = ['Hips', 'Spine', 'Spine1', 'Spine2', 'Neck', 'Head', 'LeftArm', 'RightArm', 'LeftFoot', 'RightFoot', 'LeftToe', 'RightToe'];
const UP_Y = new THREE.Vector3(0, 1, 0);
const RIGHT_X = new THREE.Vector3(1, 0, 0);

export const SPEED = { walk: 1.25, run: 2.9, sprint: 6.0 }; // m/s = design speeds of the baked cycles
const NOMINAL = { walk: 32 / 30, run: 22 / 30, sprint: 15 / 30, idle: 4.0 };
const STRIDE = { walk: SPEED.walk * NOMINAL.walk, run: SPEED.run * NOMINAL.run, sprint: SPEED.sprint * NOMINAL.sprint };
const JUMP_HEIGHT = 0.42;

/** The Blender-baked man: cross-faded idle / walk / run / sprint cycles driven by the ground speed, plus a jump. */
export class Player {
  constructor(gltf, ground, spawn) {
    this.ground = ground;
    this.root = new THREE.Group();
    this.model = gltf.scene;
    this.model.traverse((o) => {
      if (o.name.startsWith('Rig')) o.position.set(0, 0, 0); // the armature object carries the offset it had in the Blender scene: stand on the origin
      if (o.isMesh || o.isSkinnedMesh) {
        o.castShadow = !/^(Hair|Brows|Eyelids|Eyeball|Lips|Watch)/.test(o.name); // fine parts add triangles to the shadow pass, not to the shadow
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
    this.lastDir = new THREE.Vector2(0, -1);
    this.groundY = ground.height(spawn.x, spawn.z);
    this.pos.y = this.groundY;
    this.riding = false;
    this.onStep = null; // (surfaceId, speed) => void
    this.lastStepHalf = 0;
    this.w = { idle: 0, walk: 0, run: 0, sprint: 0 };

    this.mixer = new THREE.AnimationMixer(this.model);
    this.act = {};
    for (const clip of gltf.animations) {
      const key = clip.name.replace(/^(Male|Woody)_/, '').toLowerCase();
      const a = this.mixer.clipAction(clip);
      a.play();
      a.paused = true;
      a.enabled = true;
      a.setEffectiveWeight(0);
      this.act[key] = a;
    }
    this.jumpDur = this.act.jump ? this.act.jump.getClip().duration : 1.5;

    // ---- Phase C4: procedural pose layer, applied on top of the baked clips (see _proceduralPose).
    // Rotating a bone by a fixed "character space" axis (e.g. "pitch forward") means conjugating that axis-angle
    // into the bone's own local frame by its parent's rest orientation first: `bone.quaternion` is local-to-parent,
    // and most parent/child pairs on this rig are not co-directional (shoulder -> arm, knee -> ankle, ...), so a
    // naive local-space multiply would rotate around the wrong effective axis on those joints. See _delta().
    this.bones = {};
    const allBones = [];
    this.model.traverse((o) => {
      if (!o.isBone) return;
      allBones.push(o);
      if (BONE_NAMES.includes(o.name)) this.bones[o.name] = o;
    });
    this.proc = BONE_NAMES.every((n) => this.bones[n]); // false in tests, which build a Player from a bone-less stub gltf
    if (this.proc) {
      const restLocal = new Map(allBones.map((o) => [o, o.quaternion.clone()])); // bones are still at bind pose: mixer.update() hasn't run yet
      const restArmCache = new Map();
      const restArm = (o) => {
        if (!o || !o.isBone) return new THREE.Quaternion();
        if (!restArmCache.has(o)) restArmCache.set(o, restLocal.get(o).clone().premultiply(restArm(o.parent)));
        return restArmCache.get(o);
      };
      this.parentRestQ = {};
      this.parentRestQInv = {};
      for (const name of BONE_NAMES) {
        const q = restArm(this.bones[name].parent).clone();
        this.parentRestQ[name] = q;
        this.parentRestQInv[name] = q.clone().invert();
      }
    }
    this.yawVel = 0;
    this.breathT = 0;
    this.stopLean = 0; // 0..1, decays after a hard stop
    this.headYaw = 0;
    this.headPitch = 0;
    this._prevSpeed = 0;
    this._q = new THREE.Quaternion();
    this._v3 = new THREE.Vector3();
    this.lookTarget = null; // world-space Vector3 the head/neck should glance toward (e.g. an approaching train), or null

    this.apply();
  }

  jump() {
    if (this.jumpT === null && !this.riding) this.jumpT = 0;
  }

  /** hair is 1800 tufts of 48 triangles (86k triangles): thin it out on weaker presets (0: half, 1: three quarters, 2: all) */
  setDetail(level) {
    const keep = [(k) => k % 2 === 0, (k) => k % 4 !== 3, () => true][level] || (() => true);
    this.model.traverse((o) => {
      if (o.name !== 'Hair' || !o.geometry.index) return;
      const g = o.geometry;
      if (!g.userData.fullIndex) g.userData.fullIndex = g.index.array;
      const full = g.userData.fullIndex;
      const out = new full.constructor(full.length);
      let n = 0;
      for (let t = 0; t < full.length; t += 3) {
        if (!keep(Math.floor(full[t] / 28))) continue;
        out[n++] = full[t];
        out[n++] = full[t + 1];
        out[n++] = full[t + 2];
      }
      g.setIndex(new THREE.BufferAttribute(out.subarray(0, n), 1));
    });
  }

  /** input: {x, y, run, sprint}; camYaw: camera azimuth; gate(nx, nz, ox, oz): true when the step is closed off */
  update(dt, input, camYaw, gate) {
    if (this.riding) {
      this.speed = 0;
      this.pose(dt, 0, 0);
      return;
    }
    const mag = Math.min(1, Math.hypot(input.x, input.y));
    let target = 0;
    if (mag > 0.08) target = (input.sprint ? SPEED.sprint : input.run ? SPEED.run : SPEED.walk) * (input.run || input.sprint ? 1 : Math.max(0.55, mag));
    const acc = target > this.speed ? 7 : 10;
    this.speed += clamp(target - this.speed, -acc * dt, acc * dt);

    if (mag > 0.08) {
      const fx = -Math.sin(camYaw);
      const fz = -Math.cos(camYaw);
      const dx = fx * input.y - fz * input.x;
      const dz = fz * input.y + fx * input.x;
      const l = Math.hypot(dx, dz) || 1;
      this.lastDir.set(dx / l, dz / l);
      const ty = Math.atan2(this.lastDir.x, this.lastDir.y);
      let d = ty - this.yaw;
      d = Math.atan2(Math.sin(d), Math.cos(d));
      const dy = clamp(d, -7 * dt, 7 * dt); // was 12 rad/s: a touch slower so the C4.1 spine lean reads as a lean, not a snap
      this.yaw += dy;
      if (dt > 0) this.yawVel += (dy / dt - this.yawVel) * Math.min(1, dt * 10);
    } else if (dt > 0) this.yawVel += (0 - this.yawVel) * Math.min(1, dt * 6);

    // ---- move with wall / fence / slope / gate checks (axis-separated sliding)
    if (this.speed > 0.02) {
      const step = this.speed * dt;
      const mx = this.lastDir.x * step;
      const mz = this.lastDir.y * step;
      const g = this.ground;
      const stuck = g.isSolid(this.pos.x, this.pos.z);
      const tryMove = (nx, nz) => {
        const h1 = g.height(nx, nz);
        if (!(h1 === h1) || h1 < -2.3) return false;
        if (!stuck && g.isSolid(nx, nz)) return false;
        const dist = Math.hypot(nx - this.pos.x, nz - this.pos.z) || 1e-6;
        if ((h1 - this.groundY) / dist > 1.15 && this.jumpT === null) return false; // too steep to climb
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
    // snap up instantly (a lagged rise would sink the feet into a curb / step riser); ease down for soft footing
    if (gh === gh) this.groundY = gh > this.groundY ? gh : this.groundY + (gh - this.groundY) * Math.min(1, dt * 18);

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
    this.pose(dt, this.speed, wj);
  }

  /** cross-fade the baked cycles; also fires the footstep callback */
  pose(dt, s, wj) {
    this.idleT = (this.idleT + dt) % NOMINAL.idle;
    if (s > 0.03) {
      const stride = s <= SPEED.walk ? STRIDE.walk : s <= SPEED.run ? STRIDE.walk + (STRIDE.run - STRIDE.walk) * ((s - SPEED.walk) / (SPEED.run - SPEED.walk)) : STRIDE.run + (STRIDE.sprint - STRIDE.run) * clamp((s - SPEED.run) / (SPEED.sprint - SPEED.run), 0, 1);
      this.phase = (this.phase + (dt * s) / stride) % 1;
      // a foot lands at phase 0 (left) and 0.5 (right)
      const half = Math.floor(this.phase * 2);
      if (half !== this.lastStepHalf && this.jumpT === null) {
        this.lastStepHalf = half;
        if (this.onStep) this.onStep(this.ground.surface(this.pos.x, this.pos.z), s);
      }
    }
    const w = this.w;
    w.idle = w.walk = w.run = w.sprint = 0;
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
    this._act('idle', w.idle * (1 - wj), this.idleT);
    this._act('walk', w.walk * (1 - wj), this.phase * NOMINAL.walk);
    this._act('run', w.run * (1 - wj), this.phase * NOMINAL.run);
    this._act('sprint', w.sprint * (1 - wj), this.phase * NOMINAL.sprint);
    this._act('jump', wj, Math.min(this.jumpT ?? 0, this.jumpDur - 0.02));
    this.mixer.update(0);
    if (this.proc && wj < 0.5) this._proceduralPose(dt, s, w.sprint * (1 - wj));
    this._prevSpeed = s;
    this.apply();
  }

  /** Rotates `name` by `angle` around a fixed character-space `axis` ("up" / "right", not the bone's own local
   *  axes), on top of whatever the mixer already wrote to it this frame. See the constructor comment for why this
   *  needs to be conjugated through the bone's parent's rest orientation rather than a plain local multiply. */
  _delta(name, axis, angle) {
    if (!angle) return;
    this._q.setFromAxisAngle(axis, angle).premultiply(this.parentRestQInv[name]).multiply(this.parentRestQ[name]);
    this.bones[name].quaternion.premultiply(this._q);
  }

  /** Phase C4: small additive bone rotations layered on the baked clips (skipped mid-jump, wj >= 0.5) —
   *  turn lean, foot ground-snap, head/neck look-at, breathing sway, in-place contrapposto, stop lean, sprint arm punch. */
  _proceduralPose(dt, s, sprintW) {
    const k = Math.min(1, dt * 12); // shared smoothing rate for the sway/lean states below

    // C4.1: lean the spine into the turn (proportional to how fast the character is yawing)
    const turn = clamp(this.yawVel / 7, -1, 1);
    this._delta('Spine1', UP_Y, turn * 0.16);
    this._delta('Spine2', UP_Y, turn * 0.10);

    // C4.5: contrapposto — while nearly stationary but still turning, counter-twist the hips against the lean above
    const stillness = 1 - smooth(0, SPEED.walk * 0.6, s);
    if (stillness > 0.01) this._delta('Hips', UP_Y, -turn * 0.22 * stillness);

    // C4.6: a hard stop pitches the upper body forward slightly (inertia), then eases back out
    const decel = Math.max(0, this._prevSpeed - s) / Math.max(dt, 1e-4);
    this.stopLean += ((decel > 3.5 ? Math.min(1, decel / 12) : 0) - this.stopLean) * (decel > 3.5 ? Math.min(1, dt * 16) : Math.min(1, dt * 3));
    this._delta('Spine', RIGHT_X, this.stopLean * 0.14);

    // C4.4: idle/walking breathing sway, deeper and quicker the faster the character has been moving (out of breath)
    const effort = clamp(s / SPEED.sprint, 0, 1);
    this.breathT += dt * (1.1 + effort * 1.6);
    const breath = Math.sin(this.breathT) * (0.012 + effort * 0.02);
    this._delta('Spine', RIGHT_X, breath);
    this._delta('Spine2', RIGHT_X, breath);

    // C4.7: sprinting punches the arm swing a bit further than the baked clip alone
    if (sprintW > 0.01) {
      const swing = Math.sin(this.phase * Math.PI * 2) * sprintW * 0.22;
      this._delta('LeftArm', RIGHT_X, swing);
      this._delta('RightArm', RIGHT_X, -swing);
    }

    // C4.3: head / neck glance toward the look target (an approaching train, set from outside), capped well short
    // of anatomical limits; eases back to facing forward when no target is set
    let ty = 0;
    let tp = 0;
    if (this.lookTarget) {
      this._v3.copy(this.lookTarget).sub(this.pos);
      const dist = Math.hypot(this._v3.x, this._v3.z) || 1;
      let d = Math.atan2(this._v3.x, this._v3.z) - this.yaw;
      d = Math.atan2(Math.sin(d), Math.cos(d));
      ty = clamp(d, -0.9, 0.9);
      tp = clamp(Math.atan2(this._v3.y, dist), -0.5, 0.5);
    }
    this.headYaw += (ty - this.headYaw) * k;
    this.headPitch += (tp - this.headPitch) * k;
    this._delta('Neck', UP_Y, this.headYaw * 0.6);
    this._delta('Neck', RIGHT_X, -this.headPitch * 0.6);
    this._delta('Head', UP_Y, this.headYaw * 0.4);
    this._delta('Head', RIGHT_X, -this.headPitch * 0.4);

    // C4.2: foot ground-snap — nudge the ankle to close small height gaps the baked cycle leaves on slopes/curbs.
    // Needs this frame's world matrices (mixer.update + the tweaks above don't touch them; the renderer's own
    // updateMatrixWorld only runs later, after this), so refresh the model's subtree before reading foot positions.
    this.model.updateMatrixWorld(true);
    this._footSnap('LeftFoot');
    this._footSnap('RightFoot');
  }

  _footSnap(name) {
    const bone = this.bones[name];
    bone.getWorldPosition(this._v3);
    const gy = this.ground.height(this._v3.x, this._v3.z);
    if (gy !== gy) return; // off the height grid
    const dy = clamp(gy - this._v3.y, -0.12, 0.12);
    if (Math.abs(dy) < 0.005) return;
    this._delta(name, RIGHT_X, clamp(dy * 2.2, -0.35, 0.35));
  }

  _act(name, weight, time) {
    const a = this.act[name];
    if (!a) return;
    a.setEffectiveWeight(weight);
    a.time = time;
  }

  apply() {
    this.root.position.copy(this.pos);
    this.root.rotation.y = this.yaw;
  }

  teleport(x, z, yaw) {
    const h = this.ground.height(x, z);
    this.pos.set(x, h === h ? h : this.pos.y, z);
    this.groundY = this.pos.y;
    if (yaw !== undefined) this.yaw = yaw;
    this.speed = 0;
    this.jumpT = null;
    this.riding = false;
  }
}
