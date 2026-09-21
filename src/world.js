import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

const BASE = import.meta.env.BASE_URL;

export function makeLoaders(manager) {
  const draco = new DRACOLoader(manager);
  draco.setDecoderPath(BASE + 'draco/');
  const gltf = new GLTFLoader(manager);
  gltf.setDRACOLoader(draco);
  return gltf;
}

// ---------------------------------------------------------------------------------------------------- sky + light
export function sunDirection(meta) {
  // Blender: compass azimuth (N = +y, E = +x) of the sun, 225 deg = towards the south-west; three.js: z = -y
  const az = THREE.MathUtils.degToRad(meta.sun.azimuth_deg);
  const el = THREE.MathUtils.degToRad(meta.sun.elevation_deg);
  return new THREE.Vector3(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el)).normalize();
}

export function makeSky(sunDir) {
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    depthWrite: false,
    fog: false,
    uniforms: { sunDir: { value: sunDir.clone() } },
    vertexShader: /* glsl */ `
      varying vec3 vDir;
      void main() {
        vDir = normalize(position);
        vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        gl_Position = p.xyww;
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 sunDir;
      varying vec3 vDir;
      void main() {
        vec3 d = normalize(vDir);
        float h = d.y;
        vec3 zen = vec3(0.26, 0.42, 0.72);
        vec3 mid = vec3(0.80, 0.72, 0.74);
        vec3 hor = vec3(1.00, 0.72, 0.50);
        vec3 col = mix(hor, mid, smoothstep(0.0, 0.16, h));
        col = mix(col, zen, smoothstep(0.10, 0.80, h));
        float s = max(dot(d, normalize(sunDir)), 0.0);
        col += vec3(1.0, 0.60, 0.28) * pow(s, 6.0) * 0.50 + vec3(1.0, 0.92, 0.75) * pow(s, 260.0) * 2.5;
        col = mix(col, hor * 0.80, smoothstep(0.0, -0.20, h));
        gl_FragColor = vec4(col, 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  });
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(1, 32, 16), mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = -10;
  return mesh;
}

// ---------------------------------------------------------------------------------------------------- sea
function noiseNormalTexture() {
  const N = 256;
  const h = new Float32Array(N * N);
  const rnd = (x, y, s) => {
    const v = Math.sin((x * 127.1 + y * 311.7 + s * 74.7) * 0.0175) * 43758.5453;
    return v - Math.floor(v);
  };
  const smooth = (x, y, period, s) => {
    const fx = x / period;
    const fy = y / period;
    const ix = Math.floor(fx);
    const iy = Math.floor(fy);
    const tx = fx - ix;
    const ty = fy - iy;
    const p = N / period;
    const a = rnd(ix % p, iy % p, s);
    const b = rnd((ix + 1) % p, iy % p, s);
    const c = rnd(ix % p, (iy + 1) % p, s);
    const d = rnd((ix + 1) % p, (iy + 1) % p, s);
    const sx = tx * tx * (3 - 2 * tx);
    const sy = ty * ty * (3 - 2 * ty);
    return (a * (1 - sx) + b * sx) * (1 - sy) + (c * (1 - sx) + d * sx) * sy;
  };
  for (let y = 0; y < N; y++) {
    for (let x = 0; x < N; x++) {
      h[y * N + x] = smooth(x, y, 64, 1) * 0.55 + smooth(x, y, 32, 2) * 0.3 + smooth(x, y, 16, 3) * 0.15;
    }
  }
  const data = new Uint8Array(N * N * 4);
  for (let y = 0; y < N; y++) {
    for (let x = 0; x < N; x++) {
      const dx = h[y * N + ((x + 1) % N)] - h[y * N + ((x + N - 1) % N)];
      const dy = h[((y + 1) % N) * N + x] - h[((y + N - 1) % N) * N + x];
      const v = new THREE.Vector3(-dx * 6, -dy * 6, 1).normalize();
      const o = (y * N + x) * 4;
      data[o] = (v.x * 0.5 + 0.5) * 255;
      data[o + 1] = (v.y * 0.5 + 0.5) * 255;
      data[o + 2] = (v.z * 0.5 + 0.5) * 255;
      data[o + 3] = 255;
    }
  }
  const tex = new THREE.DataTexture(data, N, N, THREE.RGBAFormat);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(900, 900);
  tex.needsUpdate = true;
  return tex;
}

export function makeSea(level) {
  const geo = new THREE.PlaneGeometry(60000, 60000);
  geo.rotateX(-Math.PI / 2);
  const normalMap = noiseNormalTexture();
  const mat = new THREE.MeshStandardMaterial({ color: 0x2f7d86, roughness: 0.16, metalness: 0.05, normalMap, normalScale: new THREE.Vector2(0.55, 0.55) });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.position.y = level + 0.02;
  mesh.receiveShadow = false;
  mesh.userData.normalMap = normalMap;
  return mesh;
}

// ---------------------------------------------------------------------------------------------------- trees (instanced, low poly)
function colored(geo, hex, jitter = 0) {
  const c = new THREE.Color(hex);
  const n = geo.attributes.position.count;
  const arr = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const k = 1 + (Math.abs(Math.sin(i * 12.9898) * 43758.5453) % 1) * jitter;
    arr[i * 3] = c.r * k;
    arr[i * 3 + 1] = c.g * k;
    arr[i * 3 + 2] = c.b * k;
  }
  geo.setAttribute('color', new THREE.BufferAttribute(arr, 3));
  return geo;
}

function treeGeometries() {
  const part = (geo, hex, m, jitter = 0.12) => {
    let g = geo.index ? geo.toNonIndexed() : geo.clone();
    g.applyMatrix4(m);
    return colored(g, hex, jitter);
  };
  const T = (x, y, z) => new THREE.Matrix4().makeTranslation(x, y, z);
  const S = (x, y, z) => new THREE.Matrix4().makeScale(x, y, z);
  const trunk = (r0, r1, h, hex) => part(new THREE.CylinderGeometry(r0, r1, h, 6, 1), hex, T(0, h / 2, 0), 0);
  const blob = (r, hex, x, y, z, sy = 0.8) => part(new THREE.IcosahedronGeometry(r, 1), hex, T(x, y, z).multiply(S(1, sy, 1)));
  const broad = mergeGeometries([trunk(0.04, 0.07, 0.55, 0x5a4330), blob(0.34, 0x486f2a, 0, 0.78, 0), blob(0.24, 0x5b8232, 0.18, 0.62, 0.1), blob(0.22, 0x3f6626, -0.18, 0.66, -0.08)]);
  const pine = mergeGeometries([trunk(0.03, 0.055, 0.8, 0x4a3828), blob(0.26, 0x2c4d2e, 0.05, 0.86, 0, 0.5), blob(0.2, 0x35583a, -0.12, 0.7, 0.05, 0.5), blob(0.17, 0x2a4a2b, 0.1, 0.6, -0.1, 0.5)]);
  const cedar = mergeGeometries([trunk(0.03, 0.05, 0.3, 0x4a3828), part(new THREE.ConeGeometry(0.26, 0.9, 7, 1), 0x274a2b, T(0, 0.65, 0))]);
  const shrub = mergeGeometries([blob(0.5, 0x44662a, 0, 0.3, 0, 0.7), blob(0.32, 0x54782f, 0.28, 0.22, 0.1, 0.7)]);
  return [broad, pine, cedar, shrub];
}

export function makeTrees(data) {
  const group = new THREE.Group();
  const geos = treeGeometries();
  const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.95, flatShading: true });
  const byKind = [[], [], [], []];
  for (const t of data.trees) byKind[t[0]].push(t);
  const m4 = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);
  const col = new THREE.Color();
  byKind.forEach((list, k) => {
    if (!list.length) return;
    const im = new THREE.InstancedMesh(geos[k], mat, list.length);
    list.forEach((t, i) => {
      const [, x, y, z, h, w, rot] = t;
      q.setFromAxisAngle(up, rot);
      m4.compose(new THREE.Vector3(x, y, z), q, new THREE.Vector3(w * 1.15, h, w * 1.15));
      im.setMatrixAt(i, m4);
      const v = 0.82 + 0.3 * (Math.abs(Math.sin(i * 91.7 + k) * 43758.5453) % 1);
      col.setRGB(v, v * (0.96 + 0.08 * Math.sin(i)), v * 0.94);
      im.setColorAt(i, col);
    });
    im.castShadow = k !== 3;
    im.receiveShadow = true;
    im.frustumCulled = false;
    group.add(im);
  });
  return group;
}
