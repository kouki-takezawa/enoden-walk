import * as THREE from 'three';
import { U } from './fx.js';

const BOX = 26;
const HEIGHT = 14;

/** Drifting petals and leaves around the camera (Points, positions wrapped in the vertex shader; the wind gust speeds them up). */
export function makePetals(count = 170) {
  const g = new THREE.BufferGeometry();
  const pos = new Float32Array(count * 3);
  const seed = new Float32Array(count * 4);
  for (let i = 0; i < count; i++) {
    pos.set([(Math.random() - 0.5) * BOX * 2, Math.random() * HEIGHT, (Math.random() - 0.5) * BOX * 2], i * 3);
    seed.set([Math.random(), Math.random(), Math.random(), Math.random()], i * 4);
  }
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('aSeed', new THREE.BufferAttribute(seed, 4));
  const m = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: { uTime: U.uTime, uGust: U.uGust, uNight: U.uNight, uCam: { value: new THREE.Vector3() }, uPx: { value: 500 }, uOn: { value: 1 } },
    vertexShader: /* glsl */ `
      uniform float uTime, uGust, uPx; uniform vec3 uCam;
      attribute vec4 aSeed; varying vec4 vS; varying vec3 vCol;
      void main() {
        float t = uTime * (0.35 + aSeed.x * 0.3) * (1.0 + uGust * 2.0);
        vec3 p = position;
        p.y = mod(p.y - t * (0.9 + aSeed.y * 0.9), ${HEIGHT}.0);
        p.x += t * (1.6 + aSeed.z) + sin(uTime * (0.8 + aSeed.w) + aSeed.z * 20.0) * 0.7;
        p.z += cos(uTime * (0.6 + aSeed.x) + aSeed.w * 20.0) * 0.7 + t * 0.4;
        vec3 b = vec3(mod(p.x - uCam.x + ${BOX}.0, ${2 * BOX}.0) - ${BOX}.0, p.y, mod(p.z - uCam.z + ${BOX}.0, ${2 * BOX}.0) - ${BOX}.0);
        vec4 mv = viewMatrix * vec4(b.x + uCam.x, uCam.y - 4.0 + b.y, b.z + uCam.z, 1.0);
        gl_Position = projectionMatrix * mv;
        gl_PointSize = clamp(uPx * (0.05 + aSeed.y * 0.04) / max(-mv.z, 0.5), 1.5, 16.0);
        vS = aSeed;
        vCol = aSeed.w < 0.55 ? vec3(1.0, 0.78, 0.84) : (aSeed.w < 0.8 ? vec3(0.95, 0.62, 0.28) : vec3(0.72, 0.62, 0.22));
        vS.x *= 1.0 - smoothstep(14.0, ${BOX}.0, length(b.xz));
      }`,
    fragmentShader: /* glsl */ `
      uniform float uNight, uTime, uOn; varying vec4 vS; varying vec3 vCol;
      void main() {
        vec2 q = gl_PointCoord - 0.5;
        float a = vS.z * 6.2831 + uTime * (0.6 + vS.y);
        q = mat2(cos(a), -sin(a), sin(a), cos(a)) * q;
        float e = smoothstep(0.5, 0.28, length(q * vec2(1.0, 2.1)));
        gl_FragColor = vec4(vCol * (1.0 - 0.85 * uNight), e * 0.85 * uOn * (1.0 - uNight * 0.9) * clamp(vS.x * 2.0, 0.0, 1.0));
      }`,
  });
  const o = new THREE.Points(g, m);
  o.frustumCulled = false;
  o.renderOrder = 6;
  o.userData.set = (on, camera, pxScale, night) => {
    m.uniforms.uCam.value.copy(camera.position);
    m.uniforms.uPx.value = pxScale;
    m.uniforms.uOn.value = on ? 1 : 0;
    o.visible = on && night < 0.9;
  };
  return o;
}

/** A small flock of gulls circling over the sea (instanced, wing flap in the vertex shader). */
export function makeGulls(n = 9) {
  // body + two wings as 3 thin triangles (local: +x forward, +z right wing tip, y up)
  const v = new Float32Array([
    0.34, 0, 0, -0.18, 0.02, 0.06, -0.18, 0.02, -0.06, // body
    0.05, 0, 0.02, -0.16, 0, 0.62, -0.2, 0, 0.02, // right wing
    0.05, 0, -0.02, -0.2, 0, -0.02, -0.16, 0, -0.62, // left wing
  ]);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(v, 3));
  geo.computeVertexNormals();
  const mat = new THREE.MeshBasicMaterial({ color: 0xf4f1ec, side: THREE.DoubleSide });
  mat.customProgramCacheKey = () => 'gull';
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uTime = U.uTime;
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nuniform float uTime;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\ntransformed.y += sin(uTime * 7.5 + instanceMatrix[3].x * 0.9) * abs(position.z) * 0.55;');
  };
  const im = new THREE.InstancedMesh(geo, mat, n);
  im.frustumCulled = false;
  const birds = [];
  for (let i = 0; i < n; i++) {
    birds.push({
      cx: -90 + Math.random() * 180,
      cz: 28 + Math.random() * 70,
      r: 14 + Math.random() * 40,
      y: 22 + Math.random() * 26,
      w: (0.18 + Math.random() * 0.14) * (Math.random() < 0.5 ? 1 : -1),
      a: Math.random() * Math.PI * 2,
    });
  }
  const m = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const e = new THREE.Euler();
  const p = new THREE.Vector3();
  const s = new THREE.Vector3(1.4, 1.4, 1.4);
  im.userData.update = (dt, night, tint) => {
    for (let i = 0; i < n; i++) {
      const b = birds[i];
      b.a += b.w * dt;
      p.set(b.cx + Math.cos(b.a) * b.r, b.y + Math.sin(b.a * 2.3 + i) * 2.0, b.cz + Math.sin(b.a) * b.r);
      const sg = Math.sign(b.w);
      const yaw = Math.atan2(-Math.cos(b.a) * sg, -Math.sin(b.a) * sg); // local +x -> velocity of the circle
      e.set(-sg * 0.35, yaw, 0, 'YXZ'); // bank into the turn
      q.setFromEuler(e);
      m.compose(p, q, s);
      im.setMatrixAt(i, m);
    }
    im.instanceMatrix.needsUpdate = true;
    mat.color.setRGB(0.96 * tint.r, 0.95 * tint.g, 0.93 * tint.b);
    im.visible = night < 0.85;
  };
  return im;
}
