// HUD, menus, minimap, photo mode, i18n.  Pure DOM; main.js feeds it the state every frame.
import { SEA_BLOCK } from './ground.js';
import { ICONS, timeIcon } from './icons.js';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

export class UI {
  constructor({ t, settings, hooks, touch = false }) {
    this.t = t;
    this.s = settings;
    this.hooks = hooks;
    this.touch = touch;
    this.meta = { poi: [] };
    this.ground = null;
    this.msgTimer = 0;
    this.msgBusy = false;
    this.msgQueue = [];
    this.lastWhere = '';
    this.lastTrain = '';
    this.mapBase = null;
    this.mapOverlayOpen = false;
    this.modalOpen = null;
    this.photo = false;
    this.fpsAcc = 0;
    this.fpsFrames = 0;
    this._wire();
    this.applyLang();
  }

  /** the world data arrives after the title panel is already interactive */
  attach(meta, ground) {
    this.meta = meta;
    this.ground = ground;
    this.buildMinimap();
  }

  // ---------------------------------------------------------------------------------------------- i18n
  applyLang() {
    const t = this.t;
    document.documentElement.lang = this.s.lang;
    document.title = t('title');
    document.querySelectorAll('[data-i18n]').forEach((e) => (e.textContent = t(e.dataset.i18n)));
    document.querySelectorAll('[data-i18n-html]').forEach((e) => (e.innerHTML = t(e.dataset.i18nHtml)));
    document.querySelectorAll('.langsw button').forEach((b) => b.classList.toggle('on', b.dataset.lang === this.s.lang));
    $('helpbody').innerHTML = this.helpHTML();
    $('bJump').textContent = t('jumpKey');
    $('help').textContent = t('helpShort');
    for (const [id, key] of [['bTime', 'time'], ['bSpots', 'spots'], ['bPhoto', 'photo'], ['bSet', 'settings'], ['bHelp', 'help']]) $(id).setAttribute('aria-label', t(key));
    $('bSpots').innerHTML = ICONS.pin;
    $('bPhoto').innerHTML = ICONS.camera;
    $('bSet').innerHTML = ICONS.gear;
    $('bHelp').innerHTML = ICONS.help;
    $('bBoard').innerHTML = ICONS.train;
    $('trainicon').innerHTML = ICONS.train;
    $('mapN').textContent = t('north');
    $('bGoPf').innerHTML = `${ICONS.train}<span>${esc(t('go_platform'))}</span>`;
    $('bCall').innerHTML = `${ICONS.bell}<span>${esc(t('call_train'))}</span>`;
    $('navStop').setAttribute('aria-label', t('nav_stop'));
    $('navStop').title = t('nav_stop');
    $('mapwrap').title = t('map_hint');
    $('mapwrap').setAttribute('aria-label', t('map_hint'));
    $('mapOverlayClose').setAttribute('aria-label', t('close'));
    this.lastNav = '';
    this.lastNavAuto = undefined;
    this.lastWhere = '';
    this.lastTrain = '';
    if (this.modalOpen) this.openModal(this.modalOpen);
  }

  helpHTML() {
    const t = this.t;
    const row = (k, d) => `<div class="krow"><span>${k}</span><span>${d}</span></div>`;
    const mapRow = row(t('mapKey'), t('mapKeyDesc'));
    const keyboardRows = [
      row('<kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd> / <kbd>↑</kbd><kbd>←</kbd><kbd>↓</kbd><kbd>→</kbd>', t('moveKeys')),
      row('<kbd>Shift</kbd>', t('runKey')),
      row('<kbd>R</kbd>', t('sprintKey')),
      row('<kbd>Space</kbd>', t('jumpKey')),
      row('<kbd>F</kbd>', t('autowalkKey')),
      row(this.s.lang === 'ja' ? 'ドラッグ / ホイール' : 'Drag / wheel', t('viewKey')),
      row('<kbd>C</kbd>', t('recenterKey')),
      row('<kbd>E</kbd>', t('boardKey')),
      row('<kbd>T</kbd> / <kbd>P</kbd> / <kbd>M</kbd> / <kbd>Tab</kbd>', `${t('time')} / ${t('photoKey')} / ${t('soundKey')} / ${t('spots')}`),
      row('<kbd>H</kbd> / <kbd>？</kbd>', t('helpKey')),
    ].join('');
    // touch devices care about the touch hint and the minimap tap first; keyboard/gamepad bindings are secondary, tucked into a disclosure
    if (this.touch) {
      return [
        `<div class="touchhint">${esc(t('touchHint'))}</div>`,
        mapRow,
        `<details class="kbdetails"><summary>${this.s.lang === 'ja' ? 'キーボード / ゲームパッドの操作' : 'Keyboard / gamepad controls'}</summary>${keyboardRows}<div class="dim">${esc(t('gamepad'))}</div></details>`,
      ].join('');
    }
    return [keyboardRows, mapRow, `<div class="dim">${esc(t('gamepad'))}<br>${esc(t('touchHint'))}</div>`].join('');
  }

