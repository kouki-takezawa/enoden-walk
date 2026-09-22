import * as THREE from 'three';

// uniforms shared by every patched material (updated once per frame in main.js)
export const U = {
  uNight: { value: 0 },
  uTime: { value: 0 },
  uGust: { value: 0 }, // 0..1 wind gust (a train rushing past)
  uWet: { value: 0 }, // 0..1 rain-soaked ground
  uCloudSh: { value: 0 }, // 0..1 drifting cloud shadows on the ground
  uGlit: { value: 0 }, // 0..1 sun glitter on the sea
  uSunView: { value: new THREE.Vector3(0, 1, 0) }, // sun direction in view space (fog in-scattering)
  uSunCol: { value: new THREE.Vector3() }, // warm in-scattering colour * strength
};

const NOISE = /* glsl */ `
float fxHash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float fxNoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(fxHash(i), fxHash(i + vec2(1.0, 0.0)), f.x), mix(fxHash(i + vec2(0.0, 1.0)), fxHash(i + vec2(1.0, 1.0)), f.x), f.y);
}
// second, higher-frequency octave layered on top of fxNoise (used by the bump / roughness helpers below)
float fxNoise2(vec2 p) { return fxNoise(p) * 0.62 + fxNoise(p * 2.37 + 5.2) * 0.38; }
float fxRoughNoise(vec3 P, float freq) { return fxNoise(P.xz * freq) * 0.6 + fxNoise(P.xz * freq * 3.1 + 17.0) * 0.4; }
// Derivative-based bump mapping (Mikkelsen, "bump mapping unparametrized surfaces on the GPU"): perturbs the
// already-computed surface normal from a scalar height field h(P), using only screen-space derivatives of the
// world position and of h. No tangent attribute / normal map texture / tileable UV is required, which is why
// it is used here instead of a real normalMap: the wall / terrain / road / deck meshes have no image textures
// and their UVs (where they exist at all) are not laid out for texel-space normal mapping.
vec3 fxBump(vec3 N, vec3 P, float h, float amp) {
  vec3 dPdx = dFdx(P);
  vec3 dPdy = dFdy(P);
  float dHdx = dFdx(h);
  float dHdy = dFdy(h);
  vec3 r1 = cross(dPdy, N);
  vec3 r2 = cross(N, dPdx);
  float det = dot(dPdx, r1);
  vec3 grad = (dHdx * r1 + dHdy * r2) / max(1e-6, abs(det));
  return normalize(N - amp * grad * sign(det));
}
// Cheap single-sample parallax (not full occlusion marching): offsets a UV-like coordinate along the surface's
// own tangent/bitangent (solved from the P<->uv derivative pair, so it needs no vertex tangent attribute either).
vec2 fxParallax(vec3 P, vec2 uv, vec3 V, float depth) {
  vec3 dPdx = dFdx(P);
  vec3 dPdy = dFdy(P);
  vec2 dUVdx = dFdx(uv);
  vec2 dUVdy = dFdy(uv);
  float det = dUVdx.x * dUVdy.y - dUVdy.x * dUVdx.y;
  float invDet = 1.0 / max(1e-6, abs(det));
  vec3 T = normalize((dPdx * dUVdy.y - dPdy * dUVdx.y) * invDet);
  vec3 B = normalize((dPdy * dUVdx.x - dPdx * dUVdy.x) * invDet);
  return vec2(dot(V, T), dot(V, B)) * depth;
}
`;

/** materials whose env reflection is raised while it rains (see main.js) */
export const wetMats = new Set();

