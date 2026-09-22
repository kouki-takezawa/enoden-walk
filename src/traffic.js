// Phase N4: a handful of cars driving along Route 134. The road is a straight, flat strip through the whole
// detailed part of the map here (confirmed by scanning the baked surface grid: surface===1 (asphalt) spans
// z in [5, 13.5] at every x from -90 to 80, i.e. an ~8.5 m wide two-lane road with no curve to speak of), so unlike
// the pedestrians there is no need for A* — just two fixed lanes (east/west) with cars looping along X. No lane
// changes, no collision avoidance (departures are staggered instead) and no interaction with the level crossing —
// a deliberate scope cut; see the implementation plan.
import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

const ROAD_X0 = -90;
const ROAD_X1 = 80;
const LANE_Z = { east: 7.0, west: 11.5 }; // metres, within the ~[5, 13.5] asphalt band
const SPEED = 8.5; // m/s (~30 km/h)

function carGeometry() {
  const body = new THREE.BoxGeometry(1.75, 0.62, 4.1);
  body.translate(0, 0.62, 0);
  const cabin = new THREE.BoxGeometry(1.55, 0.42, 2.1);
  cabin.translate(0, 1.04, -0.15);
  return mergeGeometries([body, cabin]);
}

function wheelGeometry() {
  const g = new THREE.CylinderGeometry(0.32, 0.32, 0.24, 10);
  g.rotateZ(Math.PI / 2);
  return g;
}

const COLORS = [0xb7c4cc, 0x8a3a3a, 0x2c3540, 0xd8d2c0, 0x3a4a3a];

/** Cheap looping road traffic: a body InstancedMesh, a wheel InstancedMesh (x4 per car, sharing one draw call) and,
 *  at night, small emissive headlight/taillight quads. No shadow casting (they are low to the ground and numerous
 *  enough that the shadow map cost is not worth it for background decoration). */
export class Traffic {
  constructor(ground, meta, count) {
    this.ground = ground;
    this.group = new THREE.Group();
    this.cars = [];
    if (count <= 0) return;

    const bodyMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.45, metalness: 0.15, vertexColors: true });
    this.body = new THREE.InstancedMesh(carGeometry(), bodyMat, count);
    this.body.frustumCulled = false;
    const wheelMat = new THREE.MeshStandardMaterial({ color: 0x161616, roughness: 0.7 });
    this.wheels = new THREE.InstancedMesh(wheelGeometry(), wheelMat, count * 4);
    this.wheels.frustumCulled = false;
    this.group.add(this.body, this.wheels);

    const lightGeo = new THREE.PlaneGeometry(0.28, 0.16);
    const headMat = new THREE.MeshBasicMaterial({ color: 0xfff2c0, transparent: true, opacity: 0, fog: false });
    const tailMat = new THREE.MeshBasicMaterial({ color: 0xff3020, transparent: true, opacity: 0, fog: false });
    this.head = new THREE.InstancedMesh(lightGeo, headMat, count);
    this.tail = new THREE.InstancedMesh(lightGeo, tailMat, count);
    this.head.frustumCulled = this.tail.frustumCulled = false;
    this.group.add(this.head, this.tail);
    this.headMat = headMat;
    this.tailMat = tailMat;

    const rnd = (s) => Math.abs(Math.sin(s * 12.9898) * 43758.5453) % 1;
    for (let i = 0; i < count; i++) {
      const east = i % 2 === 0;
      const span = ROAD_X1 - ROAD_X0;
      this.cars.push({
        east,
        x: east ? ROAD_X0 + rnd(i) * span : ROAD_X1 - rnd(i) * span,
        speed: SPEED * (0.85 + rnd(i + 30) * 0.3),
        color: new THREE.Color(COLORS[i % COLORS.length]),
      });
    }
    this._apply(0);
  }

  update(dt, night) {
    if (!this.cars.length) return;
    for (const c of this.cars) {
      c.x += (c.east ? 1 : -1) * c.speed * dt;
      const span = ROAD_X1 - ROAD_X0;
      if (c.east && c.x > ROAD_X1) c.x -= span;
      if (!c.east && c.x < ROAD_X0) c.x += span;
    }
    this._apply(night);
  }

  _apply(night) {
    const m4 = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const up = new THREE.Vector3(0, 1, 0);
    const one = new THREE.Vector3(1, 1, 1);
    this.cars.forEach((c, i) => {
      const z = c.east ? LANE_Z.east : LANE_Z.west;
      const yaw = c.east ? Math.PI / 2 : -Math.PI / 2;
      const gy = this.ground.height(c.x, z);
      const y = gy === gy ? gy : -0.3;
      q.setFromAxisAngle(up, yaw);
      m4.compose(new THREE.Vector3(c.x, y, z), q, one);
      this.body.setMatrixAt(i, m4);
      this.body.setColorAt(i, c.color);
      for (let w = 0; w < 4; w++) {
        const dx = w < 2 ? 1.4 : -1.4;
        const dz = w % 2 === 0 ? 0.78 : -0.78;
        const wp = new THREE.Vector3(dx, 0.32, dz).applyQuaternion(q).add(new THREE.Vector3(c.x, y, z));
        this.wheels.setMatrixAt(i * 4 + w, new THREE.Matrix4().compose(wp, q, one));
      }
      const front = new THREE.Vector3(0, 0.55, c.east ? 2.05 : -2.05).applyQuaternion(q).add(new THREE.Vector3(c.x, y, z));
      const back = new THREE.Vector3(0, 0.55, c.east ? -2.05 : 2.05).applyQuaternion(q).add(new THREE.Vector3(c.x, y, z));
      this.head.setMatrixAt(i, new THREE.Matrix4().compose(front, q, one));
      this.tail.setMatrixAt(i, new THREE.Matrix4().compose(back, q, one));
    });
    this.body.instanceMatrix.needsUpdate = true;
    if (this.body.instanceColor) this.body.instanceColor.needsUpdate = true;
    this.wheels.instanceMatrix.needsUpdate = true;
    this.head.instanceMatrix.needsUpdate = true;
    this.tail.instanceMatrix.needsUpdate = true;
    this.headMat.opacity = night * 0.95;
    this.tailMat.opacity = night * 0.9;
  }
}
