// Quality presets, persisted user settings and the (ja / en) strings.
const KEY = 'enoden-walk.settings.v1';

export const PRESETS = {
  low: { dpr: 1.0, shadow: 1024, shadowRange: 34, bloom: false, msaa: 0, leafCards: false, detail: 0, clouds: false, wind: false, pointLights: 1, seaDepth: false, glow: true },
  medium: { dpr: 1.25, shadow: 2048, shadowRange: 50, bloom: true, msaa: 0, leafCards: true, detail: 1, clouds: true, wind: true, pointLights: 2, seaDepth: true, glow: true },
  high: { dpr: 1.75, shadow: 4096, shadowRange: 70, bloom: true, msaa: 4, leafCards: true, detail: 2, clouds: true, wind: true, pointLights: 4, seaDepth: true, glow: true },
};

export const DEFAULTS = {
  quality: 'auto', // auto | low | medium | high
  time: 'dusk', // day | dusk | night
  volume: 0.8,
  muted: false,
  lang: /^ja/i.test(navigator.language || 'ja') ? 'ja' : 'en',
  sens: 1.0,
  invertY: false,
  viewMode: 'drag', // drag | right | lock
  autoCam: true,
  fps: false,
  reduceMotion: typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches,
};

export function loadSettings() {
  let s = {};
  try {
    s = JSON.parse(localStorage.getItem(KEY) || '{}');
  } catch {
    s = {};
  }
  return { ...DEFAULTS, ...s };
}

export function saveSettings(s) {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* private mode: ignore */
  }
}

/** auto preset: touch devices / weak CPUs start on low, everything else on medium (the frame-time governor adapts the resolution) */
export function autoPreset() {
  const coarse = typeof matchMedia === 'function' && matchMedia('(pointer: coarse)').matches;
  const cores = navigator.hardwareConcurrency || 4;
  if (coarse || cores <= 4) return 'low';
  return cores >= 12 ? 'high' : 'medium';
}

