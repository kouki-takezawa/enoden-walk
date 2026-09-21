import { describe, it, expect } from 'vitest';
import { PRESETS, DEFAULTS, makeT } from '../src/config.js';

describe('config', () => {
  it('has the same string keys in Japanese and English', async () => {
    const mod = await import('../src/config.js');
    const tJa = makeT(() => 'ja');
    const tEn = makeT(() => 'en');
    // every key the UI asks for must resolve to something other than the key itself
    const keys = ['title', 'start', 'help', 'settings', 'spots', 'photo', 'time', 'day', 'dusk', 'night', 'quality', 'volume', 'boardPrompt', 'alightPrompt', 'clearCrossing', 'helpShort', 'saved', 'recenterKey'];
    for (const k of keys) {
      expect(tJa(k)).not.toBe(k);
      expect(tEn(k)).not.toBe(k);
    }
    expect(mod.autoPreset()).toMatch(/low|medium|high/);
  });

  it('interpolates variables and falls back to Japanese for a missing English string', () => {
    const t = makeT(() => 'en');
    expect(t('where_near', { name: 'X' })).toBe('Near X');
    expect(makeT(() => 'ja')('in', { s: 5 })).toBe('あと 5 秒');
    expect(makeT(() => 'xx')('title')).toBe(makeT(() => 'ja')('title'));
  });

  it('presets are ordered by cost', () => {
    expect(PRESETS.low.shadow).toBeLessThan(PRESETS.medium.shadow);
    expect(PRESETS.medium.shadow).toBeLessThan(PRESETS.high.shadow);
    expect(PRESETS.low.bloom).toBe(false);
    expect(PRESETS.high.msaa).toBeGreaterThan(0);
    for (const p of Object.values(PRESETS)) for (const k of ['dpr', 'shadow', 'shadowRange', 'bloom', 'msaa', 'leafCards', 'detail', 'clouds', 'wind', 'pointLights', 'seaDepth', 'glow']) expect(p).toHaveProperty(k);
  });

  it('defaults are sane', () => {
    expect(['ja', 'en']).toContain(DEFAULTS.lang);
    expect(DEFAULTS.volume).toBeGreaterThan(0);
  });
});
