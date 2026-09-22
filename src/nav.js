// Route finding on the 1 m walkable grid, with the same rules the player obeys (no sea, no solid cells, slope limit).
import { SEA_BLOCK } from './ground.js';

const SQ2 = Math.SQRT2;
const SLOPE = 1.15;
const NB = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, 1], [1, -1], [-1, -1]];

/** binary min-heap of node ids ordered by a Float32Array of scores */
class Heap {
  constructor(score) {
    this.a = [];
    this.s = score;
  }

  push(n) {
    const a = this.a;
    a.push(n);
    let i = a.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (this.s[a[p]] <= this.s[a[i]]) break;
      [a[p], a[i]] = [a[i], a[p]];
      i = p;
    }
  }

  pop() {
    const a = this.a;
    const top = a[0];
    const last = a.pop();
    if (a.length) {
      a[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let m = i;
        if (l < a.length && this.s[a[l]] < this.s[a[m]]) m = l;
        if (r < a.length && this.s[a[r]] < this.s[a[m]]) m = r;
        if (m === i) break;
        [a[m], a[i]] = [a[i], a[m]];
        i = m;
      }
    }
    return top;
  }

  get size() {
    return this.a.length;
  }
}

/** true when the straight segment can be walked (bilinear heights, solid cells and slope sampled every 0.4 m) */
export function lineWalkable(ground, x0, z0, x1, z1, clear = 0.4) {
  const len = Math.hypot(x1 - x0, z1 - z0);
  const n = Math.max(1, Math.ceil(len / 0.4));
  const px = len > 0 ? -(z1 - z0) / len : 0; // unit normal of the segment
  const pz = len > 0 ? (x1 - x0) / len : 0;
  let hPrev = ground.height(x0, z0);
  for (let i = 1; i <= n; i++) {
    const x = x0 + ((x1 - x0) * i) / n;
    const z = z0 + ((z1 - z0) * i) / n;
    const h = ground.height(x, z);
    if (!(h === h) || h < SEA_BLOCK || ground.isSolid(x, z)) return false;
    if (hPrev === hPrev && (h - hPrev) / (len / n) > SLOPE) return false;
    hPrev = h;
    // keep a little clearance to both sides so the walker (who drifts off the line) does not scrape along walls
    for (const s of [-clear, clear]) {
      const sh = ground.height(x + px * s, z + pz * s);
      if (!(sh === sh) || sh < SEA_BLOCK || ground.isSolid(x + px * s, z + pz * s)) return false;
    }
  }
  return true;
}

/**
 * Path from (sx, sz) to (tx, tz) in world coordinates.  Returns { points: [[x, z], ...], reached } where the polyline is smoothed by
 * line-of-sight; when the target cannot be reached the path leads to the reachable cell nearest to it (reached = false).
 * Rails away from the level crossing cost extra, so routes prefer the crossing to walking along the track.
 */
export function findPath(ground, sx, sz, tx, tz) {
  const { nx, ny, step, x0, y0 } = ground;
  const N = nx * ny;
  const cellOf = (x, z) => {
    const i = Math.round((x - x0) / step);
    const j = Math.round((-z - y0) / step);
    return i < 0 || j < 0 || i >= nx || j >= ny ? -1 : j * nx + i;
  };
  const wx = (k) => x0 + (k % nx) * step;
  const wz = (k) => -(y0 + Math.floor(k / nx) * step);
  const ok = (k) => {
    const h = ground.h[k];
    return h === h && h > SEA_BLOCK && ground.solid[k] !== 1;
  };
  const penalty = (k) => {
    const z = wz(k);
    const x = wx(k);
    return Math.abs(z) < 2.1 && Math.abs(x) > 4.6 && Math.abs(x) < 200 ? 22 : 0; // rails outside the crossing
  };
  let start = cellOf(sx, sz);
  if (start < 0) return null;
  if (!ok(start)) {
    // the player may stand on a solid cell edge: take the nearest free cell
    const i = start % nx;
    const j = (start / nx) | 0;
    let bd = Infinity;
    start = -1;
    for (let dj = -2; dj <= 2; dj++) {
      for (let di = -2; di <= 2; di++) {
        const ni = i + di;
        const nj = j + dj;
        if (ni < 0 || nj < 0 || ni >= nx || nj >= ny || !ok(nj * nx + ni)) continue;
        const d = Math.hypot(x0 + ni * step - sx, -(y0 + nj * step) - sz);
        if (d < bd) {
          bd = d;
          start = nj * nx + ni;
        }
      }
    }
    if (start < 0) return null;
  }
  let goal = cellOf(tx, tz);
  if (goal < 0) return null;

  const g = new Float32Array(N).fill(Infinity);
  const f = new Float32Array(N).fill(Infinity);
  const parent = new Int32Array(N).fill(-1);
  const closed = new Uint8Array(N);
  const gxw = tx;
  const gzw = tz;
  const hEst = (k) => Math.hypot(wx(k) - gxw, wz(k) - gzw) / step;
  const heap = new Heap(f);
  g[start] = 0;
  f[start] = hEst(start);
  heap.push(start);
  let best = start;
  let bestH = hEst(start);
  let found = false;
  while (heap.size) {
    const k = heap.pop();
    if (closed[k]) continue;
    closed[k] = 1;
    const hk = hEst(k);
    if (hk < bestH) {
      bestH = hk;
      best = k;
    }
    if (k === goal || hk < 0.8) {
      goal = k;
      found = true;
      break;
    }
    const i = k % nx;
    const j = (k / nx) | 0;
    for (const [di, dj] of NB) {
      const ni = i + di;
      const nj = j + dj;
      if (ni < 0 || nj < 0 || ni >= nx || nj >= ny) continue;
      const m = nj * nx + ni;
      if (closed[m] || !ok(m)) continue;
      const diag = di !== 0 && dj !== 0;
      if (diag && (!ok(j * nx + ni) || !ok(nj * nx + i))) continue; // no corner cutting
      const d = diag ? SQ2 : 1;
      if ((ground.h[m] - ground.h[k]) / (d * step) > SLOPE) continue;
      const c = g[k] + d + penalty(m);
      if (c < g[m]) {
        g[m] = c;
        f[m] = c + hEst(m);
        parent[m] = k;
        heap.push(m);
      }
    }
  }
  const end = found ? goal : best;
  const cells = [];
  for (let k = end; k !== -1; k = parent[k]) cells.push(k);
  cells.reverse();
  let pts = cells.map((k) => [wx(k), wz(k)]);
  if (found) pts.push([tx, tz]);
  // line-of-sight smoothing
  const out = [pts[0]];
  let a = 0;
  while (a < pts.length - 1) {
    let b = pts.length - 1;
    while (b > a + 1 && !lineWalkable(ground, pts[a][0], pts[a][1], pts[b][0], pts[b][1])) b--;
    out.push(pts[b]);
    a = b;
  }
  pts = out;
  return { points: pts, reached: found };
}

export function pathLength(points) {
  let d = 0;
  for (let i = 1; i < points.length; i++) d += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
  return d;
}
