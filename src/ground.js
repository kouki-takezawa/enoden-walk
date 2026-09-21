// Walkable grid baked in Blender (1 m cells).  Stored in Blender coordinates (x, y); three.js uses z = -y.
//   heights  Float32  ground height, NaN = no ground or a building footprint
//   surface  Uint8    0 none, 1 asphalt, 2 concrete, 3 grass, 4 sand, 5 gravel
//   solid    Uint8    1 = fence / pole / railing / furniture (thin things a height cell would miss); trees are added at load
export const SEA_BLOCK = -2.3; // below this the shore turns into sea: not walkable

export class Ground {
  constructor(grid, heights, surface, solid) {
    Object.assign(this, grid);
    this.h = new Float32Array(heights);
    this.surf = new Uint8Array(surface);
    this.solid = new Uint8Array(solid);
  }

  raw(i, j) {
    if (i < 0 || j < 0 || i >= this.nx || j >= this.ny) return NaN;
    return this.h[j * this.nx + i];
  }

  index(x, z) {
    const i = Math.round((x - this.x0) / this.step);
    const j = Math.round((-z - this.y0) / this.step);
    return i < 0 || j < 0 || i >= this.nx || j >= this.ny ? -1 : j * this.nx + i;
  }

  /** bilinear ground height at (x, z), NaN when any of the four cells is blocked */
  height(x, z) {
    const fx = (x - this.x0) / this.step;
    const fy = (-z - this.y0) / this.step;
    const i = Math.floor(fx);
    const j = Math.floor(fy);
    const tx = fx - i;
    const ty = fy - j;
    const a = this.raw(i, j);
    const b = this.raw(i + 1, j);
    const c = this.raw(i, j + 1);
    const d = this.raw(i + 1, j + 1);
    if (!(a === a && b === b && c === c && d === d)) return NaN;
    return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty;
  }

  walkable(x, z) {
    const h = this.height(x, z);
    return h === h && h > SEA_BLOCK;
  }

  isSolid(x, z) {
    const k = this.index(x, z);
    return k >= 0 && this.solid[k] === 1;
  }

  surface(x, z) {
    const k = this.index(x, z);
    return k < 0 ? 0 : this.surf[k];
  }

  /** tree trunks (kinds 0..2) block their cell */
  addTrees(trees) {
    for (const t of trees) {
      if (t[0] > 2) continue;
      const k = this.index(t[1], t[3]);
      if (k >= 0 && this.h[k] === this.h[k]) this.solid[k] = 1;
    }
  }

  /** true when the straight segment crosses a building footprint (used to keep the camera outside walls) */
  segmentBlocked(x0, z0, x1, z1) {
    const n = Math.max(2, Math.ceil(Math.hypot(x1 - x0, z1 - z0) / 0.6));
    for (let i = 1; i <= n; i++) {
      const t = i / n;
      const h = this.height(x0 + (x1 - x0) * t, z0 + (z1 - z0) * t);
      if (h !== h && this.index(x0 + (x1 - x0) * t, z0 + (z1 - z0) * t) >= 0) return t;
    }
    return 0;
  }
}
