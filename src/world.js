import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { makeSky } from './sky.js';
import { patchBuildingWall, patchTerrain, patchAsphalt, patchDeck, farLandMaterial } from './fx.js';

const BASE = import.meta.env.BASE_URL;

export function makeLoaders() {
  const draco = new DRACOLoader();
  draco.setDecoderPath(`${BASE}draco/`);
  const gltf = new GLTFLoader();
  gltf.setDRACOLoader(draco);
  return gltf;
}

/** Environment map from the same procedural sky (so reflections match the current light): PMREM prefiltered, used as scene.environment.
 *  `source` is the visible sky mesh, its uniform values are copied.  Returns the render target (dispose it when replaced). */
export function makeEnvironment(renderer, source) {
  const envScene = new THREE.Scene();
  const sky = makeSky(false);
  sky.scale.setScalar(50);
  for (const k of ['sunDir', 'moonDir', 'zen', 'mid', 'hor']) sky.material.uniforms[k].value.copy(source.material.uniforms[k].value);
  sky.material.uniforms.uCloud.value = source.material.uniforms.uCloud.value;
  sky.material.uniforms.uSunGlow.value = source.material.uniforms.uSunGlow.value;
  envScene.add(sky);
  const pmrem = new THREE.PMREMGenerator(renderer);
  const rt = pmrem.fromScene(envScene, 0.02);
  pmrem.dispose();
  sky.geometry.dispose();
  sky.material.dispose();
  return rt;
}

/** PBR pass over the glTF materials that Blender exported: keep them physically plausible and give reflective ones the environment. */
export function tunePBR(root) {
  root.traverse((o) => {
    if (!o.isMesh) return;
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    for (const m of mats) {
      if (!m || !m.isMeshStandardMaterial || m.userData.tuned) continue;
      m.userData.tuned = true;
      m.roughness = Math.max(0.32, m.roughness);
      if (m.metalness > 0.5) {
        m.metalness = Math.min(m.metalness, 0.75);
        m.envMapIntensity = 1.4;
      } else if (m.transparent) {
        m.envMapIntensity = 1.6;
        m.roughness = Math.min(m.roughness, 0.12);
        m.depthWrite = false;
      } else {
        m.envMapIntensity = 0.7;
      }
      if (m.name === 'W_MAT_Rail_Shiny') {
        // polished rail heads catch the low sun and the sky
        m.metalness = 0.92;
        m.roughness = 0.2;
        m.envMapIntensity = 2.0;
      }
    }
  });
}

let farMat = null;

/** Shadow flags + the per-material shader patches (window grid, terrain / road grain, hazy far land) for the current quality preset. */
export function styleWorld(root, preset) {
  if (!farMat) farMat = farLandMaterial();
  root.traverse((o) => {
    if (!o.isMesh) return;
    if (o.name.includes('FarLand')) {
      o.castShadow = false;
      o.receiveShadow = false;
      o.material = farMat;
      return;
    }
    o.castShadow = true;
    o.receiveShadow = true;
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    for (const m of mats) {
      if (m.name === 'W_MAT_Building_Wall#w') patchBuildingWall(m, preset.detail, preset.bump);
      else if (m.name === 'W_MAT_Terrain#w') patchTerrain(m, preset.detail, preset.bump);
      else if (m.name === 'W_MAT_Asphalt_Real' || m.name === 'W_MAT_Asphalt_Patch') patchAsphalt(m, preset.detail, preset.bump);
      else if (m.name === 'W_MAT_Platform_Top') patchDeck(m, 'top', preset.bump);
      else if (m.name === 'W_MAT_Tactile_Yellow') patchDeck(m, 'yellow', preset.bump);
      else if (m.name === 'W_MAT_Wood_Post' || m.name === 'W_MAT_Wood_Dark') patchDeck(m, 'wood', preset.bump);
    }
  });
}
