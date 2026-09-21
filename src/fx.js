import * as THREE from 'three';

// uniforms shared by every patched material (updated once per frame in main.js)
export const U = {
  uNight: { value: 0 },
  uTime: { value: 0 },
};

const NOISE = /* glsl */ `
float fxHash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float fxNoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(fxHash(i), fxHash(i + vec2(1.0, 0.0)), f.x), mix(fxHash(i + vec2(0.0, 1.0)), fxHash(i + vec2(1.0, 1.0)), f.x), f.y);
}
`;

function inject(shader, vertexVars, vertexMain, fragGlobals, patches) {
  shader.vertexShader = shader.vertexShader
    .replace('#include <common>', `#include <common>\n${vertexVars}`)
    .replace('#include <begin_vertex>', `#include <begin_vertex>\n${vertexMain}`);
  let f = shader.fragmentShader.replace('#include <common>', `#include <common>\n${NOISE}\n${fragGlobals}`);
  for (const [tag, code] of patches) f = f.replace(tag, `${tag}\n${code}`);
  shader.fragmentShader = f;
}

/** PLATEAU building walls: window grid + frames + soiling from the baked wall UV (m along the wall, m above the base) and the alpha code. */
export function patchBuildingWall(mat, detail) {
  mat.customProgramCacheKey = () => `bwall${detail}`;
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uNight = U.uNight;
    inject(
      shader,
      'varying vec2 vWUv; varying vec3 vWPos;',
      'vWUv = uv; vWPos = (modelMatrix * vec4(transformed, 1.0)).xyz;',
      'uniform float uNight; varying vec2 vWUv; varying vec3 vWPos; float gGlass = 0.0; float gLit = 0.0;',
      [
        [
          '#include <color_fragment>',
          `
          {
            float code = vColor.a;
            if (code > 0.09) {
              float kind = code < 0.4 ? 0.0 : (code < 0.7 ? 1.0 : 2.0);
              float wsd = clamp((code - (0.10 + 0.30 * kind)) / 0.28, 0.0, 1.0);
              float storey = kind == 1.0 ? 3.0 : 2.9;
              float sp = 1.8 + wsd * 0.9 + (kind == 1.0 ? 0.8 : 0.0);
              vec2 cell = vec2((vWUv.x + wsd * 6.0) / sp, vWUv.y / storey);
              vec2 f = fract(cell);
              vec2 id = floor(cell);
              float mort = 0.30 - (kind == 1.0 ? 0.04 : 0.0) + (wsd > 0.82 ? 0.42 : 0.0);
              vec2 inn = step(vec2(mort), f) * step(f, vec2(1.0 - mort));
              float win = inn.x * inn.y;
              vec2 fo = step(vec2(mort - 0.05), f) * step(f, vec2(1.0 - mort + 0.05));
              float frame = fo.x * fo.y * (1.0 - win);
              ${detail > 0 ? 'float dirt = fxNoise(vec2(vWUv.x * 1.3, vWUv.y * 0.35)) * 0.16 + fxNoise(vec2(vWUv.x * 7.0, vWUv.y * 1.5)) * 0.05; diffuseColor.rgb *= 0.95 - dirt + 0.06 * smoothstep(0.0, 1.6, vWUv.y);' : ''}
              vec3 glass = mix(vec3(0.045, 0.07, 0.10), vec3(0.16, 0.22, 0.28), f.y);
              diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.80, 0.80, 0.78), frame * 0.9);
              diffuseColor.rgb = mix(diffuseColor.rgb, glass, win);
              gGlass = win;
              gLit = step(fxHash(id + vec2(wsd * 17.0, kind * 3.0)), 0.36) * uNight * win;
            } else {
              ${detail > 0 ? 'diffuseColor.rgb *= 0.93 + 0.14 * fxNoise(vWPos.xz * 1.7 + vWPos.y * 0.4);' : ''}
            }
          }`,
        ],
        ['#include <roughnessmap_fragment>', 'roughnessFactor = mix(roughnessFactor, 0.09, gGlass);'],
        ['#include <metalnessmap_fragment>', 'metalnessFactor = mix(metalnessFactor, 0.35, gGlass);'],
        ['#include <emissivemap_fragment>', 'totalEmissiveRadiance += vec3(1.0, 0.72, 0.38) * gLit * 1.7;'],
      ],
    );
  };
  mat.needsUpdate = true;
}

