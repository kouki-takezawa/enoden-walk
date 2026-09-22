import * as THREE from 'three';
import { U } from './fx.js';

function ripples(N = 256) {
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
  const h = new Float32Array(N * N);
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) h[y * N + x] = smooth(x, y, 64, 1) * 0.5 + smooth(x, y, 32, 2) * 0.3 + smooth(x, y, 16, 3) * 0.2;
  const data = new Uint8Array(N * N * 4);
  for (let y = 0; y < N; y++) {
    for (let x = 0; x < N; x++) {
      const dx = h[y * N + ((x + 1) % N)] - h[y * N + ((x + N - 1) % N)];
      const dy = h[((y + 1) % N) * N + x] - h[((y + N - 1) % N) * N + x];
      const l = Math.hypot(dx * 6, dy * 6, 1);
      const o = (y * N + x) * 4;
      data[o] = (-dx * 6 / l * 0.5 + 0.5) * 255;
      data[o + 1] = (-dy * 6 / l * 0.5 + 0.5) * 255;
      data[o + 2] = (1 / l * 0.5 + 0.5) * 255;
      data[o + 3] = 255;
    }
  }
  const tex = new THREE.DataTexture(data, N, N, THREE.RGBAFormat);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(1200, 1200);
  tex.needsUpdate = true;
  return tex;
}

/** Water depth (metres below the sea surface) baked from the ground heights -> shallow turquoise, foam on the shore. */
function depthTexture(ground, level) {
  const { nx, ny } = ground;
  const half = new Uint16Array(nx * ny);
  for (let i = 0; i < nx * ny; i++) {
    const h = ground.h[i];
    const d = h === h ? level - h : 12;
    half[i] = THREE.DataUtils.toHalfFloat(Math.max(-3, Math.min(14, d)));
  }
  const tex = new THREE.DataTexture(half, nx, ny, THREE.RedFormat, THREE.HalfFloatType);
  tex.minFilter = tex.magFilter = THREE.LinearFilter;
  tex.wrapS = tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.needsUpdate = true;
  return tex;
}

/** Builds the sea shader (colour by depth, sun glitter, foam) on `mat` and, when `displace` is true (Phase C5.1,
 *  ultra preset only), adds a vertex-shader wave height field on top. The huge far plane shares the same look but
 *  is only 2 triangles, so displacing it would just tilt its 4 corners — `displace` must stay off for it. */
