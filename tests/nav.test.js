import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { Ground } from '../src/ground.js';
import { findPath, lineWalkable, pathLength } from '../src/nav.js';

const dir = new URL('../public/models/', import.meta.url);
const buf = (f) => {
  const b = readFileSync(new URL(f, dir));
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
};
const meta = JSON.parse(readFileSync(new URL('meta.json', dir), 'utf8'));
const ground = new Ground(meta.grid, buf('ground.bin'), buf('surface.bin'), buf('solid.bin'));
ground.clearDeck(meta.platform);
ground.addTrees(JSON.parse(readFileSync(new URL('trees.json', dir), 'utf8')).trees);
const spawn = [meta.spawn.x, -meta.spawn.y];

describe('route finding', () => {
  it('finds a walkable route from the spawn point to the platform deck', () => {
    const pf = meta.platform;
    const r = findPath(ground, spawn[0], spawn[1], (pf.x0 + pf.x1) / 2, -(pf.y0 + pf.y1) / 2);
    expect(r.reached).toBe(true);
    const len = pathLength(r.points);
    expect(len).toBeGreaterThan(60);
    expect(len).toBeLessThan(160);
    for (let i = 1; i < r.points.length; i++) expect(lineWalkable(ground, ...r.points[i - 1], ...r.points[i], 0.2), `segment ${i}`).toBe(true);
  });

  it('routes to every teleport spot (or as close as the land allows)', () => {
    for (const p of meta.poi) {
      const r = findPath(ground, spawn[0], spawn[1], p.x, -p.y);
      expect(r === null, p.en).toBe(false);
      const last = r.points[r.points.length - 1];
      expect(Math.hypot(last[0] - p.x, last[1] + p.y), p.en).toBeLessThan(40);
    }
  });

  it('crosses the rails at the level crossing rather than walking along them', () => {
    const r = findPath(ground, spawn[0], spawn[1], -40, -8);
    const crossing = r.points.filter((q) => Math.abs(q[1]) < 2.1);
    for (const q of crossing) expect(Math.abs(q[0])).toBeLessThan(5);
  });

  it('leads to the nearest reachable spot when the target is out at sea', () => {
    const r = findPath(ground, spawn[0], spawn[1], 20, 42) // z = +42 is open water;
    expect(r.reached).toBe(false);
    expect(r.points.length).toBeGreaterThan(1);
  });
});
