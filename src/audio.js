/** Tiny WebAudio soundscape: the level-crossing bell (two alternating "kan" tones) and the sea. Created on the first user gesture. */
export class Sound {
  constructor() {
    this.ctx = null;
    this.muted = false;
    this.next = 0;
    this.flip = false;
  }

  init() {
    if (this.ctx) return;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    this.ctx = new AC();
    this.master = this.ctx.createGain();
    this.master.gain.value = 0.8;
    this.master.connect(this.ctx.destination);
    // sea: looped noise, low-passed, slowly swelling
    const len = this.ctx.sampleRate * 3;
    const buf = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
    const d = buf.getChannelData(0);
    let last = 0;
    for (let i = 0; i < len; i++) {
      last = last * 0.96 + (Math.random() * 2 - 1) * 0.04;
      d[i] = last * 8;
    }
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.loop = true;
    const lp = this.ctx.createBiquadFilter();
    lp.type = 'lowpass';
    lp.frequency.value = 620;
    this.seaGain = this.ctx.createGain();
    this.seaGain.gain.value = 0.0;
    const lfo = this.ctx.createOscillator();
    lfo.frequency.value = 0.11;
    const lfoGain = this.ctx.createGain();
    lfoGain.gain.value = 0.05;
    lfo.connect(lfoGain).connect(this.seaGain.gain);
    lfo.start();
    src.connect(lp).connect(this.seaGain).connect(this.master);
    src.start();
  }

  toggle() {
    this.muted = !this.muted;
    if (this.master) this.master.gain.value = this.muted ? 0 : 0.8;
    return this.muted;
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

  /** alarm: crossing bell active; crossDist: metres from the crossing; sea: 0..1 loudness of the surf */
  update(alarm, crossDist, sea) {
    if (!this.ctx) return;
    if (this.ctx.state === 'suspended') this.ctx.resume();
    const now = this.ctx.currentTime;
    this.seaGain.gain.value = 0.02 + 0.10 * sea;
    if (alarm && now >= this.next) {
      const vol = Math.max(0, 1 - crossDist / 160) * 0.16;
      if (vol > 0.002) this.kan(vol, this.flip ? 1230 : 1580);
      this.flip = !this.flip;
      this.next = now + 0.5;
    }
  }
}