function applySeaShader(mat, ground, level, useDepth, depthTex, displace) {
  mat.customProgramCacheKey = () => `sea${useDepth ? 1 : 0}${displace ? 'd' : ''}`;
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uTime = U.uTime;
    shader.uniforms.uNight = U.uNight;
    shader.uniforms.uGlit = U.uGlit;
    shader.uniforms.uSunView = U.uSunView; // declared by the fog chunk
    shader.uniforms.uSunCol = U.uSunCol;
    shader.uniforms.uDepth = { value: depthTex };
    shader.uniforms.uGrid = { value: new THREE.Vector4(ground.x0, ground.y0, ground.nx * ground.step, ground.ny * ground.step) };
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', `#include <common>\nvarying vec3 vWPos;\nuniform float uTime;\nfloat seaVHash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }\nfloat seaVNoise(vec2 p) { vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f); return mix(mix(seaVHash(i), seaVHash(i + vec2(1.0, 0.0)), f.x), mix(seaVHash(i + vec2(0.0, 1.0)), seaVHash(i + vec2(1.0, 1.0)), f.x), f.y); }`)
      .replace(
        '#include <begin_vertex>',
        `#include <begin_vertex>
        vWPos = (modelMatrix * vec4(transformed, 1.0)).xyz;
        ${
          displace
            ? `{
          float w1 = seaVNoise(vWPos.xz * 0.05 + vec2(uTime * 0.10, uTime * 0.07)) - 0.5;
          float w2 = seaVNoise(vWPos.xz * 0.14 - vec2(uTime * 0.16, uTime * 0.05)) - 0.5;
          float w3 = seaVNoise(vWPos.xz * 0.4 + vec2(uTime * 0.3, -uTime * 0.22)) - 0.5;
          transformed.y += w1 * 0.34 + w2 * 0.14 + w3 * 0.045;
        }`
            : ''
        }`,
      );
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nuniform float uTime; uniform float uNight; uniform float uGlit; uniform sampler2D uDepth; uniform vec4 uGrid; varying vec3 vWPos;\nfloat seaHash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }\nfloat seaNoise(vec2 p) { vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f); return mix(mix(seaHash(i), seaHash(i + vec2(1.0, 0.0)), f.x), mix(seaHash(i + vec2(0.0, 1.0)), seaHash(i + vec2(1.0, 1.0)), f.x), f.y); }')
      .replace(
        '#include <color_fragment>',
        `#include <color_fragment>
        ${
          useDepth
            ? `{
          vec2 guv = vec2((vWPos.x - uGrid.x) / uGrid.z, (-vWPos.z - uGrid.y) / uGrid.w);
          vec2 cuv = clamp(guv, 0.002, 0.998);
          float depth = texture2D(uDepth, cuv).r + length((guv - cuv) * uGrid.zw) * 0.10; // beyond the baked grid the sea just keeps deepening
          float wob = sin(uTime * 0.9 + vWPos.x * 0.35 + vWPos.z * 0.22) * 0.13 + sin(uTime * 1.7 - vWPos.x * 0.2) * 0.06;
          float d = depth + wob;
          vec3 shallow = vec3(0.30, 0.78, 0.70);
          vec3 mid = vec3(0.10, 0.50, 0.58);
          vec3 deep = vec3(0.03, 0.17, 0.30);
          vec3 wc = mix(shallow, mid, smoothstep(0.2, 3.0, d));
          wc = mix(wc, deep, smoothstep(3.0, 10.0, d));
          float sn1 = seaNoise(vWPos.xz * 0.6);
          float band = sin(d * 2.6 - uTime * 1.1 + sn1 * 4.0);
          float lines = smoothstep(0.55, 0.95, band) * smoothstep(3.2, 0.5, d) * 0.55;
          float crest = smoothstep(0.80, 1.0, seaNoise(vWPos.xz * vec2(0.45, 1.2) + vec2(uTime * 0.12, 0.0))) * 0.30 * smoothstep(1.2, 4.5, d) * (1.0 - uNight * 0.7);
          float foam = clamp(smoothstep(0.5, 0.0, d) + lines + crest, 0.0, 1.0) * (0.75 + 0.25 * seaNoise(vWPos.xz * 3.0 + uTime * 0.2));
          diffuseColor.rgb = mix(wc, vec3(0.92, 0.96, 0.98), foam * 0.85);
        }`
            : ''
        }`,
      )
      .replace(
        '#include <emissivemap_fragment>',
        `#include <emissivemap_fragment>
        {
          // sun glitter: twinkling facets where the reflected view ray points at the sun
          vec3 gV = normalize(vViewPosition);
          vec3 gR = reflect(-gV, normal);
          float tw = seaNoise(vWPos.xz * 5.0 + vec2(uTime * 0.8, -uTime * 0.6)) * 0.6 + seaNoise(vWPos.xz * 11.0 - uTime * 1.3) * 0.4;
          float gl = pow(max(dot(gR, uSunView), 0.0), 70.0) * smoothstep(0.52, 0.80, tw);
          totalEmissiveRadiance += uSunCol * (gl * 9.0 * uGlit) / max(length(uSunCol), 0.05) * 0.35;
        }`,
      );
  };
  mat.needsUpdate = true;
}

export function makeSea(ground, level, useDepth, waves) {
  const group = new THREE.Group();
  const normalMap = ripples();
  const depthTex = useDepth ? depthTexture(ground, level) : null;
  const matParams = { color: 0x2f7d86, roughness: 0.14, metalness: 0.04, normalMap, normalScale: new THREE.Vector2(0.5, 0.5) };

  const farGeo = new THREE.PlaneGeometry(60000, 60000);
  farGeo.rotateX(-Math.PI / 2);
  const farMat = new THREE.MeshStandardMaterial(matParams);
  applySeaShader(farMat, ground, level, useDepth, depthTex, false);
  group.add(new THREE.Mesh(farGeo, farMat));

  if (waves) {
    // Phase C5.1: a finely subdivided patch near the player only (the far plane stays flat, see applySeaShader) so
    // the vertex-shader wave field actually has geometry to displace, without paying for a 60 km subdivided plane.
    const nearGeo = new THREE.PlaneGeometry(360, 360, 144, 144);
    nearGeo.rotateX(-Math.PI / 2);
    const nearMat = new THREE.MeshStandardMaterial(matParams);
    applySeaShader(nearMat, ground, level, useDepth, depthTex, true);
    const nearMesh = new THREE.Mesh(nearGeo, nearMat);
    nearMesh.position.y = 0.025; // a hair above the far plane: avoids z-fighting at the seam, invisible from a walking eye height
    group.add(nearMesh);
  }

  group.position.y = level + 0.02;
  group.userData.normalMap = normalMap;
  return group;
}
