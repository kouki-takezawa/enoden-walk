import * as THREE from 'three';
import { mergeGeometries, mergeVertices } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { U } from './fx.js';

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

const T = (x, y, z) => new THREE.Matrix4().makeTranslation(x, y, z);
const S = (x, y, z) => new THREE.Matrix4().makeScale(x, y, z);

/** smooth-shaded low-poly part (welded vertices, normals recomputed after the transform) */
function part(geo, hex, m, jitter = 0.12) {
  let g = geo.clone();
  g.deleteAttribute('uv');
  g.deleteAttribute('normal');
  g = mergeVertices(g);
  g.applyMatrix4(m);
  g.computeVertexNormals();
  return colored(g, hex, jitter);
}
const trunk = (r0, r1, h, hex) => part(new THREE.CylinderGeometry(r0, r1, h, 6, 1), hex, T(0, h / 2, 0), 0.05);
const blob = (r, hex, x, y, z, sy = 0.8) => part(new THREE.IcosahedronGeometry(r, 1), hex, T(x, y, z).multiply(S(1, sy, 1)));

/** leaf texture: several green leaves with alpha, drawn once on a canvas */
function leafTexture() {
  const cv = document.createElement('canvas');
  cv.width = cv.height = 128;
  const g = cv.getContext('2d');
  g.clearRect(0, 0, 128, 128);
  const leaf = (x, y, r, a, l, col) => {
    g.save();
    g.translate(x, y);
    g.rotate(a);
    g.fillStyle = col;
    g.beginPath();
    g.ellipse(0, 0, l, r, 0, 0, Math.PI * 2);
    g.fill();
    g.strokeStyle = 'rgba(30,60,20,0.5)';
    g.lineWidth = 1;
    g.beginPath();
    g.moveTo(-l, 0);
    g.lineTo(l, 0);
    g.stroke();
    g.restore();
  };
  const cols = ['#ffffff', '#f0f0f0', '#e2e2e2'];
  for (let i = 0; i < 22; i++) {
    const a = Math.sin(i * 12.9898) * 43758.5453;
    const b = Math.sin(i * 78.233) * 12345.6789;
    leaf(20 + (Math.abs(a) % 1) * 88, 20 + (Math.abs(b) % 1) * 88, 7 + (i % 3) * 2, ((Math.abs(a * 3.1) % 1) - 0.5) * 3.1, 16 + (i % 4) * 2, cols[i % 3]);
  }
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/** N leaf-card quads scattered over ellipsoids [cx, cy, cz, rx, ry, rz]; each faces outward with a random roll */
function cards(lumps, n, size, hex, seed) {
  const pos = [];
  const uv = [];
  const col = [];
  const idx = [];
  let s = seed;
  const rnd = () => {
    s = (s * 16807) % 2147483647;
    return s / 2147483647;
  };
  const base = new THREE.Color(hex);
  for (let i = 0; i < n; i++) {
    const L = lumps[i % lumps.length];
    const u = rnd() * 2 - 1;
    const phi = rnd() * Math.PI * 2;
    const r = Math.sqrt(1 - u * u);
    const nrm = new THREE.Vector3(r * Math.cos(phi) / L[3], u / L[4], r * Math.sin(phi) / L[5]).normalize();
    const p = new THREE.Vector3(L[0] + (r * Math.cos(phi)) * L[3], L[1] + u * L[4], L[2] + r * Math.sin(phi) * L[5]);
    const up = Math.abs(nrm.y) > 0.9 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 1, 0);
    const t = new THREE.Vector3().crossVectors(up, nrm).normalize();
    const b = new THREE.Vector3().crossVectors(nrm, t);
    const roll = rnd() * Math.PI * 2;
    const t2 = t.clone().multiplyScalar(Math.cos(roll)).addScaledVector(b, Math.sin(roll));
    const b2 = new THREE.Vector3().crossVectors(nrm, t2);
    const sz = size * (0.7 + rnd() * 0.6);
    const shade = 0.75 + 0.5 * rnd() + 0.25 * (u * 0.5 + 0.5);
    const v0 = pos.length / 3;
    for (const [a1, b1, uu, vv] of [[-1, -1, 0, 0], [1, -1, 1, 0], [1, 1, 1, 1], [-1, 1, 0, 1]]) {
      const q = p.clone().addScaledVector(t2, a1 * sz).addScaledVector(b2, b1 * sz).addScaledVector(nrm, 0.01);
      pos.push(q.x, q.y, q.z);
      uv.push(uu, vv);
      col.push(base.r * shade, base.g * shade, base.b * shade);
    }
    idx.push(v0, v0 + 1, v0 + 2, v0, v0 + 2, v0 + 3);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

function treeGeometries(useCards) {
  const broad = mergeGeometries([trunk(0.04, 0.07, 0.55, 0x5a4330), blob(0.34, 0x486f2a, 0, 0.78, 0), blob(0.24, 0x5b8232, 0.18, 0.62, 0.1), blob(0.22, 0x3f6626, -0.18, 0.66, -0.08)]);
  const pine = mergeGeometries([trunk(0.03, 0.055, 0.8, 0x4a3828), blob(0.26, 0x2c4d2e, 0.05, 0.86, 0, 0.5), blob(0.2, 0x35583a, -0.12, 0.7, 0.05, 0.5), blob(0.17, 0x2a4a2b, 0.1, 0.6, -0.1, 0.5)]);
  const cedar = mergeGeometries([trunk(0.03, 0.05, 0.3, 0x4a3828), part(new THREE.ConeGeometry(0.26, 0.9, 7, 1), 0x274a2b, T(0, 0.65, 0))]);
  const shrub = mergeGeometries([blob(0.5, 0x44662a, 0, 0.3, 0, 0.7), blob(0.32, 0x54782f, 0.28, 0.22, 0.1, 0.7)]);
  const out = [{ core: broad }, { core: pine }, { core: cedar }, { core: shrub }];
  if (useCards) {
    out[0].cards = cards([[0, 0.78, 0, 0.36, 0.30, 0.36], [0.18, 0.62, 0.1, 0.26, 0.2, 0.26], [-0.18, 0.66, -0.08, 0.24, 0.2, 0.24]], 90, 0.095, 0x6f9a3c, 11);
    out[1].cards = cards([[0.05, 0.86, 0, 0.28, 0.14, 0.28], [-0.12, 0.7, 0.05, 0.22, 0.11, 0.22], [0.1, 0.6, -0.1, 0.19, 0.1, 0.19]], 70, 0.085, 0x3d6a40, 21);
    out[3].cards = cards([[0, 0.3, 0, 0.5, 0.35, 0.5], [0.28, 0.22, 0.1, 0.32, 0.22, 0.32]], 46, 0.11, 0x5f8a34, 31);
  }
  return out;
}

const WIND = /* glsl */ `
  float sw = sin(uTime * 1.35 + instanceMatrix[3].x * 0.11 + instanceMatrix[3].z * 0.13);
  float sw2 = sin(uTime * 2.7 + instanceMatrix[3].z * 0.21);
  float h2 = position.y * position.y;
  transformed.x += (sw * 0.045 + sw2 * 0.012) * h2;
  transformed.z += (sw2 * 0.03) * h2;
`;

function windify(mat, on) {
  mat.customProgramCacheKey = () => `tree${on ? 1 : 0}`;
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uTime = U.uTime;
    if (!on) return;
    shader.vertexShader = shader.vertexShader.replace('#include <common>', '#include <common>\nuniform float uTime;').replace('#include <begin_vertex>', `#include <begin_vertex>\n${WIND}`);
  };
}

export function makeTrees(data, opts) {
  const group = new THREE.Group();
  const geos = treeGeometries(opts.leafCards);
  const coreMat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.92, flatShading: false });
  windify(coreMat, opts.wind);
  const leafMat = new THREE.MeshStandardMaterial({ vertexColors: true, map: leafTexture(), alphaTest: 0.5, side: THREE.DoubleSide, roughness: 0.85 });
  windify(leafMat, opts.wind);
  const byKind = [[], [], [], []];
  for (const t of data.trees) byKind[t[0]].push(t);
  const m4 = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);
  const col = new THREE.Color();
  const v3 = new THREE.Vector3();
  const sc = new THREE.Vector3();
  byKind.forEach((list, k) => {
    if (!list.length) return;
    const parts = [[geos[k].core, coreMat, k !== 3]];
    if (geos[k].cards) parts.push([geos[k].cards, leafMat, false]);
    for (const [geo, mat, cast] of parts) {
      const im = new THREE.InstancedMesh(geo, mat, list.length);
      list.forEach((t, i) => {
        const [, x, y, z, h, w, rot] = t;
        q.setFromAxisAngle(up, rot);
        m4.compose(v3.set(x, y, z), q, sc.set(w * 1.15, h, w * 1.15));
        im.setMatrixAt(i, m4);
        const v = 0.82 + 0.3 * (Math.abs(Math.sin(i * 91.7 + k) * 43758.5453) % 1);
        col.setRGB(v, v * (0.96 + 0.08 * Math.sin(i)), v * 0.94);
        im.setColorAt(i, col);
      });
      im.castShadow = cast;
      im.receiveShadow = true;
      im.frustumCulled = false;
      group.add(im);
    }
  });
  return group;
}
