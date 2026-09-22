import * as THREE from 'three';
import { makeAlarmGlow, makeBeam, makeSparks } from './lights.js';
import { patchTrainLivery } from './fx.js';
import { makeTorsoGeometry } from './people.js';

const LEN = 26.3; // two-car set, cab end at +x of the model (x = 0.6 at the origin)
const CAB_X = 0.6;
const CRUISE = 11; // m/s (~40 km/h)
const ACCEL = 0.9;
const DECEL = 1.1;
const START = 160;
const END = 205; // riders turn around here
const DWELL = 20; // long enough to walk up the platform and board
const WHEEL_R = 0.43; // RESEARCH["train_1000"].wheel_dia / 2 (enoden_kamakurakokomae.py) — for speed-matched wheel spin

/** Runs the Enoden set along the track with a stop at the platform, drives the level crossing (alarm lamps + barrier arms) and can carry the player. */
export class Train {
  constructor(trainGltf, world, meta) {
    this.meta = meta;
    this.group = new THREE.Group();
    this.inner = new THREE.Group();
    this.group.add(this.inner);
    this.inner.add(trainGltf.scene);
    this.mats = new Set();
    trainGltf.scene.traverse((o) => {
      if (o.isMesh) {
        o.castShadow = true;
        o.receiveShadow = true;
        o.frustumCulled = false;
        const ms = Array.isArray(o.material) ? o.material : [o.material];
        for (const m of ms) {
          this.mats.add(m);
          if (m.name && m.name.includes('Glass')) {
            this.glass = m;
            this.glassMesh = o;
          }
        }
      }
    });
    this.wheels = trainGltf.scene.getObjectByName('Enoden_1000_Wheels'); // separate node (enoden_kamakurakokomae.py: car_mb) spun in update()
    this.dir = -1; // the first run is eastbound (dir flips before each run)
    this.front = -START;
    this.state = 'wait';
    this.timer = 7;
    this.speed = 0;
    this.stopping = false;
    this.alarm = false;
    this.armT = 0;
    this.flip = false;
    this.flipT = 0;
    this.time = 0;
    this.rider = false;
    this.pf = meta.platform;
    this._span = [0, 0];

    this.arms = [];
    for (const a of meta.crossing.arms) {
      const node = world.getObjectByName(THREE.PropertyBinding.sanitizeNodeName(a.name));
      if (node) this.arms.push({ node, down: new THREE.Quaternion(...a.down), up: new THREE.Quaternion(...a.up) });
    }
    this.lampOn = world.getObjectByName('Alarm_Lamps_ON');
    this.lampOff = world.getObjectByName('Alarm_Lamps_OFF');
    if (this.lampOn && this.lampOff) {
      const one = (m) => (Array.isArray(m) ? m[0] : m).clone();
      this.bright = one(this.lampOn.material);
      this.dark = one(this.lampOff.material);
      this.bright.emissiveIntensity = 1.3;
    }

    // headlight (the +x end of the model is always the leading cab) + interior passengers
    this.head = new THREE.SpotLight(0xffe2b0, 0, 90, 0.5, 0.5, 1.2);
    this.head.position.set(CAB_X + 0.3, 1.5, 0);
    this.head.target.position.set(CAB_X + 30, 0.8, 0);
    this.inner.add(this.head, this.head.target);
    this.passengers = this._passengers();
    this.inner.add(this.passengers);
    this.beam = makeBeam();
    this.beam.position.set(CAB_X + 0.3, 1.5, 0);
    this.inner.add(this.beam);
    this.sparks = makeSparks(trainGltf.scene);
    if (this.sparks) this.inner.add(this.sparks.points);
    this.alarmGlow = makeAlarmGlow(world);
    world.add(this.alarmGlow.root);
    this.place();
    this.setArms(0);
    this.setLamps(false, 0);
  }

