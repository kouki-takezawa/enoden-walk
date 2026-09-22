import * as THREE from 'three';
import { U } from './fx.js';

const RAD = Math.PI / 180;
const dirFrom = (azDeg, elDeg) => {
  const az = azDeg * RAD;
  const el = elDeg * RAD;
  // compass azimuth (N = +y, E = +x) in Blender -> three.js (z = -y)
  return new THREE.Vector3(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el)).normalize();
};

// ---------------------------------------------------------------------------------------------------- sky dome
export function makeSky(clouds = true) {
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    depthWrite: false,
    fog: false,
    uniforms: {
      sunDir: { value: new THREE.Vector3(0, 1, 0) },
      moonDir: { value: new THREE.Vector3(0, 1, 0) },
      zen: { value: new THREE.Color() },
      mid: { value: new THREE.Color() },
      hor: { value: new THREE.Color() },
      uNight: U.uNight,
      uTime: U.uTime,
      uCloud: { value: 0.5 },
      uSunGlow: { value: 1 },
    },
    defines: { CLOUDS: clouds ? 1 : 0 },
    vertexShader: /* glsl */ `
      varying vec3 vDir;
      void main() {
        vDir = normalize(position);
        vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        gl_Position = p.xyww;
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 sunDir, moonDir, zen, mid, hor;
      uniform float uNight, uTime, uCloud, uSunGlow;
      varying vec3 vDir;
      float h21(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
      float vn(vec2 p) {
        vec2 i = floor(p), f = fract(p);
        f = f * f * (3.0 - 2.0 * f);
        return mix(mix(h21(i), h21(i + vec2(1, 0)), f.x), mix(h21(i + vec2(0, 1)), h21(i + vec2(1, 1)), f.x), f.y);
      }
      float fbm(vec2 p) {
        float a = 0.5, s = 0.0;
        for (int i = 0; i < 4; i++) { s += a * vn(p); p = p * 2.03 + 7.1; a *= 0.5; }
        return s;
      }
      void main() {
        vec3 d = normalize(vDir);
        float h = d.y;
        vec3 col = mix(hor, mid, smoothstep(0.0, 0.16, h));
        col = mix(col, zen, smoothstep(0.10, 0.80, h));
        float s = max(dot(d, normalize(sunDir)), 0.0);
        vec3 sunTint = mix(vec3(1.0, 0.62, 0.30), vec3(1.0, 0.95, 0.85), smoothstep(0.1, 0.6, sunDir.y));
        col += sunTint * pow(s, 6.0) * 0.50 * uSunGlow + vec3(1.0, 0.92, 0.75) * pow(s, 260.0) * 2.5 * uSunGlow;
        #if CLOUDS
        if (h > 0.0) {
          vec2 uv = d.xz / (h + 0.14) * 0.85 + vec2(uTime * 0.006, uTime * 0.002);
          float c = fbm(uv * 1.5);
          c = smoothstep(0.50 - 0.22 * uCloud, 0.85, c);
          vec3 lit = mix(vec3(0.92, 0.90, 0.92), sunTint * 1.15, pow(s, 3.0) * 0.6 + 0.25 * (1.0 - smoothstep(0.1, 0.6, sunDir.y)));
          vec3 ccol = mix(lit, hor * 0.6 + 0.1, 0.35) * mix(1.0, 0.16, uNight);
          col = mix(col, ccol, c * smoothstep(0.0, 0.22, h) * 0.85);
        }
        #endif
        if (uNight > 0.01) {
          vec2 sp = vec2(atan(d.z, d.x) * 46.0, asin(clamp(d.y, -1.0, 1.0)) * 92.0);
          vec2 cell = floor(sp);
          float st = step(0.9965, h21(cell)) * (0.6 + 0.4 * sin(uTime * 2.0 + h21(cell + 3.0) * 30.0));
          col += vec3(0.9, 0.95, 1.0) * st * uNight * smoothstep(0.03, 0.25, h);
          float m = dot(d, normalize(moonDir));
          col += vec3(1.0, 0.97, 0.88) * smoothstep(0.99935, 0.99965, m) * uNight * 2.2;
          col += vec3(0.45, 0.55, 0.85) * pow(max(m, 0.0), 90.0) * 0.28 * uNight;
        }
        col = mix(col, hor * 0.82, smoothstep(0.0, -0.20, h));
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

// ---------------------------------------------------------------------------------------------------- time of day
const c = (h) => new THREE.Color(h);
const lin = (r, g, b) => new THREE.Color().setRGB(r, g, b); // linear multipliers for the grade
export const TOD = {
  day: {
    sunAz: 205, sunEl: 52, lightColor: c(0xfff3e0), lightI: 3.0, hemiSky: c(0xcfe4ff), hemiGround: c(0x857f6a), hemiI: 0.9,
    fog: c(0xc9dcec), fogD: 0.0006, exposure: 1.0, envI: 0.65, zen: c(0x2f6bcc), mid: c(0x8db8e6), hor: c(0xcfe0ee), cloud: 0.75, night: 0, glow: 0,
    gradeHi: lin(1.03, 1.0, 0.96), gradeSh: lin(0.97, 0.99, 1.03), sat: 1.06, vig: 0.15, shaft: 0.10, flare: 0.5, fogSun: 0.10,
  },
  dusk: {
    sunAz: 225, sunEl: 12, lightColor: c(0xffd6a8), lightI: 3.4, hemiSky: c(0xffe6cc), hemiGround: c(0x8a7560), hemiI: 0.6,
    fog: c(0xe9c6a0), fogD: 0.00085, exposure: 1.15, envI: 0.55, zen: c(0x436bb8), mid: c(0xcdb8bd), hor: c(0xffb880), cloud: 0.6, night: 0, glow: 0.15,
    gradeHi: lin(1.08, 1.0, 0.88), gradeSh: lin(0.95, 1.0, 1.07), sat: 1.13, vig: 0.20, shaft: 0.30, flare: 0.7, fogSun: 0.45,
  },
  night: {
    sunAz: 225, sunEl: -22, lightColor: c(0x9fb4ff), lightI: 0.7, hemiSky: c(0x2a3b66), hemiGround: c(0x0e1424), hemiI: 0.55,
    fog: c(0x0c1428), fogD: 0.0012, exposure: 1.7, envI: 0.35, zen: c(0x03060f), mid: c(0x0a1226), hor: c(0x1a2038), cloud: 0.35, night: 1, glow: 1,
    gradeHi: lin(0.96, 1.0, 1.10), gradeSh: lin(0.90, 0.97, 1.13), sat: 0.96, vig: 0.26, shaft: 0, flare: 0, fogSun: 0,
  },
};
const MOON = dirFrom(140, 38);

/** Owns the sun / moon light, hemisphere light, fog, exposure, sky uniforms and the lamp glow; eases between presets. */
export class TimeOfDay {
  constructor({ scene, renderer, sky, sunLight, hemi, lampsPos, pointLights, glowPoints, onEnv }) {
    Object.assign(this, { scene, renderer, sky, sunLight, hemi, lampsPos, pointLights, glowPoints, onEnv });
    this.name = 'dusk';
    this.cur = this._clone(TOD.dusk);
    this.sunDir = dirFrom(TOD.dusk.sunAz, TOD.dusk.sunEl);
    this.lightDir = this.sunDir.clone();
    this.moving = false;
    this.envDirty = true;
    this.envTimer = 0;
    this.lampTimer = 0;
    this.applyNow();
  }

  _clone(p) {
    const o = {};
    for (const k in p) o[k] = p[k] && p[k].isColor ? p[k].clone() : p[k];
    return o;
  }

  set(name, immediate = false) {
    if (!TOD[name]) return;
    this.name = name;
    this.target = TOD[name];
    if (immediate) {
      this.cur = this._clone(TOD[name]);
      this.applyNow();
      this.envDirty = true;
    } else {
      this.moving = true;
    }
  }

  get night() {
    return this.cur.night;
  }

  applyNow() {
    const s = this.cur;
    this.sunDir.copy(dirFrom(s.sunAz, s.sunEl));
    const sunUp = THREE.MathUtils.smoothstep(s.sunEl, -6, 6);
    this.lightDir.copy(this.sunDir).lerp(MOON, 1 - sunUp).normalize();
    this.sunLight.color.copy(s.lightColor);
    this.sunLight.intensity = s.lightI;
    this.hemi.color.copy(s.hemiSky);
    this.hemi.groundColor.copy(s.hemiGround);
    this.hemi.intensity = s.hemiI;
    this.scene.fog.color.copy(s.fog);
    this.scene.fog.density = s.fogD;
    this.scene.environmentIntensity = s.envI;
    this.renderer.toneMappingExposure = s.exposure;
    const u = this.sky.material.uniforms;
    u.sunDir.value.copy(this.sunDir);
    u.moonDir.value.copy(MOON);
    u.zen.value.copy(s.zen);
    u.mid.value.copy(s.mid);
    u.hor.value.copy(s.hor);
    u.uCloud.value = s.cloud;
    u.uSunGlow.value = sunUp;
    U.uNight.value = s.night;
    // fog in-scattering colour (warm at a low sun) and sea glitter follow the sun's height
    const low = 1 - THREE.MathUtils.smoothstep(s.sunEl, 10, 40);
    U.uSunCol.value.set(1.0, 0.95 - 0.35 * low, 0.85 - 0.55 * low).multiplyScalar(s.fogSun * sunUp);
    U.uGlit.value = sunUp * (1 - s.night);
    if (this.glowPoints) {
      this.glowPoints.material.opacity = Math.max(0, s.glow) * 0.7;
      this.glowPoints.userData.halo.opacity = Math.max(0, s.glow) * 0.16;
    }
  }

  update(dt, player) {
    if (this.moving) {
      const k = 1 - Math.exp(-dt * 1.7);
      const t = this.target;
      const s = this.cur;
      let diff = 0;
      for (const key in t) {
        if (t[key].isColor) {
          s[key].lerp(t[key], k);
          diff += Math.abs(s[key].r - t[key].r) + Math.abs(s[key].g - t[key].g) + Math.abs(s[key].b - t[key].b);
        } else {
          s[key] += (t[key] - s[key]) * k;
          diff += Math.abs(s[key] - t[key]) * (key === 'sunAz' || key === 'sunEl' ? 0.02 : 1);
        }
      }
      this.applyNow();
      if (diff < 0.004) {
        this.moving = false;
        this.cur = this._clone(t);
        this.applyNow();
        this.envDirty = true;
      }
    }
    if (this.envDirty && !this.moving) {
      this.envTimer += dt;
      if (this.envTimer > 0.2) {
        this.envTimer = 0;
        this.envDirty = false;
        this.onEnv?.();
      }
    }
    // the few nearest street lamps get real point lights at night
    this.lampTimer -= dt;
    if (this.lampTimer <= 0 && this.pointLights.length) {
      this.lampTimer = 0.4;
      const n = this.cur.night;
      const list = this.lampsPos
        .map((p) => ({ p, d: (p[0] - player.x) ** 2 + (p[2] - player.z) ** 2 }))
        .sort((a, b) => a.d - b.d);
      this.pointLights.forEach((L, i) => {
        const e = list[i];
        if (!e) {
          L.intensity = 0;
          return;
        }
        L.position.set(e.p[0], e.p[1] - 0.3, e.p[2]);
        L.intensity = n * 22;
      });
    }
  }
}

/** additive glow sprites at every lamp head (visible at dusk / night) */
export function makeLampGlow(lampsPos) {
  const cv = document.createElement('canvas');
  cv.width = cv.height = 64;
  const g = cv.getContext('2d');
  const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, 'rgba(255,214,150,1)');
  grd.addColorStop(0.25, 'rgba(255,190,110,0.55)');
  grd.addColorStop(1, 'rgba(255,170,80,0)');
  g.fillStyle = grd;
  g.fillRect(0, 0, 64, 64);
  const tex = new THREE.CanvasTexture(cv);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(lampsPos.flat(), 3));
  const mat = new THREE.PointsMaterial({ map: tex, size: 2.4, sizeAttenuation: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0, fog: false });
  const flicker = (m) => {
    m.customProgramCacheKey = () => 'lampglow';
    m.onBeforeCompile = (shader) => {
      shader.uniforms.uTime = U.uTime;
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', '#include <common>\nuniform float uTime;')
        .replace('#include <fog_vertex>', 'gl_PointSize *= 0.93 + 0.07 * sin(uTime * 6.5 + position.x * 3.1 + position.z * 5.3) * sin(uTime * 2.3 + position.x * 1.7);\n#include <fog_vertex>');
    };
  };
  flicker(mat);
  const pts = new THREE.Points(geo, mat);
  pts.frustumCulled = false;
  const haloMat = new THREE.PointsMaterial({ map: tex, size: 9, sizeAttenuation: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0, fog: false });
  flicker(haloMat);
  const halo = new THREE.Points(geo, haloMat);
  halo.frustumCulled = false;
  pts.add(halo);
  pts.userData.halo = haloMat;
  return pts;
}