function inject(shader, vertexVars, vertexMain, fragGlobals, patches) {
  shader.uniforms.uTime = U.uTime;
  shader.uniforms.uWet = U.uWet;
  shader.uniforms.uCloudSh = U.uCloudSh;
  shader.uniforms.uSunView = U.uSunView;
  shader.uniforms.uSunCol = U.uSunCol;
  shader.vertexShader = shader.vertexShader
    .replace('#include <common>', `#include <common>\n${vertexVars}`)
    .replace('#include <begin_vertex>', `#include <begin_vertex>\n${vertexMain}`);
  let f = shader.fragmentShader.replace('#include <common>', `#include <common>\nuniform float uTime;\nuniform float uWet;\nuniform float uCloudSh;\n${NOISE}\n${fragGlobals}`);
  for (const [tag, code] of patches) f = f.replace(tag, `${tag}\n${code}`);
  shader.fragmentShader = f;
}

/** PLATEAU building walls: window grid + frames + soiling from the baked wall UV (m along the wall, m above the base) and the alpha code.
 *  `bump` (ultra preset only) adds mortar/frame normal perturbation, roughness micro-variation and a single-sample window parallax. */
export function patchBuildingWall(mat, detail, bump) {
  mat.customProgramCacheKey = () => `bwall${detail}${bump ? 'b' : ''}`;
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uNight = U.uNight;
    inject(
      shader,
      'varying vec2 vWUv; varying vec3 vWPos;',
      'vWUv = uv; vWPos = (modelMatrix * vec4(transformed, 1.0)).xyz;',
      'uniform float uNight; varying vec2 vWUv; varying vec3 vWPos; float gGlass = 0.0; float gLit = 0.0; float gFrame = 0.0;',
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
              ${
                bump
                  ? 'vec2 wpar = fxParallax(vWPos, vWUv, normalize(cameraPosition - vWPos), 0.05);'
                  : 'vec2 wpar = vec2(0.0);'
              }
              vec2 cell = vec2((vWUv.x + wpar.x + wsd * 6.0) / sp, (vWUv.y + wpar.y) / storey);
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
              gFrame = frame;
              gLit = step(fxHash(id + vec2(wsd * 17.0, kind * 3.0)), 0.36) * uNight * win;
            } else {
              ${detail > 0 ? 'diffuseColor.rgb *= 0.93 + 0.14 * fxNoise(vWPos.xz * 1.7 + vWPos.y * 0.4);' : ''}
            }
          }`,
        ],
        ...(bump
          ? [
              [
                '#include <normal_fragment_maps>',
                'normal = fxBump(normal, vWPos, fxNoise2(vWUv * vec2(9.0, 6.0)) * (1.0 - gGlass) + gFrame * 0.6, 0.30);',
              ],
              ['#include <roughnessmap_fragment>', 'roughnessFactor = clamp(roughnessFactor + (fxRoughNoise(vWPos, 3.2) - 0.5) * 0.18 * (1.0 - gGlass), 0.045, 1.0);'],
            ]
          : []),
        // C6.1: rain makes the glass mirror-glossy too (the same envMapIntensity-boost trick `wetMats` uses for the
        // road/deck can't target glass alone since it's a material-wide scalar; this does it per-pixel instead)
        ['#include <roughnessmap_fragment>', 'roughnessFactor = mix(roughnessFactor, 0.09 - 0.055 * uWet, gGlass);'],
        ['#include <metalnessmap_fragment>', 'metalnessFactor = mix(metalnessFactor, 0.35, gGlass);'],
        ['#include <emissivemap_fragment>', 'totalEmissiveRadiance += vec3(1.0, 0.72, 0.38) * gLit * 1.7;'],
      ],
    );
  };
  mat.needsUpdate = true;
}

/** terrain: large-scale patchiness + fine grain in the vertex colour (removes the faceted, flat look of the slopes).
 *  `bump` (ultra preset only) adds normal perturbation + roughness micro-variation from the same noise field. */
export function patchTerrain(mat, detail, bump) {
  mat.customProgramCacheKey = () => `terrain${detail}${bump ? 'b' : ''}`;
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
        [
          '#include <color_fragment>',
          'diffuseColor.rgb *= 1.0 - uCloudSh * 0.30 * smoothstep(0.50, 0.72, fxNoise(vWPos.xz * 0.013 + vec2(uTime * 0.035, uTime * 0.014)));',
        ],
        ...(bump
          ? [
              ['#include <normal_fragment_maps>', 'normal = fxBump(normal, vWPos, fxNoise2(vWPos.xz * 2.6) + fxNoise2(vWPos.xz * 11.0) * 0.4, 0.55);'],
              ['#include <roughnessmap_fragment>', 'roughnessFactor = clamp(roughnessFactor + (fxRoughNoise(vWPos, 4.5) - 0.5) * 0.22, 0.15, 1.0);'],
            ]
          : []),
      ],
    );
  };
  mat.needsUpdate = true;
}

/** road surface: blotchy wear + fine aggregate. `bump` (ultra preset only) adds crack-driven normal
 *  perturbation and roughness micro-variation, faded out on wet/puddled patches so the rain look is untouched. */
export function patchAsphalt(mat, detail, bump) {
  mat.customProgramCacheKey = () => `asphalt${detail}${bump ? 'b' : ''}`;
  wetMats.add(mat);
  mat.onBeforeCompile = (shader) => {
    inject(shader, 'varying vec3 vWPos;', 'vWPos = (modelMatrix * vec4(transformed, 1.0)).xyz;', 'varying vec3 vWPos; float gWet = 0.0;', [
      [
        '#include <color_fragment>',
        `${
          detail > 0
            ? `{
          float n1 = fxNoise(vWPos.xz * 0.55);
          float n2 = fxNoise(vWPos.xz * 7.5);
          float crack = smoothstep(0.02, 0.0, abs(fxNoise(vWPos.xz * 1.15 + 5.0) - 0.5) - 0.012);
          diffuseColor.rgb *= 0.80 + 0.32 * n1 + 0.14 * n2 - ${detail > 1 ? '0.16' : '0.08'} * crack;
        }`
            : ''
        }
        diffuseColor.rgb *= 1.0 - uCloudSh * 0.30 * smoothstep(0.50, 0.72, fxNoise(vWPos.xz * 0.013 + vec2(uTime * 0.035, uTime * 0.014)));
        {
          // rain: the road darkens and puddles form in the low, noisy patches
          float pud = smoothstep(0.50, 0.70, fxNoise(vWPos.xz * 0.35 + 9.0));
          gWet = uWet * (0.55 + 0.45 * pud);
          diffuseColor.rgb *= 1.0 - 0.34 * gWet;
        }`,
      ],
      ...(bump
        ? [
            ['#include <normal_fragment_maps>', 'normal = fxBump(normal, vWPos, fxNoise2(vWPos.xz * 6.0) + fxNoise2(vWPos.xz * 1.2 + 5.0) * 0.5, 0.28 * (1.0 - gWet));'],
            ['#include <roughnessmap_fragment>', 'roughnessFactor = clamp(roughnessFactor + (fxRoughNoise(vWPos, 8.0) - 0.5) * 0.16 * (1.0 - gWet), 0.06, 1.0);'],
          ]
        : []),
      ['#include <roughnessmap_fragment>', 'roughnessFactor = mix(roughnessFactor, 0.045, gWet);'],
    ]);
  };
  mat.needsUpdate = true;
}

/** Generic small-prop / secondary-surface weathering (roofs, concrete, stone, steel, wood fences and benches, rusty
 *  rail...): the same "blotchy colour + normal/roughness noise" recipe as the wall/terrain/road patches above, but
 *  without any material-specific pattern (no window grid, no puddle logic) — most of the 53 materials this project
 *  builds in Blender only need *some* texture breakup to stop looking like a single flat colour, not a bespoke
 *  shader, so one parametrised function covers all of them instead of writing one function per material. */
export function patchGeneric(mat, detail, bump, { freq = 1.2, amp = 0.22, bumpFreq = 6.0, bumpAmp = 0.18 } = {}) {
  // GLSL ES has no implicit int->float conversion for overload resolution, and JS stringifies a whole-number float
  // (e.g. 9.0) as "9" — silently producing an int literal that fails to link against a `float` parameter. Every
  // runtime-configured number reaching the shader source below must go through this.
  const f = (n) => (Number.isInteger(n) ? n.toFixed(1) : String(n));
  mat.customProgramCacheKey = () => `generic${detail}${bump ? 'b' : ''}${freq}`;
  mat.onBeforeCompile = (shader) => {
    inject(shader, 'varying vec3 vWPos;', 'vWPos = (modelMatrix * vec4(transformed, 1.0)).xyz;', 'varying vec3 vWPos;', [
      [
        '#include <color_fragment>',
        detail > 0
          ? `{
          float n1 = fxNoise(vWPos.xz * ${f(freq)} + vWPos.y * ${f(freq)});
          float n2 = fxNoise(vWPos.xz * ${f(freq * 6.0)} + 5.0);
          diffuseColor.rgb *= 1.0 - ${f(amp)} * 0.5 + ${f(amp)} * n1 + ${f(amp)} * 0.3 * (n2 - 0.5);
        }`
          : '',
      ],
      ...(bump
        ? [
            [
              '#include <normal_fragment_maps>',
              `normal = fxBump(normal, vWPos, fxNoise2(vWPos.xz * ${f(bumpFreq)} + vWPos.y * ${f(bumpFreq)}), ${f(bumpAmp)});`,
            ],
            ['#include <roughnessmap_fragment>', `roughnessFactor = clamp(roughnessFactor + (fxRoughNoise(vWPos, ${f(bumpFreq)}) - 0.5) * 0.14, 0.05, 0.95);`],
          ]
        : []),
    ]);
  };
  mat.needsUpdate = true;
}

/** platform deck / wooden posts / tactile strip: grime, worn yellow paint, dirty column bases, wet patches (all confined to the deck's world box).
 *  `bump` (ultra preset only) adds plank/grain normal perturbation on top, faded out on wet patches. */
export function patchDeck(mat, kind, bump) {
  mat.customProgramCacheKey = () => `deck-${kind}${bump ? 'b' : ''}`;
  if (kind === 'top') wetMats.add(mat);
  const body = {
    top: `float n = fxNoise(vec2(vWPos.x * 0.7, vWPos.z * 4.0));
      diffuseColor.rgb *= 0.84 + 0.26 * n + 0.10 * (fxNoise(vWPos.xz * 6.0) - 0.5);
      float pud = smoothstep(0.50, 0.68, fxNoise(vWPos.xz * 0.5 + 2.0));
      gWet = uWet * (0.6 + 0.4 * pud);
      diffuseColor.rgb *= 1.0 - 0.28 * gWet;`,
    yellow: `float wear = smoothstep(0.55, 0.82, fxNoise(vWPos.xz * vec2(1.6, 9.0) + 3.0));
      diffuseColor.rgb = mix(diffuseColor.rgb, diffuseColor.rgb * vec3(0.72, 0.66, 0.5), wear * 0.7);
      float chip = smoothstep(0.78, 0.9, fxNoise(vWPos.xz * vec2(4.0, 20.0)));
      diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.36, 0.34, 0.32), chip * 0.5);`,
    wood: `float low = 1.0 - smoothstep(0.0, 0.6, vWPos.y - 1.1);
      float n = fxNoise(vWPos.xz * 3.0 + vWPos.y * 2.0);
      diffuseColor.rgb *= 1.0 - low * (0.18 + 0.22 * n);`,
  }[kind];
  const bumpFreq = { top: 'vec2(0.9, 5.0)', yellow: 'vec2(1.6, 9.0)', wood: 'vec2(2.2, 6.0)' }[kind];
  mat.onBeforeCompile = (shader) => {
    inject(shader, 'varying vec3 vWPos;', 'vWPos = (modelMatrix * vec4(transformed, 1.0)).xyz;', 'varying vec3 vWPos; float gWet = 0.0;', [
      [
        '#include <color_fragment>',
        `if (vWPos.x > -56.0 && vWPos.x < -9.0 && vWPos.z < -1.3 && vWPos.z > -4.6 && vWPos.y > 0.9) {
      ${body}
    }`,
      ],
      ...(bump
        ? [
            [
              '#include <normal_fragment_maps>',
              `if (vWPos.x > -56.0 && vWPos.x < -9.0 && vWPos.z < -1.3 && vWPos.z > -4.6 && vWPos.y > 0.9) {
                normal = fxBump(normal, vWPos, fxNoise2(vWPos.xz * ${bumpFreq}), 0.22 * (1.0 - gWet));
              }`,
            ],
            ['#include <roughnessmap_fragment>', 'roughnessFactor = clamp(roughnessFactor + (fxRoughNoise(vWPos, 5.0) - 0.5) * 0.14 * (1.0 - gWet), 0.08, 1.0);'],
          ]
        : []),
      ['#include <roughnessmap_fragment>', 'roughnessFactor = mix(roughnessFactor, 0.05, gWet);'],
    ]);
  };
  mat.needsUpdate = true;
}

/** Character / train materials have no useful UV (the character body has none at all; the wall/terrain patches above
 *  use world position instead, which is right for fixed scenery but would make skin blemishes or fabric weave swim
 *  across the body as the character walks and turns). These patches key noise off the *bind-pose local* position
 *  instead — `transformed` at `#include <begin_vertex>`, before skinning is applied — so the pattern stays put on
 *  the mesh regardless of where in the world (or what animation pose) it currently is. */