/** terrain: large-scale patchiness + fine grain in the vertex colour (removes the faceted, flat look of the slopes) */
export function patchTerrain(mat, detail) {
  mat.customProgramCacheKey = () => `terrain${detail}`;
  mat.onBeforeCompile = (shader) => {
    inject(
      shader,
      'varying vec3 vWPos;',
      'vWPos = (modelMatrix * vec4(transformed, 1.0)).xyz;',
      'varying vec3 vWPos;',
      [
        [
          '#include <color_fragment>',
          detail > 0
            ? `{
            float n1 = fxNoise(vWPos.xz * 0.30);
            float n2 = fxNoise(vWPos.xz * 2.3 + 11.0);
            float n3 = fxNoise(vWPos.xz * 9.0 + 3.0);
            diffuseColor.rgb *= 0.80 + 0.36 * n1 + 0.14 * (n2 - 0.5) + ${detail > 1 ? '0.10' : '0.05'} * (n3 - 0.5);
            diffuseColor.rgb = mix(diffuseColor.rgb, diffuseColor.rgb * vec3(0.90, 1.07, 0.82), smoothstep(0.55, 0.85, n1));
            // sand: faint ripples, and damp darker sand near the waterline
            float sandK = smoothstep(0.0, 0.05, diffuseColor.r - diffuseColor.g) * smoothstep(0.04, 0.14, diffuseColor.r - diffuseColor.b);
            float rip = sin(dot(vWPos.xz, vec2(0.87, 0.5)) * 6.5 + fxNoise(vWPos.xz * 0.7) * 6.0);
            diffuseColor.rgb *= 1.0 + sandK * (0.05 * rip + 0.10 * (n3 - 0.5));
            diffuseColor.rgb *= 1.0 - 0.30 * smoothstep(-2.7, -3.7, vWPos.y) * sandK;
          }`
            : '',
        ],
      ],
    );
  };
  mat.needsUpdate = true;
}

/** road surface: blotchy wear + fine aggregate */
export function patchAsphalt(mat, detail) {
  mat.customProgramCacheKey = () => `asphalt${detail}`;
  mat.onBeforeCompile = (shader) => {
    inject(shader, 'varying vec3 vWPos;', 'vWPos = (modelMatrix * vec4(transformed, 1.0)).xyz;', 'varying vec3 vWPos;', [
      [
        '#include <color_fragment>',
        detail > 0
          ? `{
          float n1 = fxNoise(vWPos.xz * 0.55);
          float n2 = fxNoise(vWPos.xz * 7.5);
          float crack = smoothstep(0.02, 0.0, abs(fxNoise(vWPos.xz * 1.15 + 5.0) - 0.5) - 0.012);
          diffuseColor.rgb *= 0.80 + 0.32 * n1 + 0.14 * n2 - ${detail > 1 ? '0.16' : '0.08'} * crack;
        }`
          : '',
      ],
    ]);
  };
  mat.needsUpdate = true;
}

/** far land (Enoshima, headlands, Hakone, Fuji): hazy blue silhouettes lighter with height, snow on Fuji */
export function farLandMaterial() {
  const mat = new THREE.MeshBasicMaterial({ color: 0x8b98ad, fog: false });
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uNight = U.uNight;
    shader.vertexShader = shader.vertexShader.replace('#include <common>', '#include <common>\nvarying float vY;').replace('#include <begin_vertex>', '#include <begin_vertex>\nvY = (modelMatrix * vec4(transformed, 1.0)).y;');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying float vY; uniform float uNight;')
      .replace(
        '#include <color_fragment>',
        `#include <color_fragment>
        vec3 base = vec3(0.30, 0.38, 0.52);
        vec3 haze = vec3(0.66, 0.62, 0.66);
        diffuseColor.rgb = mix(base, haze, smoothstep(0.0, 1400.0, vY) * 0.55 + 0.25);
        diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.92, 0.93, 0.97), smoothstep(2500.0, 3000.0, vY));
        diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.05, 0.07, 0.13), uNight * 0.92);`,
      );
  };
  return mat;
}