  /** A bit more than a "head + torso box" silhouette (shoulders read as shoulders, the head keeps a fixed skin
   *  tone instead of taking on the clothing colour) while staying cheap enough for a couple dozen instances.
   *  Shares its geometry builder with the pedestrian crowd (people.js) — passengers are seated, so no legs. */
  _passengers() {
    const geo = makeTorsoGeometry();
    const mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.9, vertexColors: true });
    const slots = [];
    for (const cx of [CAB_X - 6.55, CAB_X - 20.55]) for (let k = -4; k <= 4; k++) for (const z of [-0.78, 0.78]) slots.push([cx + k * 1.28, z]);
    const im = new THREE.InstancedMesh(geo, mat, slots.length);
    const m = new THREE.Matrix4();
    const c = new THREE.Color();
    let n = 0;
    slots.forEach(([x, z], i) => {
      const r = Math.abs(Math.sin(i * 12.9898) * 43758.5453) % 1;
      if (r > 0.42) return;
      m.makeRotationY(z > 0 ? Math.PI : 0).setPosition(x, 1.07 + 0.36, z);
      im.setMatrixAt(n, m);
      c.setHSL(0.55 + 0.15 * r, 0.25, 0.14 + 0.2 * r);
      im.setColorAt(n, c);
      n++;
    });
    im.count = n;
    im.frustumCulled = false;
    return im;
  }

  /** liveried-paint weathering (see fx.js patchTrainLivery); call again on a quality-preset switch. The interior
   *  seats/floor (car_mb() in enoden_kamakurakokomae.py) reuse the body's own green/dark materials, so they're
   *  already covered by the branches below. */
  style(preset) {
    for (const m of this.mats) {
      if (m.name === 'W_MAT_Enoden_Green') patchTrainLivery(m, preset.detail, true);
      else if (m.name === 'W_MAT_Enoden_Cream' || m.name === 'W_MAT_Train_Roof' || m.name === 'W_MAT_Train_Dark') patchTrainLivery(m, preset.detail, false);
    }
  }

  place() {
    if (this.dir > 0) {
      this.group.rotation.y = 0;
      this.group.position.set(this.front - CAB_X, 0, 0);
    } else {
      this.group.rotation.y = Math.PI;
      this.group.position.set(this.front + CAB_X, 0, 0);
    }
    this.group.visible = this.state !== 'wait';
  }

  /** x range [min, max] covered by the set */
  span() {
    const s = this._span;
    if (this.dir > 0) {
      s[0] = this.front - LEN;
      s[1] = this.front;
    } else {
      s[0] = this.front;
      s[1] = this.front + LEN;
    }
    return s; // shared array: read it right away
  }

  stopFront() {
    return this.dir > 0 ? this.pf.x1 - 2 : this.pf.x0 + 2;
  }

  hits(p) {
    if (this.state === 'wait' || this.rider) return false;
    if (p.z < -1.4 && p.y > 0.3) return false; // standing on the platform deck (the solid cells keep walkers out of z > -1.5; its edge is at -1.35)
    const [a, b] = this.span();
    return p.x > a - 0.4 && p.x < b + 0.4 && Math.abs(p.z) < 1.6 && p.y < 4.2;
  }

  /** seen from inside the walls are dropped (single sided) so the scenery is visible all around; outside they are double sided again */
  setFirstPerson(on) {
    for (const m of this.mats) {
      m.side = on ? THREE.FrontSide : THREE.DoubleSide;
      m.needsUpdate = true;
    }
    if (this.glassMesh) this.glassMesh.visible = !on; // the lit window panes would veil the view from the seat
  }

  /** the passenger's seat in world space */
  seat(out) {
    return out.set(this.front - this.dir * 9.0, 1.07, 0);
  }

  /** can a player at p (world) board now? */
  canBoard(p) {
    if (this.state !== 'dwell' || this.rider) return false;
    const [a, b] = this.span();
    return p.x > a - 1 && p.x < b + 1 && p.z < -1.0 && p.z > -this.pf.y1 - 2.5;
  }

  info() {
    if (this.state === 'wait') return { state: 'wait', dir: -this.dir, s: Math.max(0, Math.ceil(this.timer)) };
    if (this.state === 'dwell') return { state: 'dwell', dir: this.dir, s: Math.max(0, Math.ceil(this.timer)) };
    return { state: this.stopping ? 'arriving' : 'passing', dir: this.dir, s: 0 };
  }

  setArms(t) {
    for (const a of this.arms) a.node.quaternion.copy(a.up).slerp(a.down, t);
  }

  setLamps(active, phase) {
    if (!this.lampOn || !this.lampOff) return;
    if (!active) {
      this.lampOn.material = this.dark;
      this.lampOff.material = this.dark;
    } else if (phase) {
      this.lampOn.material = this.bright;
      this.lampOff.material = this.dark;
    } else {
      this.lampOn.material = this.dark;
      this.lampOff.material = this.bright;
    }
  }

  _computeAlarm() {
    if (this.state === 'wait') return false;
    const [a, b] = this.span();
    if (this.dir > 0) {
      const leaving = !this.stopping || (this.state === 'dwell' && this.timer < 3.5);
      return leaving && a < 9 && b > -60;
    }
    // westbound: from ~7 s before the cab reaches the crossing until the tail has cleared it
    return this.state !== 'dwell' && a < CRUISE * 7 && b > -9 && this.stopping;
  }

  update(dt, night = 0, glow = night) {
    this.time += dt;
    if (this.state === 'wait') {
      this.timer -= dt;
      if (this.timer <= 0) {
        this.dir = -this.dir;
        this.front = this.dir > 0 ? -START : START;
        this.state = 'move';
        this.stopping = true;
        this.speed = CRUISE;
      }
    } else if (this.state === 'dwell') {
      this.speed = 0;
      this.timer -= dt;
      if (this.timer <= 0) {
        this.state = 'move';
        this.stopping = false;
      }
    } else {
      if (this.stopping) {
        const dist = (this.stopFront() - this.front) * this.dir;
        const lim = Math.sqrt(2 * DECEL * Math.max(dist, 0)) + 0.4;
        this.speed = Math.min(this.speed + ACCEL * dt, CRUISE, lim);
        if (dist <= 0.06 || (dist < 0.8 && this.speed < 0.45)) {
          this.front = this.stopFront();
          this.speed = 0;
          this.state = 'dwell';
          this.timer = DWELL;
        }
      } else {
        this.speed = Math.min(this.speed + ACCEL * dt, CRUISE);
      }
      this.front += this.dir * this.speed * dt;
      const [a, b] = this.span();
      if (!this.stopping && ((this.dir > 0 && a > (this.rider ? END : START)) || (this.dir < 0 && b < -(this.rider ? END : START)))) {
        if (this.rider) {
          // turn around with the passenger on board and come back to the platform
          this.front = this.dir > 0 ? a : b;
          this.dir = -this.dir;
          this.stopping = true;
          this.speed = 0;
        } else {
          this.state = 'wait';
          this.timer = 20 + Math.random() * 12;
          this.speed = 0;
        }
      }
    }
    this.alarm = this._computeAlarm();
    this.armT += ((this.alarm ? 1 : 0) - this.armT) * Math.min(1, dt * 1.3);
    this.setArms(this.armT);
    this.flipT += dt;
    if (this.flipT > 0.5) {
      this.flipT = 0;
      this.flip = !this.flip;
    }
    this.setLamps(this.alarm, this.flip);
    this.alarmGlow.update(this.alarm, this.flip, night);

    // running sway + night lights
    const v = this.speed / CRUISE;
    this.inner.rotation.z = Math.sin(this.time * 6.1 + this.front * 0.8) * 0.0035 * v;
    this.inner.rotation.x = Math.sin(this.time * 4.3) * 0.0022 * v;
    this.inner.position.y = Math.abs(Math.sin(this.front * 0.52)) * 0.006 * v;
    this.head.intensity = night * 260 * (this.state === 'wait' ? 0 : 1);
    this.beam.material.uniforms.uI.value = Math.min(1, glow * 3) * (this.state === 'wait' ? 0 : 1);
    this.sparks?.update(dt, night, this.speed);
    if (this.glass) {
      this.glass.emissive.setRGB(1.0, 0.82, 0.55);
      this.glass.emissiveIntensity = night * 0.55;
    }
    // wheel discs are a separate exported node (car_mb() in enoden_kamakurakokomae.py) spun about their own local
    // Z (the axle direction after Blender's Y-up glTF export) — see blender/cars.py's module docstring for the
    // same convention on the road-traffic wheels.
    if (this.wheels) this.wheels.rotation.z += (this.dir * this.speed * dt) / WHEEL_R;
    this.place();
  }
}
