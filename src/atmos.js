import * as THREE from 'three';
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js';
import { U } from './fx.js';

/** Fog with warm in-scattering toward the sun (aerial perspective).  Patches the built-in fog chunks once, before any material compiles;
 *  every material gets the two shared uniforms through Material.prototype.onBeforeCompile (materials with their own patch just see zeros = plain fog). */
export function installFog() {
  const C = THREE.ShaderChunk;
  C.fog_pars_vertex = C.fog_pars_vertex.replace('varying float vFogDepth;', 'varying float vFogDepth;\n\tvarying vec3 vFogDir;');
  C.fog_vertex = C.fog_vertex.replace('vFogDepth = - mvPosition.z;', 'vFogDepth = - mvPosition.z;\n\tvFogDir = mvPosition.xyz;');
  C.fog_pars_fragment = C.fog_pars_fragment.replace('varying float vFogDepth;', 'varying float vFogDepth;\n\tvarying vec3 vFogDir;\n\tuniform vec3 uSunView;\n\tuniform vec3 uSunCol;');
  C.fog_fragment = C.fog_fragment.replace(
    'gl_FragColor.rgb = mix( gl_FragColor.rgb, fogColor, fogFactor );',
    `float fogSun = pow( max( dot( normalize( vFogDir ), uSunView ), 0.0 ), 5.0 );
	gl_FragColor.rgb = mix( gl_FragColor.rgb, fogColor + uSunCol * fogSun, fogFactor );`,
  );
  THREE.Material.prototype.onBeforeCompile = function (shader) {
    shader.uniforms.uSunView = U.uSunView;
    shader.uniforms.uSunCol = U.uSunCol;
  };
}

/** Final grading pass (linear HDR, before the output pass): sun shafts, lens flare, split-tone grade, saturation, vignette, faint dither. */
export function makeAtmosPass() {
  const pass = new ShaderPass({
    uniforms: {
      tDiffuse: { value: null },
      uSunUV: { value: new THREE.Vector2(0.5, 0.5) },
      uShaft: { value: 0 },
      uFlare: { value: 0 },
      uAspect: { value: 1 },
      uHi: { value: new THREE.Color(1, 1, 1) },
      uSh: { value: new THREE.Color(1, 1, 1) },
      uSat: { value: 1 },
      uVig: { value: 0.15 },
      uTime: { value: 0 },
    },
    vertexShader: /* glsl */ `
      varying vec2 vUv;
      void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: /* glsl */ `
      uniform sampler2D tDiffuse;
      uniform vec2 uSunUV;
      uniform float uShaft, uFlare, uAspect, uSat, uVig, uTime;
      uniform vec3 uHi, uSh;
      varying vec2 vUv;
      float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
      float h21(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
      void main() {
        vec3 col = texture2D(tDiffuse, vUv).rgb;
        if (uShaft > 0.002) {
          vec2 dir = uSunUV - vUv;
          float dist = length(dir * vec2(uAspect, 1.0));
          const int N = 32;
          vec2 stp = dir * (0.9 / float(N));
          vec2 p = vUv;
          vec3 acc = vec3(0.0);
          float w = 1.0;
          for (int i = 0; i < N; i++) {
            p += stp;
            vec3 s = texture2D(tDiffuse, clamp(p, 0.001, 0.999)).rgb;
            acc += s * smoothstep(0.9, 2.2, luma(s)) * w;
            w *= 0.95;
          }
          col += acc / float(N) * uShaft * exp(-dist * 2.2) * vec3(1.0, 0.80, 0.58);
        }
        if (uFlare > 0.002) {
          float vis = 0.0;
          for (int i = -1; i <= 1; i++) for (int j = -1; j <= 1; j++) vis += smoothstep(1.4, 2.8, luma(texture2D(tDiffuse, clamp(uSunUV + vec2(float(i), float(j)) * 0.006, 0.001, 0.999).xy).rgb));
          vis /= 9.0;
          vis *= smoothstep(0.0, 0.08, uSunUV.x) * smoothstep(1.0, 0.92, uSunUV.x) * smoothstep(0.0, 0.08, uSunUV.y) * smoothstep(1.0, 0.92, uSunUV.y);
          if (vis > 0.002) {
            vec2 v = vec2(0.5) - uSunUV;
            vec2 q = (vUv - uSunUV) * vec2(uAspect, 1.0);
            vec3 fl = vec3(0.0);
            // ghosts along the axis through the screen centre
            for (int k = 0; k < 4; k++) {
              float t = k == 0 ? 0.55 : (k == 1 ? 1.15 : (k == 2 ? 1.7 : -0.35));
              float r = k == 0 ? 0.05 : (k == 1 ? 0.09 : (k == 2 ? 0.035 : 0.12));
              vec2 gp = (uSunUV + v * t);
              float d = length((vUv - gp) * vec2(uAspect, 1.0));
              vec3 tint = k == 0 ? vec3(1.0, 0.7, 0.35) : (k == 1 ? vec3(0.45, 0.75, 1.0) : (k == 2 ? vec3(1.0, 0.5, 0.6) : vec3(1.0, 0.85, 0.5)));
              fl += tint * (exp(-d * d / (r * r)) * 0.12 + smoothstep(0.010, 0.0, abs(d - r * 1.6)) * 0.05);
            }
            float d0 = length(q);
            fl += vec3(1.0, 0.82, 0.55) * (exp(-d0 * 6.0) * 0.16 + exp(-d0 * 24.0) * 0.30);
            col += fl * vis * uFlare;
          }
        }
        float l = luma(col);
        col *= mix(uSh, uHi, smoothstep(0.0, 1.2, l));
        col = mix(vec3(luma(col)), col, uSat);
        vec2 c = (vUv - 0.5) * vec2(uAspect, 1.0);
        col *= 1.0 - uVig * smoothstep(0.35, 1.05, length(c));
        col += (h21(vUv * 1731.0 + uTime) - 0.5) * 0.006;
        gl_FragColor = vec4(max(col, 0.0), 1.0);
      }`,
  });
  pass.enabled = true;
  return pass;
}

/** Chromatic aberration (radial, stronger toward the edges) + a faint film grain dither: cheap enough (three texture
 *  taps + one hash) that it runs on every quality preset, including `low`, unlike the heavier atmos pass above. */
export function makeGradePass() {
  const pass = new ShaderPass({
    uniforms: {
      tDiffuse: { value: null },
      uAspect: { value: 1 },
      uTime: { value: 0 },
      uCA: { value: 0.0016 },
      uGrain: { value: 0.018 },
    },
    vertexShader: /* glsl */ `
      varying vec2 vUv;
      void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: /* glsl */ `
      uniform sampler2D tDiffuse;
      uniform float uAspect, uTime, uCA, uGrain;
      varying vec2 vUv;
      float gh21(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
      void main() {
        vec2 c = (vUv - 0.5) * vec2(uAspect, 1.0);
        vec2 dir = c * dot(c, c) * uCA;
        float r = texture2D(tDiffuse, vUv - dir).r;
        float g = texture2D(tDiffuse, vUv).g;
        float b = texture2D(tDiffuse, vUv + dir).b;
        vec3 col = vec3(r, g, b);
        col += (gh21(vUv * 1731.0 + uTime) - 0.5) * uGrain;
        gl_FragColor = vec4(max(col, 0.0), 1.0);
      }`,
  });
  return pass;
}
