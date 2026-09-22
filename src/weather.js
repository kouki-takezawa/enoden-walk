import * as THREE from 'three';
import { U } from './fx.js';

const COUNT = 4500;
const BOX = 34; // half width of the rain volume around the camera
const HEIGHT = 22;

/** Optional rain: thin streaks that fall inside a box following the camera (positions are wrapped in the vertex shader). */
export function makeRain() {
  const g = new THREE.BufferGeometry();
  const pos = new Float32Array(COUNT * 2 * 3);
  const end = new Float32Array(COUNT * 2);
  for (let i = 0; i < COUNT; i++) {
    const x = (Math.random() - 0.5) * BOX * 2;
    const y = Math.random() * HEIGHT;
    const z = (Math.random() - 0.5) * BOX * 2;
    for (let k = 0; k < 2; k++) {
      pos.set([x, y, z], (i * 2 + k) * 3);
      end[i * 2 + k] = k;
    }
  }
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('aEnd', new THREE.BufferAttribute(end, 1));
  const m = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: { uTime: U.uTime, uCam: { value: new THREE.Vector3() }, uAlpha: { value: 0 }, uTint: { value: new THREE.Color(0xbcc8d4) } },
    vertexShader: /* glsl */ `
      uniform float uTime; uniform vec3 uCam;
      attribute float aEnd; varying float vA;
      void main() {
        vec3 p = position;
        float speed = 14.0 + fract(p.x * 12.9898 + p.z * 4.1414) * 4.0;
        p.y = mod(p.y - uTime * speed, ${HEIGHT}.0);
        p.x += p.y * 0.08;
        vec3 base = vec3(mod(p.x - uCam.x + ${BOX}.0, ${2 * BOX}.0) - ${BOX}.0, p.y, mod(p.z - uCam.z + ${BOX}.0, ${2 * BOX}.0) - ${BOX}.0);
        vec3 w = vec3(base.x + uCam.x, base.y + uCam.y - 6.0, base.z + uCam.z);
        w.y += aEnd * 0.55; w.x += aEnd * 0.05;
        vA = (1.0 - aEnd * 0.6) * (1.0 - smoothstep(18.0, ${BOX}.0, length(base.xz)));
        gl_Position = projectionMatrix * viewMatrix * vec4(w, 1.0);
      }`,
    fragmentShader: /* glsl */ `
      uniform float uAlpha; uniform vec3 uTint; varying float vA;
      void main() { gl_FragColor = vec4(uTint, vA * uAlpha * 0.6); }`,
  });
  const rain = new THREE.LineSegments(g, m);
  rain.frustumCulled = false;
  rain.visible = false;
  rain.renderOrder = 5;
  rain.userData.set = (on, camera, night) => {
    m.uniforms.uCam.value.copy(camera.position);
    const target = on ? 1 : 0;
    m.uniforms.uAlpha.value += (target - m.uniforms.uAlpha.value) * 0.05;
    m.uniforms.uTint.value.setRGB(0.74 - night * 0.4, 0.78 - night * 0.42, 0.83 - night * 0.38);
    rain.visible = m.uniforms.uAlpha.value > 0.01;
    return m.uniforms.uAlpha.value;
  };
  return rain;
}
