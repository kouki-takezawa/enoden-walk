import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { makeSky } from './sky.js';
import { patchBuildingWall, patchTerrain, patchAsphalt, patchDeck, patchGeneric, patchSkin, patchHair, patchFabric, farLandMaterial } from './fx.js';

// Phase N0: generic weathering for every other prop/building material that doesn't need bespoke logic (see
// patchGeneric in fx.js). 'large' = big flat surfaces (roofs, whole walls), 'small' = poles/fences/benches, which
// need a higher spatial frequency for the noise to actually read as detail at their size.
const GENERIC_LARGE = { freq: 0.9, amp: 0.20, bumpFreq: 3.5, bumpAmp: 0.22 };
const GENERIC_SMALL = { freq: 2.6, amp: 0.24, bumpFreq: 9.0, bumpAmp: 0.16 };
const GENERIC_MATS = {
  'W_MAT_Building_Roof#w': GENERIC_LARGE,
  'W_MAT_Balcony#w': GENERIC_LARGE,
  W_MAT_Wall_Plaster: GENERIC_LARGE,
  W_MAT_Block_Wall: GENERIC_LARGE,
  W_MAT_Stone_House: GENERIC_LARGE,
  W_MAT_Siding_Corr: GENERIC_LARGE,
  W_MAT_Slate_Roof: GENERIC_LARGE,
  W_MAT_Platform_Wall: GENERIC_LARGE,
  W_MAT_Revetment: GENERIC_LARGE,
  W_MAT_Stone_Light: GENERIC_SMALL,
  W_MAT_Stone_Black: GENERIC_SMALL,
  W_MAT_Concrete: GENERIC_SMALL,
  W_MAT_Concrete_Pole: GENERIC_SMALL,
  W_MAT_Steel_Grey: GENERIC_SMALL,
  W_MAT_Steel_Galv: GENERIC_SMALL,
  W_MAT_Rail_Rust: GENERIC_SMALL,
  W_MAT_Wood_Fence: GENERIC_SMALL,
  W_MAT_Wood_Bench: GENERIC_SMALL,
};

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
      else if (GENERIC_MATS[m.name]) patchGeneric(m, preset.detail, preset.bump, GENERIC_MATS[m.name]);
    }
  });
}

/** Character shader patches (skin / hair / fabric): same "port the Blender pattern to JS" trick as styleWorld,
 *  since the web export flattens the character's rich procedural materials (subsurface skin, per-strand hair
 *  tint, fabric sheen) to flat colours the same way it does for the world's materials. */
export function styleCharacter(model, preset) {
  model.traverse((o) => {
    if (!o.isMesh && !o.isSkinnedMesh) return;
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    for (const m of mats) {
      if (m.name === 'W_MAT_Skin_Body' || m.name === 'W_MAT_Skin_Head' || m.name === 'W_MAT_Skin_Head_lips' || m.name === 'W_Woody_Head' || m.name === 'W_Woody_Skin') patchSkin(m, preset.detail, preset.bump);
      else if (m.name === 'W_MAT_Hair') patchHair(m, preset.detail);
      else if (m.name === 'W_MAT_Tee' || m.name === 'W_MAT_TeeRib' || m.name === 'W_MAT_Chino') patchFabric(m, preset.detail, preset.bump);
    }
  });
}
