/** Tiny WebAudio soundscape, all synthesised: crossing bell, sea, wind, night crickets, footsteps (per surface), train rumble + rail joints.
 *  Created on the first user gesture. */
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

export class Sound {
  constructor() {
    this.ctx = null;
    this.muted = false;
    this.volume = 0.8;
    this.nextKan = 0;
    this.flip = false;
    this.nextClack = 0;
    this.nextCricket = 0;
  }

  init() {
    if (this.ctx) return;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    this.ctx = new AC();
    this.master = this.ctx.createGain();
    this.master.connect(this.ctx.destination);
    this.applyVolume();
    // shared 1.5 s noise buffer (brown-ish) for every noise based sound
    const len = Math.floor(this.ctx.sampleRate * 1.5);
    this.noise = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
    const d = this.noise.getChannelData(0);
    let last = 0;
    for (let i = 0; i < len; i++) {
      last = last * 0.96 + (Math.random() * 2 - 1) * 0.04;
      d[i] = last * 8;
    }
    this.white = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
    const w = this.white.getChannelData(0);
    for (let i = 0; i < len; i++) w[i] = Math.random() * 2 - 1;
    this.sea = this._loop(this.noise, 'lowpass', 620, 0.11);
    this.wind = this._loop(this.white, 'bandpass', 420, 0.07);
    this.rumble = this._loop(this.noise, 'lowpass', 180, 0.3);
    this.rumble.g.gain.value = 0;
  }

  _loop(buf, type, freq, lfoHz) {
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.loop = true;
    const f = this.ctx.createBiquadFilter();
    f.type = type;
    f.frequency.value = freq;
    const g = this.ctx.createGain();
    g.gain.value = 0;
    const lfo = this.ctx.createOscillator();
    lfo.frequency.value = lfoHz;
    const lg = this.ctx.createGain();
    lg.gain.value = 0.04;
    lfo.connect(lg).connect(g.gain);
    lfo.start();
    src.connect(f).connect(g).connect(this.master);
    src.start(0, Math.random());
    return { g, f };
  }

  applyVolume() {
    if (this.master) this.master.gain.value = this.muted ? 0 : this.volume;
  }

  setVolume(v) {
    this.volume = v;
    this.applyVolume();
  }

  toggle() {
    this.muted = !this.muted;
    this.applyVolume();
    return this.muted;
  }

  _burst(buf, type, freq, q, vol, dur) {
    const t = this.ctx.currentTime;
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    const f = this.ctx.createBiquadFilter();
    f.type = type;
    f.frequency.value = freq;
    f.Q.value = q;
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.0006, t + dur);
    src.connect(f).connect(g).connect(this.master);
    src.start(t, Math.random() * 0.8);
    src.stop(t + dur + 0.02);
  }

  /** foot strike; surface: 1 asphalt, 2 concrete, 3 grass, 4 sand, 5 gravel */
  step(surface, speed) {
    if (!this.ctx) return;
    const v = clamp(0.05 + speed * 0.05, 0.05, 0.3);
    switch (surface) {
      case 3: this._burst(this.noise, 'lowpass', 900, 0.7, v * 1.6, 0.12); break;
      case 4: this._burst(this.white, 'highpass', 1600, 0.7, v * 0.45, 0.16); break;
      case 5: this._burst(this.white, 'bandpass', 2600, 0.9, v * 0.9, 0.09); this._burst(this.white, 'bandpass', 1900, 0.9, v * 0.6, 0.14); break;
      case 2: this._burst(this.white, 'bandpass', 2300, 1.1, v * 0.6, 0.05); break;
      default: this._burst(this.white, 'bandpass', 1500, 1.3, v * 0.55, 0.05);
    }
  }

  kan(vol, f) {
    const t = this.ctx.currentTime;
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.0008, t + 0.42);
    g.connect(this.master);
    for (const [mul, type, amp] of [[1, 'sine', 1], [2.41, 'triangle', 0.35], [4.7, 'sine', 0.12]]) {
      const o = this.ctx.createOscillator();
      o.type = type;
      o.frequency.value = f * mul;
      const og = this.ctx.createGain();
      og.gain.value = amp;
      o.connect(og).connect(g);
      o.start(t);
      o.stop(t + 0.45);
    }
  }

  /**
   * s: {alarm, crossDist, sea (0..1), night (0..1), trainSpeed, trainDist, riding}
   */
  update(s) {
    if (!this.ctx) return;
    if (this.ctx.state === 'suspended') this.ctx.resume();
    const now = this.ctx.currentTime;
    this.sea.g.gain.value = 0.02 + 0.11 * s.sea;
    this.wind.g.gain.value = 0.012 + 0.03 * (1 - s.sea * 0.5);
    // train: rumble + rail-joint clacks, louder when close (or when riding)
    const near = s.riding ? 1 : clamp(1 - s.trainDist / 210, 0, 1);
    const sp = s.trainSpeed / 11;
    this.rumble.g.gain.value = near * sp * (s.riding ? 0.34 : 0.28);
    this.rumble.f.frequency.value = 120 + 140 * sp;
    if (sp > 0.05 && near > 0.02 && now >= this.nextClack) {
      this._burst(this.white, 'bandpass', 900, 2.0, 0.05 * near * (0.4 + sp), 0.07);
      this.nextClack = now + clamp(0.42 / Math.max(sp, 0.15), 0.12, 1.4);
    }
    if (s.alarm && now >= this.nextKan) {
      const vol = clamp(1 - s.crossDist / 160, 0, 1) * 0.16;
      if (vol > 0.002) this.kan(vol, this.flip ? 1230 : 1580);
      this.flip = !this.flip;
      this.nextKan = now + 0.5;
    }
    if (s.night > 0.5 && now >= this.nextCricket) {
      const f = 4300 + Math.random() * 500;
      for (let i = 0; i < 3; i++) {
        const t = now + i * 0.09;
        const o = this.ctx.createOscillator();
        o.frequency.value = f;
        const g = this.ctx.createGain();
        g.gain.setValueAtTime(0.0001, t);
        g.gain.linearRampToValueAtTime(0.012 * s.night, t + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t + 0.07);
        o.connect(g).connect(this.master);
        o.start(t);
        o.stop(t + 0.08);
      }
      this.nextCricket = now + 0.6 + Math.random() * 1.6;
    }
  }
}