  // ---------------------------------------------------------------------------------------------- wiring
  _wire() {
    const h = this.hooks;
    document.querySelectorAll('.langsw button').forEach((b) =>
      b.addEventListener('click', () => {
        this.s.lang = b.dataset.lang;
        h.changed('lang');
        this.applyLang();
      }),
    );
    $('bHelp').onclick = () => this.openModal('help');
    $('bSet').onclick = () => this.openModal('settings');
    $('bSpots').onclick = () => this.openModal('spots');
    $('bPhoto').onclick = () => h.photo();
    $('bTime').onclick = () => h.cycleTime();
    $('bBoard').addEventListener('pointerdown', (e) => {
      e.preventDefault();
      h.board();
    });
    $('mapwrap').onclick = (e) => {
      if (this._mapLongPressed) {
        this._mapLongPressed = false;
        return;
      }
      const r = $('mapwrap').getBoundingClientRect();
      const u = ((e.clientX - r.left) / r.width) * 176;
      const v = ((e.clientY - r.top) / r.height) * 176;
      if ((u - 88) ** 2 + (v - 88) ** 2 < 86 * 86) h.mapTap(u, v);
    };
    // long-press the minimap to open the enlarged overlay (a plain tap still walks there, as before)
    let mapPressTimer = 0;
    let mapPressStart = null;
    $('mapwrap').addEventListener('pointerdown', (e) => {
      mapPressStart = { x: e.clientX, y: e.clientY };
      clearTimeout(mapPressTimer);
      mapPressTimer = setTimeout(() => {
        this._mapLongPressed = true;
        this.toggleMapOverlay(true);
      }, 480);
    });
    $('mapwrap').addEventListener('pointermove', (e) => {
      if (mapPressStart && Math.hypot(e.clientX - mapPressStart.x, e.clientY - mapPressStart.y) > 10) clearTimeout(mapPressTimer);
    });
    $('mapwrap').addEventListener('pointerup', () => clearTimeout(mapPressTimer));
    $('mapwrap').addEventListener('pointercancel', () => clearTimeout(mapPressTimer));
    $('mapOverlayClose').onclick = () => this.toggleMapOverlay(false);
    $('mapOverlay').onclick = (e) => {
      if (e.target.id === 'mapOverlay') this.toggleMapOverlay(false);
    };
    $('bGoPf').onclick = () => h.goPlatform();
    $('bCall').onclick = () => h.callTrain();
    $('navAuto').onclick = () => h.navAuto();
    $('navStop').onclick = () => h.navStop();
    addEventListener('keydown', (e) => {
      if (e.code === 'Escape' && this.modalOpen) this.closeModal();
    });
  }

  // ---------------------------------------------------------------------------------------------- messages / prompts
  /** messages queue (up to 3 deep) instead of overwriting one another when several land at once */
  showMsg(text, ms = 2600) {
    if (this.msgBusy) {
      if (this.msgQueue.length < 3) this.msgQueue.push({ text, ms });
      return;
    }
    this._displayMsg(text, ms);
  }

  _displayMsg(text, ms) {
    const el = $('msg');
    this.msgBusy = true;
    el.textContent = text;
    el.classList.add('show');
    clearTimeout(this.msgTimer);
    this.msgTimer = setTimeout(() => {
      el.classList.remove('show');
      this.msgBusy = false;
      const next = this.msgQueue.shift();
      if (next) setTimeout(() => this._displayMsg(next.text, next.ms), 250);
    }, ms);
  }

  /** text: prompt line (null hides everything); showText false on touch devices where only the round button is shown */
  setPrompt(text, showText = true) {
    const el = $('prompt');
    if (text && showText) {
      el.textContent = text;
      el.classList.remove('hidden');
    } else el.classList.add('hidden');
    $('bBoard').classList.toggle('hidden', !text);
  }

