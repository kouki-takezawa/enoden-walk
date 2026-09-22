import { describe, it, expect } from 'vitest';
import { Ground, SEA_BLOCK } from '../src/ground.js';

// 10 x 8 grid, 1 m cells, x0 = -5, y0 = -4 (Blender coords; three.js z = -y)
const grid = { x0: -5, y0: -4, step: 1, nx: 10, ny: 8 };
function make(fill = (i, j) => 1 + 0.1 * i) {
  const h = new Float32Array(grid.nx * grid.ny);
  const s = new Uint8Array(grid.nx * grid.ny).fill(1);
  const o = new Uint8Array(grid.nx * grid.ny);
  for (let j = 0; j < grid.ny; j++) for (let i = 0; i < grid.nx; i++) h[j * grid.nx + i] = fill(i, j);
  return new Ground(grid, h.buffer, s.buffer, o.buffer);
}

describe('Ground', () => {
  it('interpolates the height bilinearly', () => {
    const g = make();
    expect(g.height(-5, 0)).toBeCloseTo(1.0, 5);
    expect(g.height(-4.5, 0)).toBeCloseTo(1.05, 5);
    expect(g.height(0, 0)).toBeCloseTo(1.5, 5);
  });

  it('maps three.js z to the flipped grid row', () => {
    const g = make((i, j) => j); // height = row = blender y - y0
    // z = -y: z = 0 is y = 0 -> row 4
    expect(g.height(0, 0)).toBeCloseTo(4, 5);
    expect(g.height(0, -2)).toBeCloseTo(6, 5);
  });

  it('is NaN / not walkable next to a building cell and outside the grid', () => {
    const g = make((i, j) => (i === 5 && j === 4 ? NaN : 0));
    expect(g.height(0, 0)).toBeNaN();
    expect(g.walkable(0, 0)).toBe(false);
    expect(g.walkable(-4, 0)).toBe(true);
    expect(g.walkable(100, 100)).toBe(false);
  });

  it('treats the sea shore as not walkable', () => {
    const g = make(() => SEA_BLOCK - 0.5);
    expect(g.walkable(0, 0)).toBe(false);
  });

  it('marks trunks as solid but not shrubs', () => {
    const g = make(() => 0);
    g.addTrees([[0, 1, 0, -1, 5, 1, 0], [3, 2, 0, -2, 1, 1, 0]]);
    expect(g.isSolid(1, -1)).toBe(true);
    expect(g.isSolid(2, -2)).toBe(false);
  });

  it('reports the fraction of a segment at which it enters a building', () => {
    const g = make((i, j) => (i === 8 ? NaN : 0));
    expect(g.segmentBlocked(-4, 0, -3, 0)).toBe(0);
    const t = g.segmentBlocked(-4, 0, 4, 0);
    expect(t).toBeGreaterThan(0.5);
    expect(t).toBeLessThan(1);
  });

  it('clearDeck frees solid cells on the platform deck only', () => {
    const g = make((i, j) => (j >= 4 ? 1.1 : -0.2)); // y = j - 4: deck for y >= 0
    g.solid.fill(1);
    g.clearDeck({ x0: -3, x1: 2, y0: 0.5, y1: 3.95, height: 1.1 });
    expect(g.isSolid(0, -1)).toBe(false);
    expect(g.isSolid(0, -3)).toBe(false);
    expect(g.isSolid(0, 0)).toBe(true); // track side stays closed
    expect(g.isSolid(0, -4)).toBe(true); // back fence stays closed
  });
});
