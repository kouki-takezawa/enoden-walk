import * as THREE from 'three';
import { glowTexture } from './lights.js';

const MAX_PRINTS = 56;
const MAX_DUST = 90;
const PRINT_LIFE = 26;
const UPY = new THREE.Vector3(0, 1, 0);
const ONE = new THREE.Vector3(1, 1, 1);

/** Footprints on sand, dust puffs from running / landing, and a soft contact shadow under the character. */
export class StepFx {
  constructor(scene, ground) {
    this.ground = ground;
    this.side = 1;
    this.jumping = false;
    this._m = new THREE.Matrix4();
    this._q = new THREE.Quaternion();
    this._p = new THREE.Vector3();

    // ---- footprints (instanced, alpha faded by age in the shader)
    const cv = document.createElement('canvas');
    cv.width = 32;
    cv.height = 64;
    const g = cv.getContext('2d');
    g.fillStyle = '#fff';
    g.beginPath();
    g.ellipse(16, 40, 9, 17, 0, 0, Math.PI * 2);
    g.ellipse(16, 12, 7, 8, 0, 0, Math.PI * 2);
    g.fill();
    const map = new THREE.CanvasTexture(cv);
    const geo = new THREE.PlaneGeometry(0.15, 0.32);
    geo.rotateX(-Math.PI / 2);
    this.fade = new THREE.InstancedBufferAttribute(new Float32Array(MAX_PRINTS), 1);
    geo.setAttribute('aFade', this.fade);
    const mat = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -3,
      polygonOffsetUnits: -3,
      uniforms: { map: { value: map } },
      vertexShader: /* glsl */ `
        attribute float aFade; varying float vF; varying vec2 vUv;
        void main() { vUv = uv; vF = aFade; gl_Position = projectionMatrix * modelViewMatrix * instanceMatrix * vec4(position, 1.0); }`,
      fragmentShader: /* glsl */ `
        uniform sampler2D map; varying float vF; varying vec2 vUv;
        void main() { float a = texture2D(map, vUv).a * vF * 0.42; gl_FragColor = vec4(0.16, 0.11, 0.06, a); }`,
    });
    this.prints = new THREE.InstancedMesh(geo, mat, MAX_PRINTS);
    this.prints.frustumCulled = false;
    this.prints.renderOrder = 2;
    this.printAge = new Float32Array(MAX_PRINTS).fill(1e9);
    this.nextPrint = 0;
    const zero = new THREE.Matrix4().makeScale(0, 0, 0);
    for (let i = 0; i < MAX_PRINTS; i++) this.prints.setMatrixAt(i, zero);
    scene.add(this.prints);

    // ---- dust puffs (CPU pool)
    const dg = new THREE.BufferGeometry();
    this.dpos = new Float32Array(MAX_DUST * 3);
    this.dvel = new Float32Array(MAX_DUST * 3);
    this.dlife = new Float32Array(MAX_DUST);
    this.dcol = new Float32Array(MAX_DUST * 3);
    this.dsize = new Float32Array(MAX_DUST);
    this.dalpha = new Float32Array(MAX_DUST);
    for (let i = 0; i < MAX_DUST; i++) this.dpos[i * 3 + 1] = -999;
    dg.setAttribute('position', new THREE.BufferAttribute(this.dpos, 3));
    dg.setAttribute('color', new THREE.BufferAttribute(this.dcol, 3));
    dg.setAttribute('aSize', new THREE.BufferAttribute(this.dsize, 1));
    dg.setAttribute('aAlpha', new THREE.BufferAttribute(this.dalpha, 1));
    this.dgeo = dg;
    const dmat = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      uniforms: { uPx: { value: 500 } },
      vertexShader: /* glsl */ `
        uniform float uPx; attribute float aSize; attribute float aAlpha; attribute vec3 color; varying float vA; varying vec3 vC;
        void main() {
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          gl_Position = projectionMatrix * mv;
          gl_PointSize = clamp(uPx * aSize / max(-mv.z, 0.4), 1.0, 90.0);
          vA = aAlpha; vC = color;
        }`,
      fragmentShader: /* glsl */ `
        varying float vA; varying vec3 vC;
        void main() { float d = length(gl_PointCoord - 0.5); gl_FragColor = vec4(vC, smoothstep(0.5, 0.05, d) * vA); }`,
    });
    this.dust = new THREE.Points(dg, dmat);
    this.dust.frustumCulled = false;
    this.dust.renderOrder = 7;
    scene.add(this.dust);
    this.nextDust = 0;

    // ---- contact shadow
    this.blob = new THREE.Mesh(
      new THREE.PlaneGeometry(1.5, 1.5).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({ map: glowTexture('0,0,0', 64), transparent: true, depthWrite: false, opacity: 0.32, fog: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }),
    );
    this.blob.renderOrder = 1;
    scene.add(this.blob);
  }

  _puff(x, y, z, surf, n, spread, up) {
    // surface colours: 1 asphalt, 2 concrete, 3 grass, 4 sand, 5 gravel
    const col = { 1: [0.5, 0.5, 0.5], 2: [0.62, 0.62, 0.6], 3: [0.42, 0.5, 0.3], 4: [0.86, 0.76, 0.56], 5: [0.6, 0.57, 0.52] }[surf] || [0.6, 0.6, 0.6];
    for (let k = 0; k < n; k++) {
      const i = this.nextDust++ % MAX_DUST;
      this.dpos.set([x + (Math.random() - 0.5) * 0.25, y + 0.05, z + (Math.random() - 0.5) * 0.25], i * 3);
      const a = Math.random() * Math.PI * 2;
      const s = Math.random() * spread;
      this.dvel.set([Math.cos(a) * s, up * (0.5 + Math.random()), Math.sin(a) * s], i * 3);
      this.dcol.set(col, i * 3);
      this.dlife[i] = 1;
      this.dsize[i] = 0.16 + Math.random() * 0.14;
    }
  }

  /** foot strike callback */
  step(surface, speed, player) {
    const y = this.ground.height(player.pos.x, player.pos.z);
    const h = y === y ? y : player.pos.y;
    this.side = -this.side;
    if (surface === 4) {
      const yaw = player.yaw;
      const px = player.pos.x - Math.cos(yaw) * 0.11 * this.side + Math.sin(yaw) * 0.08;
      const pz = player.pos.z + Math.sin(yaw) * 0.11 * this.side + Math.cos(yaw) * 0.08;
      const i = this.nextPrint++ % MAX_PRINTS;
      this._q.setFromAxisAngle(UPY, yaw);
      this.prints.setMatrixAt(i, this._m.compose(this._p.set(px, h + 0.025, pz), this._q, ONE));
      this.prints.instanceMatrix.needsUpdate = true;
      this.printAge[i] = 0;
      this._puff(player.pos.x, h, player.pos.z, 4, speed > 3 ? 3 : 1, 0.5, 0.25);
    } else if (speed > 3.2 && surface !== 3) this._puff(player.pos.x, h, player.pos.z, surface, 2, 0.6, 0.2);
  }

  /** showBlob: draw the contact shadow; night 0..1; pxScale: viewport height in px * 0.5 / tan(fov / 2) */
  update(dt, player, showBlob, night, pxScale) {
    let dirty = false;
    for (let i = 0; i < MAX_PRINTS; i++) {
      if (this.printAge[i] > PRINT_LIFE + 1) continue;
      this.printAge[i] += dt;
      const f = Math.max(0, 1 - this.printAge[i] / PRINT_LIFE);
      this.fade.array[i] = f * Math.min(1, this.printAge[i] * 8);
      dirty = true;
    }
    if (dirty) this.fade.needsUpdate = true;

    const jumping = player.jumpT !== null;
    if (this.jumping && !jumping) this._puff(player.pos.x, player.groundY, player.pos.z, this.ground.surface(player.pos.x, player.pos.z), 7, 1.0, 0.35);
    this.jumping = jumping;

    for (let i = 0; i < MAX_DUST; i++) {
      if (this.dlife[i] <= 0) {
        this.dalpha[i] = 0;
        continue;
      }
      this.dlife[i] -= dt * 1.6;
      const k = i * 3;
      this.dpos[k] += this.dvel[k] * dt;
      this.dpos[k + 1] += this.dvel[k + 1] * dt;
      this.dpos[k + 2] += this.dvel[k + 2] * dt;
      this.dvel[k] *= 0.94;
      this.dvel[k + 2] *= 0.94;
      this.dvel[k + 1] *= 0.96;
      this.dsize[i] += dt * 0.12;
      this.dalpha[i] = Math.max(0, this.dlife[i]) * 0.32 * (1 - night * 0.6);
    }
    for (const n of ['position', 'aAlpha', 'aSize', 'color']) this.dgeo.attributes[n].needsUpdate = true;
    this.dust.material.uniforms.uPx.value = pxScale;

    const lift = Math.max(0, player.pos.y - player.groundY);
    this.blob.visible = showBlob;
    if (showBlob) {
      this.blob.position.set(player.pos.x, player.groundY + 0.03, player.pos.z);
      const s = 1 / (1 + lift * 1.4);
      this.blob.scale.setScalar(s);
      this.blob.material.opacity = 0.34 * s * (1 - night * 0.5);
    }
  }
}
