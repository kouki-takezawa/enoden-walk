import * as THREE from 'three';

const TRAIN_LEN = 26.3;      // two-car set, cab end at +x of the model (x = 0.6 at the origin)
const CAB_X = 0.6;
const SPEED = 11;             // m/s (~40 km/h)
const START = 150;

/** Runs the Enoden set back and forth along the track and drives the level crossing (alarm lamps + barrier arms). */
export class Train {
  constructor(trainGltf, world, meta) {
    this.group = new THREE.Group();
    this.group.add(trainGltf.scene);
    trainGltf.scene.traverse((o) => {
      if (o.isMesh) {
        o.castShadow = true;
        o.receiveShadow = true;
        o.frustumCulled = false;
      }
    });
    this.dir = 1;
    this.front = -START;
    this.state = 'wait';
    this.timer = 6;
    this.alarm = false;
    this.armT = 0;              // 0 = raised, 1 = lowered
    this.flip = false;
    this.flipT = 0;
    this.meta = meta;

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
    this.place();
    this.setArms(0);
    this.setLamps(false, 0);
  }

  place() {
    if (this.dir > 0) {
      this.group.rotation.y = 0;
      this.group.position.set(this.front - CAB_X, 0, 0);
    } else {
      this.group.rotation.y = Math.PI;
      this.group.position.set(this.front + CAB_X, 0, 0);
    }
    this.group.visible = this.state === 'run';
  }

  /** x range [min, max] covered by the set */
  span() {
    return this.dir > 0 ? [this.front - TRAIN_LEN, this.front] : [this.front, this.front + TRAIN_LEN];
  }

  hits(p) {
    if (this.state !== 'run') return false;
    const [a, b] = this.span();
    return p.x > a - 0.4 && p.x < b + 0.4 && Math.abs(p.z) < 1.6 && p.y < 4.2;
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

  update(dt) {
    if (this.state === 'wait') {
      this.timer -= dt;
      if (this.timer <= 0) {
        this.dir = -this.dir;
        this.front = this.dir > 0 ? -START : START;
        this.state = 'run';
      }
    } else {
      this.front += this.dir * SPEED * dt;
      if ((this.dir > 0 && this.front - TRAIN_LEN > START) || (this.dir < 0 && this.front + TRAIN_LEN < -START)) {
        this.state = 'wait';
        this.timer = 22 + Math.random() * 12;
      }
    }
    // alarm: 7 s before the cab reaches the crossing until the tail has cleared it
    const [a, b] = this.span();
    const lead = SPEED * 7;
    this.alarm = this.state === 'run' && a < 10 + 0 && b > -10 && (this.dir > 0 ? this.front > -lead : this.front < lead);
    this.armT += ((this.alarm ? 1 : 0) - this.armT) * Math.min(1, dt * 1.3);
    this.setArms(this.armT);
    this.flipT += dt;
    if (this.flipT > 0.5) {
      this.flipT = 0;
      this.flip = !this.flip;
    }
    this.setLamps(this.alarm, this.flip);
    this.place();
  }
}
