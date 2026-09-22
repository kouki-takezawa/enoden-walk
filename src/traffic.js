// Phase N4 (JS primitives) -> B2 (real Blender geometry, see blender/cars.py): a handful of cars driving along
// Route 134. The road is a straight, flat strip through the whole detailed part of the map here (confirmed by
// scanning the baked surface grid: surface===1 (asphalt) spans z in [5, 13.5] at every x from -90 to 80, i.e. an
// ~8.5 m wide two-lane road with no curve to speak of), so unlike the pedestrians there is no need for A* — just
// two fixed lanes (east/west) with cars looping along X. No lane changes, no collision avoidance (departures are
// staggered instead) and no interaction with the level crossing — a deliberate scope cut; see the implementation plan.
//
// cars.glb's body is modelled nose-first along local +X with no extra yaw needed for an eastbound car (glTF's
// Y-up export keeps Blender X as glTF/three.js X) — see blender/cars.py's module docstring for the coordinate
// convention shared with the wheel object (axle along local Z, so a wheel just spins around its own Z to roll).
import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

const ROAD_X0 = -90;
const ROAD_X1 = 80;
const LANE_Z = { east: 7.0, west: 11.5 }; // metres, within the ~[5, 13.5] asphalt band
const SPEED = 8.5; // m/s (~30 km/h)
const WHEEL_R = 0.33;
const FRONT_AXLE_X = 1.35;
const REAR_AXLE_X = -1.35;
const TRACK_Z = 0.75;
const WHEEL_Y = WHEEL_R;

// per-instance tint multiplied onto the baked-neutral car paint texture (same palette the old flat-colour boxes used)
const TINTS = [0xb7c4cc, 0x8a3a3a, 0x2c3540, 0xd8d2c0, 0x3a4a3a];

/** Blender's glTF exporter splits a multi-material mesh into one primitive per material; GLTFLoader in turn loads
 *  that as a Group of single-material child Meshes rather than one Mesh with a material array. Recombine them into
 *  a single geometry (with per-material .groups) + material array, suitable for one multi-material InstancedMesh. */
function mergeNamedGroup(node) {
  const meshes = node.isMesh ? [node] : node.children.filter((c) => c.isMesh);
  const geometry = meshes.length > 1 ? mergeGeometries(meshes.map((m) => m.geometry), true) : meshes[0].geometry.clone();
  const materials = meshes.map((m) => m.material.clone());
  return { geometry, materials };
}

/** Cheap looping road traffic: a body InstancedMesh (the real Blender-modelled car, baked paint texture tinted per
 *  instance) and a wheel InstancedMesh (x4 per car, sharing one draw call, rolling with travel speed). No shadow
 *  casting (they are low to the ground and numerous enough that the shadow map cost is not worth it for background
 *  decoration). Headlight/taillight are baked-in emissive lenses on the body mesh, toggled via emissiveIntensity
 *  (shared across all instances, like the old per-material opacity toggle was). */
export class Traffic {
  constructor(carsGltf, ground, meta, count) {
    this.ground = ground;
    this.group = new THREE.Group();
    this.cars = [];
    if (count <= 0) return;

    const { geometry: bodyGeo, materials: bodyMats } = mergeNamedGroup(carsGltf.scene.getObjectByName('CarBody'));
    const { geometry: wheelGeo, materials: wheelMats } = mergeNamedGroup(carsGltf.scene.getObjectByName('CarWheel'));

    const paintMat = bodyMats.find((m) => m.name === 'MAT_CarPaint');
    if (paintMat) {
      paintMat.vertexColors = true;
      paintMat.needsUpdate = true;
    }
    this.headMat = bodyMats.find((m) => m.name === 'MAT_CarHead');
    this.tailMat = bodyMats.find((m) => m.name === 'MAT_CarTail');
    this.headBase = this.headMat ? this.headMat.emissiveIntensity : 0;
    this.tailBase = this.tailMat ? this.tailMat.emissiveIntensity : 0;
    if (this.headMat) this.headMat.emissiveIntensity = 0;
    if (this.tailMat) this.tailMat.emissiveIntensity = 0;

    this.body = new THREE.InstancedMesh(bodyGeo, bodyMats, count);
    this.body.frustumCulled = false;
    this.wheels = new THREE.InstancedMesh(wheelGeo, wheelMats, count * 4);
    this.wheels.frustumCulled = false;
    this.group.add(this.body, this.wheels);

    const rnd = (s) => Math.abs(Math.sin(s * 12.9898) * 43758.5453) % 1;
    for (let i = 0; i < count; i++) {
      const east = i % 2 === 0;
      const span = ROAD_X1 - ROAD_X0;
      this.cars.push({
        east,
        x: east ? ROAD_X0 + rnd(i) * span : ROAD_X1 - rnd(i) * span,
        speed: SPEED * (0.85 + rnd(i + 30) * 0.3),
        color: new THREE.Color(TINTS[i % TINTS.length]),
        roll: rnd(i + 60) * Math.PI * 2,
      });
    }
    this._apply(0);
  }

  update(dt, night) {
    if (!this.cars.length) return;
    for (const c of this.cars) {
      const step = (c.east ? 1 : -1) * c.speed * dt;
      c.x += step;
      c.roll -= step / WHEEL_R;
      const span = ROAD_X1 - ROAD_X0;
      if (c.east && c.x > ROAD_X1) c.x -= span;
      if (!c.east && c.x < ROAD_X0) c.x += span;
    }
    this._apply(night);
  }

  _apply(night) {
    const m4 = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const qRoll = new THREE.Quaternion();
    const qWheel = new THREE.Quaternion();
    const up = new THREE.Vector3(0, 1, 0);
    const zAxis = new THREE.Vector3(0, 0, 1);
    const one = new THREE.Vector3(1, 1, 1);
    this.cars.forEach((c, i) => {
      const z = c.east ? LANE_Z.east : LANE_Z.west;
      const yaw = c.east ? 0 : Math.PI;
      const gy = this.ground.height(c.x, z);
      const y = gy === gy ? gy : -0.3;
      const base = new THREE.Vector3(c.x, y, z);
      q.setFromAxisAngle(up, yaw);
      m4.compose(base, q, one);
      this.body.setMatrixAt(i, m4);
      this.body.setColorAt(i, c.color);
      qRoll.setFromAxisAngle(zAxis, c.roll);
      qWheel.copy(q).multiply(qRoll);
      for (let w = 0; w < 4; w++) {
        const dx = w < 2 ? FRONT_AXLE_X : REAR_AXLE_X;
        const dz = w % 2 === 0 ? TRACK_Z : -TRACK_Z;
        const wp = new THREE.Vector3(dx, WHEEL_Y, dz).applyQuaternion(q).add(base);
        this.wheels.setMatrixAt(i * 4 + w, new THREE.Matrix4().compose(wp, qWheel, one));
      }
    });
    this.body.instanceMatrix.needsUpdate = true;
    if (this.body.instanceColor) this.body.instanceColor.needsUpdate = true;
    this.wheels.instanceMatrix.needsUpdate = true;
    if (this.headMat) this.headMat.emissiveIntensity = this.headBase * night;
    if (this.tailMat) this.tailMat.emissiveIntensity = this.tailBase * night;
  }
}