  setWhere(name, dist) {
    const txt = name && dist < 90 ? this.t('where_near', { name }) : this.t('where_default');
    if (txt !== this.lastWhere) {
      $('where').textContent = txt;
      this.lastWhere = txt;
    }
  }

  setQuick(showPlatform, showCall) {
    $('bGoPf').classList.toggle('hidden', !showPlatform);
    $('bCall').classList.toggle('hidden', !showCall);
  }

  /** info: null hides the bar; otherwise {name, m, angle (rad, clockwise from screen-up), auto} */
  setNav(info) {
    const bar = $('navbar');
    if (!info) {
      bar.classList.add('hidden');
      this.navShown = false;
      return;
    }
    if (!this.navShown) {
      bar.classList.remove('hidden');
      this.navShown = true;
    }
    $('navArrow').style.transform = `rotate(${info.angle}rad)`;
    const txt = this.t('nav_to', { name: info.name, m: Math.max(0, Math.round(info.m)) });
    if (txt !== this.lastNav) {
      $('navText').textContent = txt;
      this.lastNav = txt;
    }
    if (this.lastNavAuto !== info.auto) {
      this.lastNavAuto = info.auto;
      $('navAuto').innerHTML = `${info.auto ? ICONS.hand : ICONS.footprints}<span>${esc(this.t(info.auto ? 'nav_manual' : 'nav_auto'))}</span>`;
    }
  }

  setTimeIcon(name) {
    $('bTime').innerHTML = timeIcon(name);
    document.body.dataset.tod = name; // lets the HUD colors shift a little for dusk/night
  }

  setTrain(info, riding) {
    const t = this.t;
    let txt;
    const dirTxt = info.dir > 0 ? t('east') : t('west');
    if (riding) txt = `${t('riding')} — ${dirTxt}`;
    else if (info.state === 'wait') txt = `${t('nextTrain')}: ${dirTxt} ${t('in', { s: info.s })}`;
    else if (info.state === 'dwell') txt = `${dirTxt}: ${t('dwell')}${info.s ? ` (${t('in', { s: info.s })})` : ''}`;
    else if (info.state === 'arriving') txt = `${dirTxt}: ${t('arriving')}`;
    else txt = `${dirTxt}: ${t('passing')}`;
    if (txt !== this.lastTrain) {
      $('traintext').textContent = txt;
      this.lastTrain = txt;
    }
  }

  stick(active, x, y, dx, dy) {
    const s = $('stick');
    s.classList.toggle('active', active);
    if (active) {
      s.style.left = `${x - 64}px`;
      s.style.top = `${y - 64}px`;
      s.style.bottom = 'auto';
      $('knob').style.transform = `translate(${dx}px, ${dy}px)`;
    } else {
      s.style.left = s.style.top = s.style.bottom = '';
      $('knob').style.transform = '';
    }
  }

  fps(dt) {
    if (!this.s.fps) return;
    this.fpsAcc += dt;
    this.fpsFrames++;
    if (this.fpsAcc >= 0.5) {
      $('fps').textContent = `${Math.round(this.fpsFrames / this.fpsAcc)} fps`;
      this.fpsAcc = 0;
      this.fpsFrames = 0;
    }
  }

  fade(fn) {
    const f = $('fade');
    f.classList.add('on');
    setTimeout(() => {
      fn();
      setTimeout(() => f.classList.remove('on'), 80);
    }, 220);
  }

