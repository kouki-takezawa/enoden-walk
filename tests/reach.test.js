import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { Ground } from '../src/ground.js';

// Walks the real baked data with the same movement rules as Player (slope limit, solid cells, sea) to make sure every place the game
// sends the player to can actually be reached on foot.
const dir = new URL('../public/models/', import.meta.url);
const buf = (f) => {
  const b = readFileSync(new URL(f, dir));
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
};
const meta = JSON.parse(readFileSync(new URL('meta.json', dir), 'utf8'));
const ground = new Ground(meta.grid, buf('ground.bin'), buf('surface.bin'), buf('solid.bin'));
ground.clearDeck(meta.platform);
const trees = JSON.parse(readFileSync(new URL('trees.json', dir), 'utf8'));
ground.addTrees(trees.trees);

const STEP = 0.5;
const key = (x, z) => `${Math.round(x / STEP)},${Math.round(z / STEP)}`;

function reachable(x0, z0) {
  const seen = new Set([key(x0, z0)]);
  const stack = [[x0, z0]];
  const dirs = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, -1], [1, -1], [-1, 1]];
  while (stack.length) {
    const [x, z] = stack.pop();
    const h0 = ground.height(x, z);
    for (const [dx, dz] of dirs) {
      const nx = x + dx * STEP;
      const nz = z + dz * STEP;
      const k = key(nx, nz);
      if (seen.has(k)) continue;
      const h1 = ground.height(nx, nz);
      if (!(h1 === h1) || h1 < -2.3 || ground.isSolid(nx, nz)) continue;
      if ((h1 - h0) / (STEP * Math.hypot(dx, dz)) > 1.15) continue;
      seen.add(k);
      stack.push([nx, nz]);
    }
  }
  return seen;
}

const spawn = [meta.spawn.x, -meta.spawn.y];
const seen = reachable(spawn[0], spawn[1]);
const near = (x, z, r) => {
  for (let dx = -r; dx <= r; dx += STEP) for (let dz = -r; dz <= r; dz += STEP) if (seen.has(key(x + dx, z + dz))) return true;
  return false;
};

describe('walkable world', () => {
  it('reaches every teleport spot from the spawn point', () => {
    for (const p of meta.poi) expect(near(p.x, -p.y, 8), p.en).toBe(true);
  });

  it('reaches the whole platform deck (via the west ramp)', () => {
    const pf = meta.platform;
    let n = 0;
    let ok = 0;
    for (let x = pf.x0 + 1; x < pf.x1; x += 1) {
      for (const y of [2.5, 3]) {
        n++;
        if (seen.has(key(x, -y))) ok++;
      }
    }
    expect(ok / n).toBeGreaterThan(0.95);
    expect(near(pf.x0 - 2.5, -(pf.y0 + pf.y1) / 2, 1)).toBe(true); // the ramp itself
  });

  it('keeps the track side of the platform closed', () => {
    for (let x = -50; x < -12; x += 3) expect(ground.isSolid(x, -1)).toBe(true);
  });
});
