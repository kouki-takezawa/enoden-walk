import * as THREE from 'three';

/**
 * Split a large indexed mesh into spatial chunks so that frustum culling (main view AND shadow view) can skip the parts that are out of sight.
 * The chunks share the vertex attributes and one re-ordered index buffer (only drawRange differs), so GPU memory does not grow.
 * Returns the number of chunks (0 = left untouched).
 */
export function chunkMesh(mesh, cell = 120, minTris = 20000) {
  const geo = mesh.geometry;
  if (!geo.index || !mesh.parent) return 0;
  const tris = geo.index.count / 3;
  if (tris < minTris) return 0;
  mesh.updateWorldMatrix(true, false);
  const pos = geo.attributes.position;
  const idx = geo.index.array;
  const m = mesh.matrixWorld;
  const e = m.elements;
  // world x/z of every vertex is only needed for the triangle centroids: transform lazily
  const wx = (i) => e[0] * pos.getX(i) + e[4] * pos.getY(i) + e[8] * pos.getZ(i) + e[12];
  const wz = (i) => e[2] * pos.getX(i) + e[6] * pos.getY(i) + e[10] * pos.getZ(i) + e[14];
  const keyOf = new Int32Array(tris);
  const counts = new Map();
  for (let t = 0; t < tris; t++) {
    const a = idx[t * 3];
    const b = idx[t * 3 + 1];
    const c = idx[t * 3 + 2];
    const cx = Math.floor((wx(a) + wx(b) + wx(c)) / 3 / cell);
    const cz = Math.floor((wz(a) + wz(b) + wz(c)) / 3 / cell);
    const k = (cx + 512) * 1024 + (cz + 512);
    keyOf[t] = k;
    counts.set(k, (counts.get(k) || 0) + 1);
  }
  if (counts.size < 2) return 0;
  // counting sort of the triangles by cell
  const keys = [...counts.keys()].sort((p, q) => p - q);
  const start = new Map();
  let acc = 0;
  for (const k of keys) {
    start.set(k, acc);
    acc += counts.get(k);
  }
  const sorted = new (idx.constructor)(idx.length);
  const fill = new Map(start);
  for (let t = 0; t < tris; t++) {
    const k = keyOf[t];
    const o = fill.get(k) * 3;
    fill.set(k, fill.get(k) + 1);
    sorted[o] = idx[t * 3];
    sorted[o + 1] = idx[t * 3 + 1];
    sorted[o + 2] = idx[t * 3 + 2];
  }
  const index = new THREE.BufferAttribute(sorted, 1);
  const parent = mesh.parent;
  const box = new THREE.Box3();
  const v = new THREE.Vector3();
  let n = 0;
  for (const k of keys) {
    const s = start.get(k);
    const cnt = counts.get(k);
    const g = new THREE.BufferGeometry();
    for (const name in geo.attributes) g.setAttribute(name, geo.attributes[name]);
    g.setIndex(index);
    g.setDrawRange(s * 3, cnt * 3);
    box.makeEmpty();
    for (let i = s * 3; i < (s + cnt) * 3; i++) box.expandByPoint(v.fromBufferAttribute(pos, sorted[i]));
    g.boundingBox = box.clone();
    g.boundingSphere = box.getBoundingSphere(new THREE.Sphere());
    const part = new THREE.Mesh(g, mesh.material);
    part.name = `${mesh.name}#${n++}`;
    part.position.copy(mesh.position);
    part.quaternion.copy(mesh.quaternion);
    part.scale.copy(mesh.scale);
    part.castShadow = mesh.castShadow;
    part.receiveShadow = mesh.receiveShadow;
    part.renderOrder = mesh.renderOrder;
    parent.add(part);
  }
  mesh.removeFromParent();
  return n;
}

/** chunk the few big static meshes (terrain, the largest building batches); chunking small ones would only add draw calls */
export function chunkWorld(root, cell = 120) {
  const list = [];
  root.traverse((o) => {
    if (o.isMesh && !/^(Barrier|Alarm|FarLand)/.test(o.name) && !o.isSkinnedMesh) list.push(o);
  });
  let chunks = 0;
  for (const m of list) chunks += chunkMesh(m, cell);
  return chunks;
}
