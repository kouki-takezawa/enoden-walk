import * as THREE from 'three';

/** soft radial sprite texture */
export function glowTexture(rgb = '255,255,255', size = 64) {
  if (typeof document === 'undefined') return null; // unit tests run without a DOM
  const cv = document.createElement('canvas');
  cv.width = cv.height = size;
  const g = cv.getContext('2d');
  const grd = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  grd.addColorStop(0, `rgba(${rgb},1)`);
  grd.addColorStop(0.22, `rgba(${rgb},0.55)`);
  grd.addColorStop(1, `rgba(${rgb},0)`);
  g.fillStyle = grd;
  g.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(cv);
}

/** centres of the separate blobs of vertices of a mesh (world space): the lamp heads of a merged lamp mesh */
function clusterCentres(mesh, gap = 0.6) {
  mesh.updateWorldMatrix(true, false);
  const pos = mesh.geometry.attributes.position;
  const v = new THREE.Vector3();
  const cl = [];
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i).applyMatrix4(mesh.matrixWorld);
    let c = cl.find((k) => k.c.distanceTo(v) < gap);
    if (!c) {
      c = { c: v.clone(), sum: new THREE.Vector3(), n: 0 };
      cl.push(c);
    }
    c.sum.add(v);
    c.n++;
    c.c.copy(c.sum).divideScalar(c.n);
  }
  return cl.map((k) => k.c);
}

/** red halo around the level-crossing alarm lamps: follows the alternating flash of the lamp materials */
export function makeAlarmGlow(world) {
  const tex = glowTexture('255,60,40');
  const make = (name) => {
    const m = world.getObjectByName(name);
    if (!m || !m.geometry) return null;
    const pts = clusterCentres(m);
    if (!pts.length) return null;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pts.flatMap((p) => [p.x, p.y, p.z]), 3));
    const mat = new THREE.PointsMaterial({ map: tex, size: 1.5, sizeAttenuation: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0, fog: false });
    const o = new THREE.Points(geo, mat);
    o.frustumCulled = false;
    o.matrixAutoUpdate = false;
    return o;
  };
  const on = make('Alarm_Lamps_ON');
  const off = make('Alarm_Lamps_OFF');
  const root = new THREE.Group();
  for (const o of [on, off]) if (o) root.add(o);
  return {
    root,
    update(alarm, phase, night) {
      const k = alarm ? 0.55 + 0.45 * night : 0;
      if (on) on.material.opacity = phase ? k : 0;
      if (off) off.material.opacity = phase ? 0 : k;
      root.visible = alarm;
    },
  };
}

/** light pools on the platform deck under the canopy tubes */
export function makeDeckPools(meta) {
  const cv = document.createElement('canvas');
  cv.width = cv.height = 64;
  const g = cv.getContext('2d');
  const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, 'rgba(255,244,214,0.95)');
  grd.addColorStop(0.5, 'rgba(255,236,190,0.35)');
  grd.addColorStop(1, 'rgba(255,230,180,0)');
  g.fillStyle = grd;
  g.fillRect(0, 0, 64, 64);
  const tex = new THREE.CanvasTexture(cv);
  const pf = meta.platform;
  const geo = new THREE.PlaneGeometry(1, 1);
  geo.rotateX(-Math.PI / 2);
  const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0, fog: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
  const im = new THREE.InstancedMesh(geo, mat, 10);
  const m = new THREE.Matrix4();
  const s = new THREE.Vector3(5.6, 1, 2.3);
  for (let k = 0; k < 10; k++) {
    m.compose(new THREE.Vector3(pf.x0 + 2.25 + 4.5 * k, pf.height + 0.03, -(pf.y0 + pf.y1) / 2), new THREE.Quaternion(), s);
    im.setMatrixAt(k, m);
  }
  im.frustumCulled = false;
  im.renderOrder = 3;
  return {
    mesh: im,
    update(night) {
      mat.opacity = night * 0.5;
      im.visible = night > 0.02;
    },
  };
}

/** additive light cone in front of the leading cab (local +x); intensity 0..1 */
export function makeBeam(len = 36, radius = 3.6) {
  const geo = new THREE.ConeGeometry(radius, len, 28, 1, true);
  geo.translate(0, -len / 2, 0); // tip at the origin, opening toward -y
  geo.rotateZ(Math.PI / 2); // ... now toward +x
  const mat = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
    fog: false,
    uniforms: { uI: { value: 0 }, uLen: { value: len } },
    vertexShader: /* glsl */ `
      varying vec3 vN; varying vec3 vV; varying float vT;
      uniform float uLen;
      void main() {
        vT = position.x / uLen;
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        vN = normalize(normalMatrix * normal);
        vV = normalize(-mv.xyz);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      uniform float uI; varying vec3 vN; varying vec3 vV; varying float vT;
      void main() {
        float f = abs(dot(normalize(vN), normalize(vV)));
        float a = pow(f, 1.6) * pow(max(1.0 - vT, 0.0), 1.7) * smoothstep(0.0, 0.05, vT) * uI * 0.32;
        gl_FragColor = vec4(1.0, 0.9, 0.68, a);
      }`,
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = 4;
  return mesh;
}

/** small blue-white flashes at the pantographs (highest points of the train), only after dark */
export function makeSparks(trainRoot) {
  let maxY = -1e9;
  const verts = [];
  const v = new THREE.Vector3();
  trainRoot.updateWorldMatrix(true, true);
  trainRoot.traverse((o) => {
    if (!o.isMesh) return;
    const p = o.geometry.attributes.position;
    for (let i = 0; i < p.count; i++) {
      v.fromBufferAttribute(p, i).applyMatrix4(o.matrixWorld);
      verts.push(v.clone());
      if (v.y > maxY) maxY = v.y;
    }
  });
  const top = verts.filter((q) => q.y > maxY - 0.2);
  const cl = [];
  for (const q of top) {
    const c = cl.find((k) => Math.abs(k.x - q.x) < 3);
    if (!c) cl.push(q.clone());
  }
  if (!cl.length) return null;
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(cl.flatMap((p) => [p.x, p.y + 0.05, p.z]), 3));
  const mat = new THREE.PointsMaterial({ map: glowTexture('190,215,255'), size: 0.9, sizeAttenuation: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0, fog: false });
  const pts = new THREE.Points(geo, mat);
  pts.frustumCulled = false;
  let flash = 0;
  return {
    points: pts,
    update(dt, night, speed) {
      if (night < 0.3 || speed < 2) {
        mat.opacity = 0;
        return;
      }
      if (Math.random() < dt * 3.2) flash = 1;
      flash *= Math.exp(-dt * 16);
      mat.opacity = flash * night;
    },
  };
}