const LOCAL_POS = ['varying vec3 vLocalPos;', 'vLocalPos = transformed;', 'varying vec3 vLocalPos;'];

/** skin: faint warm/cool blotching + pore-scale roughness, plus a cheap fresnel "warm edge glow" standing in for
 *  subsurface scattering (a full SSS BRDF would need patching three.js's lighting chunk; this fakes the same read —
 *  light bleeding through thin tissue at grazing/backlit angles — far more cheaply, and suits this scene's frequent
 *  low, warm dusk sun especially well). `bump` (ultra preset only) adds pore-scale normal perturbation. */
export function patchSkin(mat, detail, bump) {
  mat.customProgramCacheKey = () => `skin${detail}${bump ? 'b' : ''}`;
  mat.onBeforeCompile = (shader) => {
    inject(shader, ...LOCAL_POS, [
      [
        '#include <color_fragment>',
        detail > 0
          ? `{
          float blot = fxNoise(vLocalPos.xz * 3.2 + vLocalPos.y * 2.4);
          float fine = fxNoise(vLocalPos.xz * 12.0 + 5.0);
          diffuseColor.rgb *= 0.94 + 0.09 * fine;
          diffuseColor.rgb = mix(diffuseColor.rgb, diffuseColor.rgb * vec3(1.07, 0.93, 0.89), smoothstep(0.52, 0.85, blot) * 0.55);
        }`
          : '',
      ],
      ['#include <roughnessmap_fragment>', 'roughnessFactor = clamp(roughnessFactor + (fxRoughNoise(vLocalPos, 22.0) - 0.5) * 0.10, 0.30, 0.85);'],
      ...(bump ? [['#include <normal_fragment_maps>', 'normal = fxBump(normal, vLocalPos, fxNoise2(vLocalPos.xz * 38.0 + vLocalPos.y * 26.0), 0.05);']] : []),
      [
        '#include <emissivemap_fragment>',
        '{ float fres = pow(1.0 - clamp(dot(normalize(normal), normalize(vViewPosition)), 0.0, 1.0), 3.0); totalEmissiveRadiance += vec3(0.55, 0.16, 0.09) * fres * 0.09; }',
      ],
    ]);
  };
  mat.needsUpdate = true;
}

