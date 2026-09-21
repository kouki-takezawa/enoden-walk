// Walkable height grid baked in Blender (1 m cells, NaN = no ground or a building footprint).
// The grid is stored in Blender coordinates (x, y); three.js uses z = -y.
export const SEA_BLOCK = -2.3; // below this the shore turns into sea: not walkable

export class Ground {
  constructor(grid, buffer) {
    Object.assign(this, grid);
    this.h = new Float32Array(buffer);
  }

  raw(i, j) {
    if (i < 0 || j < 0 || i >= this.nx || j >= this.ny) return NaN;
    return this.h[j * this.nx + i];
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
}
