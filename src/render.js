import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { SMAAPass } from 'three/examples/jsm/postprocessing/SMAAPass.js';
import { GTAOPass } from 'three/examples/jsm/postprocessing/GTAOPass.js';
import { BokehPass } from 'three/examples/jsm/postprocessing/BokehPass.js';
import { AfterimagePass } from 'three/examples/jsm/postprocessing/AfterimagePass.js';
import { makeAtmosPass, makeGradePass } from './atmos.js';

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

/** WebGL renderer + optional composer (MSAA render target, bloom, SSAO, DOF, atmosphere, SMAA, chromatic-aberration/grain, motion blur)
 *  + a frame-time governor that adapts the pixel ratio. */
export class Renderer {
  constructor(canvas, preset, { govern = true, scene, camera } = {}) {
    this.canvas = canvas;
    this.scene = scene;
    this.camera = camera;
    this.gl = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance', preserveDrawingBuffer: false });
    this.gl.outputColorSpace = THREE.SRGBColorSpace; // linear lighting -> sRGB display
    this.gl.toneMapping = THREE.ACESFilmicToneMapping; // filmic roll-off
    this.gl.shadowMap.enabled = true; // real-time sun / moon shadows
    this.gl.shadowMap.type = THREE.PCFSoftShadowMap; // soft edges
    this.govern = govern;
    this.ema = 16;
    this.acc = 0;
    this.preset = preset;
    this.baseDpr = 1;
    this.dpr = 1;
    this.composer = null;
    this.motionBlurOn = false;
    this.apply(preset);
  }

  apply(preset) {
    this.preset = preset;
    this.baseDpr = Math.min(window.devicePixelRatio || 1, preset.dpr);
    this.dpr = this.baseDpr;
    this.gl.setPixelRatio(this.dpr);
    this.gl.setSize(innerWidth, innerHeight);
    this.buildComposer();
  }

  buildComposer() {
    if (this.composer) {
      this.composer.dispose?.();
      this.composer = null;
    }
    this.bloom = null;
    this.atmos = null;
    this.ssao = null;
    this.dof = null;
    this.afterimage = null;
    const p = this.preset;
    const size = this.gl.getDrawingBufferSize(new THREE.Vector2());
    const rt = new THREE.WebGLRenderTarget(size.x, size.y, { type: THREE.HalfFloatType, samples: p.msaa, colorSpace: THREE.LinearSRGBColorSpace });
    this.composer = new EffectComposer(this.gl, rt);
    this.composer.setPixelRatio(this.dpr);
    this.composer.setSize(innerWidth, innerHeight);
    this.renderPass = new RenderPass(new THREE.Scene(), new THREE.PerspectiveCamera());
    this.composer.addPass(this.renderPass);
    if (p.bloom) {
      this.bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth * 0.5, innerHeight * 0.5), 0.28, 0.6, 1.25);
      this.composer.addPass(this.bloom);
    }
    if (p.ssao && this.scene && this.camera) {
      this.ssao = new GTAOPass(this.scene, this.camera, size.x, size.y, undefined, { radius: 2, distanceExponent: 1, thickness: 1 });
      this.ssao.output = GTAOPass.OUTPUT.Default;
      this.ssao.blendIntensity = 0.85;
      this.gtaoBox = new THREE.Box3();
      this.ssao.setSceneClipBox(this.gtaoBox);
      this.composer.addPass(this.ssao);
    }
    if (p.atmos) {
      this.atmos = makeAtmosPass(); // shafts / flare / grade / vignette (medium, high, ultra)
      this.composer.addPass(this.atmos);
    }
    if (p.dof && this.scene && this.camera) {
      this.dof = new BokehPass(this.scene, this.camera, { focus: 6, aperture: 0.012, maxblur: 0.006 });
      this.composer.addPass(this.dof);
    }
    if (p.smaa) this.composer.addPass(new SMAAPass(size.x, size.y));
    this.grade = makeGradePass(); // chromatic aberration + film grain: cheap enough to run on every preset
    this.composer.addPass(this.grade);
    if (p.motionBlur) {
      this.afterimage = new AfterimagePass(0.72);
      this.afterimage.enabled = this.motionBlurOn;
      this.composer.addPass(this.afterimage);
    }
    this.composer.addPass(new OutputPass());
  }

  /** ultra-only, and off by default even there: the settings toggle drives this independently of the preset. */
  setMotionBlur(on) {
    this.motionBlurOn = on;
    if (this.afterimage) this.afterimage.enabled = on;
  }

  /** keeps the GTAO pass's clip box (needed for depth precision against a 150 km far plane) centred on the player. */
  updateAoBox(center, half = 120) {
    if (!this.gtaoBox) return;
    this.gtaoBox.min.set(center.x - half, center.y - 40, center.z - half);
    this.gtaoBox.max.set(center.x + half, center.y + 60, center.z + half);
  }

  setFocus(dist) {
    if (this.dof) this.dof.uniforms.focus.value = dist;
  }

  resize() {
    this.gl.setSize(innerWidth, innerHeight);
    if (this.composer) this.composer.setSize(innerWidth, innerHeight);
    if (this.bloom) this.bloom.resolution.set(innerWidth * 0.5, innerHeight * 0.5);
  }

  setDpr(d) {
    this.dpr = d;
    this.gl.setPixelRatio(d);
    if (this.composer) {
      this.composer.setPixelRatio(d);
      this.composer.setSize(innerWidth, innerHeight);
    }
    if (this.bloom) this.bloom.resolution.set(innerWidth * 0.5, innerHeight * 0.5);
  }

  /** call once per frame with the raw frame time (s) */
  tick(dt) {
    if (!this.govern) return;
    this.ema += (dt * 1000 - this.ema) * 0.08;
    this.acc += dt;
    if (this.acc < 1.2) return;
    this.acc = 0;
    if (this.ema > 24 && this.dpr > this.baseDpr * 0.55) this.setDpr(Math.max(0.6, this.dpr - 0.15));
    else if (this.ema < 13.5 && this.dpr < this.baseDpr - 0.01) this.setDpr(Math.min(this.baseDpr, this.dpr + 0.1));
  }

  render(scene, camera) {
    if (this.composer) {
      this.renderPass.scene = scene;
      this.renderPass.camera = camera;
      this.composer.render();
    } else {
      this.gl.render(scene, camera);
    }
  }
}