/** hair: per-strand-ish colour variation (warm brown highlights over the near-black base) and roughness streaking,
 *  so it reads as hair instead of a flat dark cap. */
export function patchHair(mat, detail) {
  mat.customProgramCacheKey = () => `hair${detail}`;
  mat.onBeforeCompile = (shader) => {
    inject(shader, ...LOCAL_POS, [
      [
        '#include <color_fragment>',
        detail > 0
          ? `{
          float strand = fxNoise(vLocalPos.xz * 60.0 + vLocalPos.y * 44.0);
          float hi = smoothstep(0.60, 0.90, strand);
          diffuseColor.rgb = mix(diffuseColor.rgb, diffuseColor.rgb * vec3(1.9, 1.5, 1.15), hi * 0.30);
          diffuseColor.rgb *= 0.86 + 0.26 * fxNoise(vLocalPos.xz * 13.0 + 3.0);
        }`
          : '',
      ],
      ['#include <roughnessmap_fragment>', 'roughnessFactor = clamp(roughnessFactor + (fxNoise(vLocalPos.xz * 50.0 + vLocalPos.y * 30.0) - 0.5) * 0.28, 0.18, 0.85);'],
    ]);
  };
  mat.needsUpdate = true;
}

/** clothing (tee / chino): weave-scale normal perturbation (`bump`, ultra only) + subtle dye/wash colour variation. */
export function patchFabric(mat, detail, bump) {
  mat.customProgramCacheKey = () => `fabric${detail}${bump ? 'b' : ''}`;
  mat.onBeforeCompile = (shader) => {
    inject(shader, ...LOCAL_POS, [
      ['#include <color_fragment>', detail > 0 ? 'diffuseColor.rgb *= 0.92 + 0.14 * fxNoise(vLocalPos.xz * 5.0 + vLocalPos.y * 4.0);' : ''],
      ['#include <roughnessmap_fragment>', 'roughnessFactor = clamp(roughnessFactor + (fxRoughNoise(vLocalPos, 18.0) - 0.5) * 0.10, 0.55, 0.98);'],
      ...(bump ? [['#include <normal_fragment_maps>', 'normal = fxBump(normal, vLocalPos, fxNoise2(vLocalPos.xz * 70.0 + vLocalPos.y * 55.0), 0.10);']] : []),
    ]);
  };
  mat.needsUpdate = true;
}