const STR = {
  ja: {
    title: '江ノ電 鎌倉高校前 散歩',
    subtitle: '夕暮れの1号踏切と、相模湾の見える丘の街を歩こう',
    start: '散歩をはじめる',
    loading: '読み込み中…',
    assembling: '街を組み立て中…',
    ready: '準備できました',
    failed: '読み込みに失敗しました',
    where_default: '鎌倉高校前 周辺',
    where_near: '{name} 付近',
    help: '操作ガイド',
    settings: '設定',
    spots: '名所へ移動',
    photo: '写真モード',
    share: '共有',
    copied: 'リンクをコピーしました',
    close: '閉じる',
    time: '時刻',
    day: '昼',
    dusk: '夕方',
    night: '夜',
    quality: '画質',
    q_auto: '自動',
    q_low: '低',
    q_medium: '中',
    q_high: '高',
    volume: '音量',
    mute: 'ミュート',
    sens: '視点の感度',
    invertY: '上下を反転',
    viewMode: '視点操作',
    vm_drag: '左ドラッグ',
    vm_right: '右ドラッグ',
    vm_lock: 'マウス固定（クリックで開始）',
    autoCam: '移動時に自動で背後へ回る',
    fps: 'FPS を表示',
    lang: '言語',
    reduce: '動きを抑える',
    moveKeys: '移動',
    runKey: '走る',
    sprintKey: '全力',
    jumpKey: 'ジャンプ',
    viewKey: '視点',
    boardKey: '乗る / 降りる',
    soundKey: '音',
    photoKey: '写真モード',
    helpKey: 'このガイド',
    recenterKey: '視点を背後へ',
    gamepad: 'ゲームパッド: 左スティック 移動 / 右スティック 視点 / A ジャンプ / RT 走る / X 全力 / Y 乗る',
    touchHint: 'スマホ: 左側をスライドで移動、右側をドラッグで視点、2本指で拡大縮小',
    nextTrain: '次の電車',
    east: '藤沢方面',
    west: '鎌倉方面',
    in: 'あと {s} 秒',
    arriving: '駅に到着中',
    dwell: '駅に停車中',
    passing: '通過中',
    boardPrompt: 'E で乗車',
    alightPrompt: 'E で降りる',
    riding: '乗車中',
    boarded: '乗車しました。車窓の景色を楽しもう',
    alighted: 'ホームに降りました',
    alarm: 'カンカンカン… 電車が来ます',
    clearCrossing: '踏切から出てください',
    hit: '電車に注意！ 踏切の外へ戻りました',
    start_msg: '散歩をはじめましょう',
    sound_on: '音: オン',
    sound_off: '音: オフ',
    photoFov: '画角',
    photoHide: '人物を隠す',
    capture: '撮影して保存',
    saved: '写真を保存しました',
    exitPhoto: '写真モードを終了',
    quality_now: '画質: {q}',
    credit: '地形・建物: 国土交通省 Project PLATEAU（CC BY 4.0）／ 道路・線路: © OpenStreetMap contributors（ODbL）<br>3Dモデル（風景・電車・人物）は Blender で手続き生成した非公式の創作物です。',
    minimap: '地図',
    helpShort: 'WASD 移動 ・ Shift 走る ・ Space ジャンプ ・ E 乗る ・ ？ ガイド',
    north: '北',
  },
  en: {
    title: 'Enoden Kamakura-Koko-Mae Walk',
    subtitle: 'Stroll around the famous level crossing and the hills above Sagami Bay',
    start: 'Start walking',
    loading: 'Loading…',
    assembling: 'Building the town…',
    ready: 'Ready',
    failed: 'Failed to load',
    where_default: 'Kamakura-Koko-Mae area',
    where_near: 'Near {name}',
    help: 'Controls',
    settings: 'Settings',
    spots: 'Go to a spot',
    photo: 'Photo mode',
    share: 'Share',
    copied: 'Link copied',
    close: 'Close',
    time: 'Time of day',
    day: 'Day',
    dusk: 'Dusk',
    night: 'Night',
    quality: 'Quality',
    q_auto: 'Auto',
    q_low: 'Low',
    q_medium: 'Medium',
    q_high: 'High',
    volume: 'Volume',
    mute: 'Mute',
    sens: 'Look sensitivity',
    invertY: 'Invert vertical look',
    viewMode: 'Camera control',
    vm_drag: 'Left drag',
    vm_right: 'Right drag',
    vm_lock: 'Mouse lock (click to start)',
    autoCam: 'Swing behind me when walking',
    fps: 'Show FPS',
    lang: 'Language',
    reduce: 'Reduce motion',
    moveKeys: 'Move',
    runKey: 'Run',
    sprintKey: 'Sprint',
    jumpKey: 'Jump',
    viewKey: 'Look',
    boardKey: 'Board / alight',
    soundKey: 'Sound',
    photoKey: 'Photo mode',
    helpKey: 'This guide',
    recenterKey: 'Camera behind me',
    gamepad: 'Gamepad: left stick move / right stick look / A jump / RT run / X sprint / Y board',
    touchHint: 'Touch: slide on the left to move, drag on the right to look, pinch to zoom',
    nextTrain: 'Next train',
    east: 'for Fujisawa',
    west: 'for Kamakura',
    in: 'in {s} s',
    arriving: 'arriving',
    dwell: 'stopped at the station',
    passing: 'passing',
    boardPrompt: 'E: board',
    alightPrompt: 'E: get off',
    riding: 'Riding',
    boarded: 'You boarded. Enjoy the view from the window',
    alighted: 'You got off at the platform',
    alarm: 'Ding-ding-ding… a train is coming',
    clearCrossing: 'Please leave the crossing',
    hit: 'Watch out for trains! Moved out of the crossing',
    start_msg: "Let's take a walk",
    sound_on: 'Sound: on',
    sound_off: 'Sound: off',
    photoFov: 'Field of view',
    photoHide: 'Hide the character',
    capture: 'Capture & save',
    saved: 'Photo saved',
    exitPhoto: 'Exit photo mode',
    quality_now: 'Quality: {q}',
    credit: 'Terrain & buildings: MLIT Project PLATEAU (CC BY 4.0) / roads & rails: © OpenStreetMap contributors (ODbL)<br>All 3D models (scenery, train, character) are unofficial procedurally generated creations made with Blender.',
    minimap: 'Map',
    helpShort: 'WASD move · Shift run · Space jump · E board · ? guide',
    north: 'N',
  },
};

export function makeT(getLang) {
  return (key, vars) => {
    let s = (STR[getLang()] && STR[getLang()][key]) || STR.ja[key] || key;
    if (vars) for (const k in vars) s = s.replace(`{${k}}`, vars[k]);
    return s;
  };
}
