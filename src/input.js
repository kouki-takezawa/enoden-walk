// Keyboard, mouse (drag / right-drag / pointer lock), touch (floating stick + look + pinch) and gamepad, unified.
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const DEAD = 0.18;

export class Input {
  constructor(canvas, settings, hooks) {
    this.canvas = canvas;
    this.s = settings; // live reference: sens / invertY / viewMode
    this.hooks = hooks; // { jump, board, photo, mute, help, cycleTime, toggleMenu, recenter, escape, stick }
    this.keys = {};
    this.touch = { x: 0, y: 0, run: false };
    this.pad = { x: 0, y: 0, run: false, sprint: false };
    this.look = { dx: 0, dy: 0 }; // accumulated look delta (radians), drained by the camera
    this.zoom = 0; // accumulated zoom delta
    this.lastLook = 0;
    this.enabled = true;
    this.padPrev = {};
    this.stickId = null;
    this.stickOrigin = null;
    this.camPointers = new Map();
    this.pinch = null;
    this._bind();
  }

  _bind() {
    const kd = (e) => {
      if (!this.enabled || e.target.matches?.('input, select, textarea')) return;
      if (['Space', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.code)) e.preventDefault();
      if (e.repeat) return;
      this.keys[e.code] = true;
      if (e.code === 'Space') this.hooks.jump();
      else if (e.code === 'KeyE') this.hooks.board();
      else if (e.code === 'KeyP') this.hooks.photo();
      else if (e.code === 'KeyM') this.hooks.mute();
      else if (e.code === 'KeyH' || e.code === 'F1' || e.key === '?') this.hooks.help();
      else if (e.code === 'KeyT') this.hooks.cycleTime();
      else if (e.code === 'KeyC') this.hooks.recenter?.();
      else if (e.code === 'KeyF') this.hooks.autoWalk?.();
      else if (e.code === 'Escape') this.hooks.escape?.();
      else if (e.code === 'Tab') {
        e.preventDefault();
        this.hooks.toggleMenu();
      }
    };
    addEventListener('keydown', kd);
    addEventListener('keyup', (e) => {
      this.keys[e.code] = false;
    });
    addEventListener('blur', () => {
      for (const k in this.keys) this.keys[k] = false;
    });

    // ---- mouse / pen / touch on the canvas
    const c = this.canvas;
    c.addEventListener('contextmenu', (e) => e.preventDefault());
    c.addEventListener('pointerdown', (e) => {
      if (!this.enabled) return;
      if (e.pointerType === 'touch') {
        this._touchDown(e);
        return;
      }
      const vm = this.s.viewMode;
      if (vm === 'lock') {
        if (document.pointerLockElement !== c) c.requestPointerLock?.();
        return;
      }
      if ((vm === 'drag' && e.button === 0) || (vm === 'right' && e.button === 2) || e.button === 1) {
        this.camPointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
        c.setPointerCapture(e.pointerId);
      }
    });
    c.addEventListener('pointermove', (e) => {
      if (e.pointerType === 'touch') {
        this._touchMove(e);
        return;
      }
      const p = this.camPointers.get(e.pointerId);
      if (p) {
        this._addLook(e.clientX - p.x, e.clientY - p.y, 0.0055);
        p.x = e.clientX;
        p.y = e.clientY;
      } else if (document.pointerLockElement === c) this._addLook(e.movementX, e.movementY, 0.0022);
    });
    const up = (e) => {
      this.camPointers.delete(e.pointerId);
      if (e.pointerType === 'touch') this._touchUp(e);
    };
    c.addEventListener('pointerup', up);
    c.addEventListener('pointercancel', up);
    c.addEventListener('wheel', (e) => {
      this.zoom += e.deltaY * 0.0012;
      e.preventDefault();
    }, { passive: false });
  }

  _addLook(dx, dy, k) {
    const s = this.s.sens * k;
    this.look.dx += dx * s;
    this.look.dy += dy * s * (this.s.invertY ? -1 : 1);
    this.lastLook = performance.now();
  }

  // ---- touch: left 45% floating stick, the rest looks; two fingers pinch
  _touchDown(e) {
    const w = innerWidth;
    if (this.camPointers.size === 1 && this.stickId !== e.pointerId) {
      // second finger on the look side -> pinch
      const [id, p] = [...this.camPointers][0];
      this.pinch = { a: id, b: e.pointerId, d: Math.hypot(p.x - e.clientX, p.y - e.clientY), pa: p, pb: { x: e.clientX, y: e.clientY } };
    }
    if (e.clientX < w * 0.45 && this.stickId === null && !e.target.closest?.('#btns')) {
      this.stickId = e.pointerId;
      this.stickOrigin = { x: e.clientX, y: e.clientY };
      this.hooks.stick?.(true, e.clientX, e.clientY, 0, 0);
      this.canvas.setPointerCapture(e.pointerId);
    } else {
      this.camPointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      this.canvas.setPointerCapture(e.pointerId);
    }
  }