/** train livery: the same "dust film near the sill, faint wear" pattern the Blender-side MAT_Enoden_Green / _Cream
 *  materials already model (see build_materials() in enoden_kamakurakokomae.py) — ported to JS since the web export
 *  discards the procedural node graph and left the livery flat. `sill` biases the grime toward the bottom edge. */
export function patchTrainLivery(mat, detail, sill) {
  mat.customProgramCacheKey = () => `livery${detail}${sill ? 's' : ''}`;
  mat.onBeforeCompile = (shader) => {
    inject(shader, ...LOCAL_POS, [
      [
        '#include <color_fragment>',
        detail > 0
          ? `{
          float wear = fxNoise(vLocalPos.xz * 0.35 + vLocalPos.y * 0.6);
          diffuseColor.rgb = mix(diffuseColor.rgb, diffuseColor.rgb * vec3(0.72, 0.72, 0.70), smoothstep(0.55, 0.90, wear) * 0.30);
          diffuseColor.rgb *= 0.95 + 0.08 * fxNoise(vLocalPos.xz * 4.0 + 7.0);
          ${sill ? 'diffuseColor.rgb *= 1.0 - 0.22 * smoothstep(1.1, 0.85, vLocalPos.y) * (0.5 + 0.5 * fxNoise(vLocalPos.xz * 0.8 + 2.0));' : ''}
        }`
          : '',
      ],
      ['#include <roughnessmap_fragment>', 'roughnessFactor = clamp(roughnessFactor + (fxRoughNoise(vLocalPos, 2.0) - 0.5) * 0.10, 0.08, 0.6);'],
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