  // ---------------------------------------------------------------------------------------------- minimap
  buildMinimap() {
    const g = this.ground;
    const cv = document.createElement('canvas');
    cv.width = g.nx;
    cv.height = g.ny;
    const ctx = cv.getContext('2d');
    const img = ctx.createImageData(g.nx, g.ny);
    const SURF = { 1: [78, 82, 92], 2: [186, 180, 168], 3: [126, 152, 88], 4: [222, 200, 146], 5: [128, 122, 114] };
    for (let j = 0; j < g.ny; j++) {
      for (let i = 0; i < g.nx; i++) {
        const k = j * g.nx + i;
        const h = g.h[k];
        const o = ((g.ny - 1 - j) * g.nx + i) * 4; // north up
        let c;
        if (h !== h) c = [104, 92, 86]; // building footprint
        else if (h < SEA_BLOCK) c = [70, 148, 178];
        else {
          c = SURF[g.surf[k]] || [126, 152, 88];
          const hx = g.raw(i + 1, j) - g.raw(i - 1, j);
          const hy = g.raw(i, j + 1) - g.raw(i, j - 1);
          const sh = 1 + ((hx === hx ? hx : 0) * -0.11 + (hy === hy ? hy : 0) * 0.09);
          const k2 = Math.max(0.6, Math.min(1.35, sh)) * (g.surf[k] === 3 ? 0.85 + Math.min(h, 45) / 160 : 1);
          c = c.map((v) => Math.max(0, Math.min(255, v * k2)));
          if (g.solid[k]) c = [60, 60, 60];
        }
        img.data[o] = c[0];
        img.data[o + 1] = c[1];
        img.data[o + 2] = c[2];
        img.data[o + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    this.mapBase = cv;
  }

  toggleMapOverlay(open) {
    this.mapOverlayOpen = open;
    $('mapOverlay').classList.toggle('hidden', !open);
  }

  /** draws the normal minimap, plus the enlarged overlay copy (same drawing, scaled up) while it's open */
  drawMinimap(player, yaw, train, route) {
    this._drawMapOnto($('map'), player, yaw, train, route);
    if (this.mapOverlayOpen) this._drawMapOnto($('mapBig'), player, yaw, train, route);
  }

  _drawMapOnto(cv, player, yaw, train, route) {
    if (!this.mapBase) return;
    const ctx = cv.getContext('2d');
    const g = this.ground;
    const R = 62; // cells shown around the player (radius)
    const cx = (player.x - g.x0) / g.step;
    const cy = g.ny - 1 - (-player.z - g.y0) / g.step;
    ctx.save();
    ctx.scale(cv.width / 176, cv.height / 176); // draws the same 176x176 layout, scaled to the canvas' actual backing size
    ctx.clearRect(0, 0, 176, 176);
    ctx.beginPath();
    ctx.arc(88, 88, 86, 0, Math.PI * 2);
    ctx.clip();
    ctx.fillStyle = '#3b6f8a';
    ctx.fillRect(0, 0, 176, 176);
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(this.mapBase, cx - R, cy - R, R * 2, R * 2, 0, 0, 176, 176);
    const px = (x, z) => 88 + ((x - g.x0) / g.step - cx) * (88 / R);
    const py = (x, z) => 88 + (g.ny - 1 - (-z - g.y0) / g.step - cy) * (88 / R);
    // train
    if (train && train.visible) {
      ctx.fillStyle = '#e6362b';
      const [a, b] = train.span;
      ctx.fillRect(px(a, 0), py(a, 0) - 2.5, Math.max(4, px(b, 0) - px(a, 0)), 5);
    }
    // guidance route + destination
    if (route && route.points.length) {
      ctx.strokeStyle = 'rgba(255, 190, 40, 0.95)';
      ctx.lineWidth = 3;
      ctx.setLineDash([6, 4]);
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(px(player.x, player.z), py(player.x, player.z));
      for (const p of route.points.slice(route.i)) ctx.lineTo(px(p[0], p[1]), py(p[0], p[1]));
      ctx.stroke();
      ctx.setLineDash([]);
      const tx = px(route.target[0], route.target[1]);
      const ty = py(route.target[0], route.target[1]);
      const pulse = 5 + 2.5 * Math.sin(performance.now() / 260);
      ctx.strokeStyle = '#ff9a1f';
      ctx.fillStyle = 'rgba(255, 154, 31, 0.35)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(Math.max(4, Math.min(172, tx)), Math.max(4, Math.min(172, ty)), pulse, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }
    // platform deck + its entrance ramp
    const pf = this.meta.platform;
    if (pf) {
      const x0 = px(pf.x0, 0);
      const x1 = px(pf.x1, 0);
      const y0 = py(0, -pf.y1);
      const y1 = py(0, -pf.y0);
      if (x1 > 0 && x0 < 176) {
        ctx.fillStyle = 'rgba(232, 236, 240, 0.85)';
        ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
        ctx.fillStyle = '#ff8a2b';
        ctx.beginPath();
        ctx.arc(px(pf.x0 - 2.5, 0), py(0, -(pf.y0 + pf.y1) / 2), 2.6, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    // spots
    ctx.fillStyle = '#ffffff';
    ctx.strokeStyle = '#2a2118';
    ctx.lineWidth = 1.5;
    for (const p of this.meta.poi) {
      const x = px(p.x, -p.y);
      const y = py(p.x, -p.y);
      if ((x - 88) ** 2 + (y - 88) ** 2 > 84 * 84) continue;
      ctx.beginPath();
      ctx.arc(x, y, 3.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }
    // player arrow (yaw 0 faces +z = south = canvas down; the arrow sprite points up)
    ctx.translate(88, 88);
    ctx.rotate(-yaw + Math.PI);
    ctx.fillStyle = '#ffdd33';
    ctx.strokeStyle = '#2a2118';
    ctx.beginPath();
    ctx.moveTo(0, -8);
    ctx.lineTo(6, 7);
    ctx.lineTo(0, 3.5);
    ctx.lineTo(-6, 7);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  // ---------------------------------------------------------------------------------------------- modals
  openModal(kind) {
    const t = this.t;
    const m = $('modal');
    this.modalOpen = kind;
    let body = '';
    if (kind === 'help') body = `<h2>${t('help')}</h2><div class="keys">${this.helpHTML()}</div><p class="credit">${t('credit')}</p>`;
    else if (kind === 'spots') {
      body = `<h2>${t('spots')}</h2><div class="spots">${this.meta.poi.map((p, i) => `<div class="spotrow"><button data-spot="${i}">${esc(this.s.lang === 'en' ? p.en : p.name)}</button><button data-guide="${i}" title="${esc(t('guide_btn'))}" aria-label="${esc(t('guide_btn'))}: ${esc(this.s.lang === 'en' ? p.en : p.name)}">${ICONS.compass}</button></div>`).join('')}</div>
        <div class="row"><button id="mShare">${t('share')}</button></div>`;
    } else if (kind === 'settings') {
      const sel = (id, opts, val) => `<select id="${id}">${opts.map(([v, l]) => `<option value="${v}"${v === val ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
      body = `<h2>${t('settings')}</h2>
        <label>${t('time')} ${sel('sTime', [['day', t('day')], ['dusk', t('dusk')], ['night', t('night')]], this.s.time)}</label>
        <label>${t('quality')} ${sel('sQuality', [['auto', t('q_auto')], ['low', t('q_low')], ['medium', t('q_medium')], ['high', t('q_high')], ['ultra', t('q_ultra')]], this.s.quality)}</label>
        ${this.s.quality === 'ultra' ? `<label><input id="sDof" type="checkbox" ${this.s.dof ? 'checked' : ''}> ${t('dof')}</label>` : ''}
        ${this.s.quality === 'ultra' ? `<label><input id="sMotionBlur" type="checkbox" ${this.s.motionBlur ? 'checked' : ''}> ${t('motionBlur')}</label>` : ''}
        <label>${t('volume')} <input id="sVol" type="range" min="0" max="1" step="0.05" value="${this.s.volume}"></label>
        <label><input id="sMute" type="checkbox" ${this.s.muted ? 'checked' : ''}> ${t('mute')}</label>
        <label>${t('viewMode')} ${sel('sView', [['drag', t('vm_drag')], ['right', t('vm_right')], ['lock', t('vm_lock')]], this.s.viewMode)}</label>
        ${this.touch ? `<label>${t('handed')} ${sel('sHanded', [['right', t('handed_right')], ['left', t('handed_left')]], this.s.handed)}</label>` : ''}
        <label>${t('sens')} <input id="sSens" type="range" min="0.4" max="2.2" step="0.1" value="${this.s.sens}"></label>
        <label><input id="sInv" type="checkbox" ${this.s.invertY ? 'checked' : ''}> ${t('invertY')}</label>
        <label><input id="sAuto" type="checkbox" ${this.s.autoCam ? 'checked' : ''}> ${t('autoCam')}</label>
        <label><input id="sReduce" type="checkbox" ${this.s.reduceMotion ? 'checked' : ''}> ${t('reduce')}</label>
        <label><input id="sAnn" type="checkbox" ${this.s.announce ? 'checked' : ''}> ${t('announce')}</label>
        <label><input id="sAutoT" type="checkbox" ${this.s.autoTime ? 'checked' : ''}> ${t('autoTime')}</label>
        <label><input id="sRain" type="checkbox" ${this.s.rain ? 'checked' : ''}> ${t('rain')}</label>
        <label><input id="sFps" type="checkbox" ${this.s.fps ? 'checked' : ''}> ${t('fps')}</label>
        <label>${t('lang')} ${sel('sLang', [['ja', '日本語'], ['en', 'English']], this.s.lang)}</label>`;
    }
    if (!this.lastFocus) this.lastFocus = document.activeElement;
    m.innerHTML = `<div class="modalbox" role="dialog" aria-modal="true" aria-label="${esc(t(kind === 'spots' ? 'spots' : kind))}">${body}<button id="mClose" class="close">${t('close')}</button></div>`;
    m.classList.remove('hidden');
    $('mClose').onclick = () => this.closeModal();
    m.onclick = (e) => {
      if (e.target === m) this.closeModal();
    };
    m.querySelectorAll('[data-spot]').forEach((b) => (b.onclick = () => {
      this.closeModal();
      this.hooks.goto(this.meta.poi[+b.dataset.spot]);
    }));
    m.querySelectorAll('[data-guide]').forEach((b) => (b.onclick = () => {
      this.closeModal();
      this.hooks.guideTo(this.meta.poi[+b.dataset.guide]);
    }));
    const on = (id, ev, fn) => $(id) && $(id).addEventListener(ev, fn);
    on('mShare', 'click', () => this.hooks.share());
    on('sTime', 'change', (e) => this.hooks.setTime(e.target.value));
    on('sQuality', 'change', (e) => {
      this._set('quality', e.target.value);
      this.openModal('settings'); // re-render: the motion-blur toggle only shows for the ultra preset
    });
    on('sMotionBlur', 'change', (e) => this._set('motionBlur', e.target.checked));
    on('sDof', 'change', (e) => this._set('dof', e.target.checked));
    on('sVol', 'input', (e) => this._set('volume', +e.target.value));
    on('sMute', 'change', (e) => this._set('muted', e.target.checked));
    on('sView', 'change', (e) => this._set('viewMode', e.target.value));
    on('sHanded', 'change', (e) => {
      this._set('handed', e.target.value);
      document.body.dataset.handed = e.target.value;
    });
    on('sSens', 'input', (e) => this._set('sens', +e.target.value));
    on('sInv', 'change', (e) => this._set('invertY', e.target.checked));
    on('sAuto', 'change', (e) => this._set('autoCam', e.target.checked));
    on('sReduce', 'change', (e) => this._set('reduceMotion', e.target.checked));
    on('sAnn', 'change', (e) => this._set('announce', e.target.checked));
    on('sAutoT', 'change', (e) => this._set('autoTime', e.target.checked));
    on('sRain', 'change', (e) => this._set('rain', e.target.checked));
    on('sFps', 'change', (e) => {
      this._set('fps', e.target.checked);
      $('fps').classList.toggle('hidden', !e.target.checked);
    });
    on('sLang', 'change', (e) => {
      this._set('lang', e.target.value);
      this.applyLang();
    });
    this.hooks.modal?.(true);
    m.querySelector('select, input, button[data-spot], #mClose')?.focus({ preventScroll: true });
  }

  _set(k, v) {
    this.s[k] = v;
    this.hooks.changed(k);
  }

  closeModal() {
    this.modalOpen = null;
    $('modal').classList.add('hidden');
    this.hooks.modal?.(false);
    try {
      this.lastFocus?.focus?.({ preventScroll: true });
    } catch {
      /* element gone */
    }
    this.lastFocus = null;
  }

  // ---------------------------------------------------------------------------------------------- photo mode
  enterPhoto(state) {
    const t = this.t;
    this.photo = true;
    $('hud').classList.add('hidden');
    $('touch').classList.add('hidden');
    const p = $('photo');
    p.innerHTML = `<label>${t('photoFov')} <input id="pFov" type="range" min="25" max="95" step="1" value="${state.fov}"></label>
      <label>${t('time')} <select id="pTime">${['day', 'dusk', 'night'].map((k) => `<option value="${k}"${k === state.time ? ' selected' : ''}>${t(k)}</option>`).join('')}</select></label>
      <label><input id="pHide" type="checkbox"> ${t('photoHide')}</label>
      <div class="row"><button id="pShot">${t('capture')}</button><button id="pExit">${t('exitPhoto')}</button></div>`;
    p.classList.remove('hidden');
    $('pFov').oninput = (e) => this.hooks.photoFov(+e.target.value);
    $('pTime').onchange = (e) => this.hooks.setTime(e.target.value);
    $('pHide').onchange = (e) => this.hooks.photoHide(e.target.checked);
    $('pShot').onclick = () => this.hooks.capture();
    $('pExit').onclick = () => this.hooks.photo();
  }

  exitPhoto(touchDevice) {
    this.photo = false;
    $('photo').classList.add('hidden');
    $('hud').classList.remove('hidden');
    if (touchDevice) $('touch').classList.remove('hidden');
  }
}