  _touchMove(e) {
    if (e.pointerId === this.stickId) {
      const o = this.stickOrigin;
      let dx = e.clientX - o.x;
      let dy = e.clientY - o.y;
      const m = Math.hypot(dx, dy);
      const lim = 56;
      if (m > lim) {
        dx = (dx / m) * lim;
        dy = (dy / m) * lim;
      }
      this.touch.x = dx / lim;
      this.touch.y = -dy / lim;
      this.hooks.stick?.(true, o.x, o.y, dx, dy);
      return;
    }
    const p = this.camPointers.get(e.pointerId);
    if (!p) return;
    if (this.pinch && (e.pointerId === this.pinch.a || e.pointerId === this.pinch.b)) {
      const pa = this.camPointers.get(this.pinch.a);
      const pb = this.camPointers.get(this.pinch.b);
      if (pa && pb) {
        if (e.pointerId === this.pinch.a) {
          pa.x = e.clientX;
          pa.y = e.clientY;
        } else {
          pb.x = e.clientX;
          pb.y = e.clientY;
        }
        const d = Math.hypot(pa.x - pb.x, pa.y - pb.y);
        this.zoom -= (d - this.pinch.d) * 0.004;
        this.pinch.d = d;
        return;
      }
    }
    this._addLook(e.clientX - p.x, e.clientY - p.y, 0.006);
    p.x = e.clientX;
    p.y = e.clientY;
  }

  _touchUp(e) {
    if (e.pointerId === this.stickId) {
      this.stickId = null;
      this.touch.x = this.touch.y = 0;
      this.hooks.stick?.(false, 0, 0, 0, 0);
    }
    if (this.pinch && (e.pointerId === this.pinch.a || e.pointerId === this.pinch.b)) this.pinch = null;
  }

  // ---- gamepad (polled once per frame)
  pollPad() {
    const pads = navigator.getGamepads ? navigator.getGamepads() : [];
    const gp = [...pads].find((p) => p && p.connected);
    if (!gp) {
      this.pad.x = this.pad.y = 0;
      this.pad.run = this.pad.sprint = false;
      return;
    }
    const ax = (i) => (Math.abs(gp.axes[i] || 0) > DEAD ? gp.axes[i] : 0);
    this.pad.x = ax(0);
    this.pad.y = -ax(1);
    const rx = ax(2);
    const ry = ax(3);
    if (rx || ry) {
      this.look.dx += rx * 0.045 * this.s.sens;
      this.look.dy += ry * 0.03 * this.s.sens * (this.s.invertY ? -1 : 1);
      this.lastLook = performance.now();
    }
    const b = (i) => !!(gp.buttons[i] && gp.buttons[i].pressed);
    this.pad.run = b(7) || b(5);
    this.pad.sprint = b(2) || b(10); // pressing the left stick = dash
    const edge = (name, i, fn) => {
      const on = b(i);
      if (on && !this.padPrev[name]) fn();
      this.padPrev[name] = on;
    };
    edge('a', 0, this.hooks.jump);
    edge('y', 3, this.hooks.board);
    edge('start', 9, this.hooks.toggleMenu);
    edge('select', 8, this.hooks.help);
  }

  /** current movement command */
  read() {
    const k = this.keys;
    let x = (k.KeyD || k.ArrowRight ? 1 : 0) - (k.KeyA || k.ArrowLeft ? 1 : 0) + this.touch.x + this.pad.x;
    let y = (k.KeyW || k.ArrowUp ? 1 : 0) - (k.KeyS || k.ArrowDown ? 1 : 0) + this.touch.y + this.pad.y;
    x = clamp(x, -1, 1);
    y = clamp(y, -1, 1);
    return {
      x,
      y,
      // a floating stick pushed to its very end also runs
      run: !!(k.ShiftLeft || k.ShiftRight) || this.touch.run || this.pad.run || Math.hypot(this.touch.x, this.touch.y) > 0.94,
      sprint: !!k.KeyR || this.pad.sprint,
    };
  }

  drainLook() {
    const l = { dx: this.look.dx, dy: this.look.dy };
    this.look.dx = this.look.dy = 0;
    return l;
  }

  drainZoom() {
    const z = this.zoom;
    this.zoom = 0;
    return z;
  }
}
