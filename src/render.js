import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

/** WebGL renderer + optional composer (MSAA render target, bloom, output pass) + a frame-time governor that adapts the pixel ratio. */
export class Renderer {
  constructor(canvas, preset, { govern = true } = {}) {
    this.canvas = canvas;
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
    const p = this.preset;
    if (!p.bloom && !p.msaa) return;
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
    this.composer.addPass(new OutputPass());
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
