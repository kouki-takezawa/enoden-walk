import { describe, it, expect } from 'vitest';
import * as THREE from 'three';
import { Train } from '../src/train.js';

const meta = {
  platform: { x0: -55, x1: -10, y0: 1.35, y1: 3.95, height: 1.1 },
  crossing: { arms: [] },
};

function make() {
  const scene = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial({ name: 'W_MAT_Glass_Train', transparent: true }));
  scene.add(body);
  const tr = new Train({ scene }, new THREE.Group(), meta);
  return tr;
}

/** step the simulation until pred() or the time limit; returns elapsed seconds */
function run(tr, pred, limit = 400, dt = 1 / 30) {
  let t = 0;
  while (t < limit && !pred(tr)) {
    tr.update(dt, 0);
    t += dt;
  }
  return t;
}

describe('Train', () => {
  it('waits, arrives, stops at the platform and leaves again', () => {
    const tr = make();
    expect(tr.state).toBe('wait');
    run(tr, (x) => x.state === 'dwell');
    expect(tr.state).toBe('dwell');
    expect(tr.dir).toBe(1); // first run is eastbound
    expect(tr.front).toBeCloseTo(meta.platform.x1 - 2, 1);
    expect(tr.speed).toBe(0);
    run(tr, (x) => x.state === 'move');
    expect(tr.stopping).toBe(false);
    run(tr, (x) => x.state === 'wait');
    expect(tr.state).toBe('wait');
    expect(tr.timer).toBeGreaterThan(19);
  });

  it('alternates direction; the westbound run stops at the far end of the platform', () => {
    const tr = make();
    run(tr, (x) => x.state === 'dwell');
    run(tr, (x) => x.state === 'wait');
    run(tr, (x) => x.state === 'dwell', 600);
    expect(tr.dir).toBe(-1);
    expect(tr.front).toBeCloseTo(meta.platform.x0 + 2, 1);
  });

  it('rings the crossing alarm before the eastbound departure and while it clears the crossing', () => {
    const tr = make();
    run(tr, (x) => x.state === 'dwell');
    expect(tr.alarm).toBe(false);
    run(tr, (x) => x.alarm);
    expect(tr.alarm).toBe(true);
    expect(tr.timer).toBeLessThan(3.6); // starts just before departure
    run(tr, (x) => !x.alarm);
    expect(tr.span()[0]).toBeGreaterThanOrEqual(9 - 0.5);
  });

  it('lets a passenger board only at the platform while the train is stopped', () => {
    const tr = make();
    const p = new THREE.Vector3(-25, 1.1, -2.6);
    expect(tr.canBoard(p)).toBe(false);
    run(tr, (x) => x.state === 'dwell');
    expect(tr.canBoard(p)).toBe(true);
    expect(tr.canBoard(new THREE.Vector3(-25, 0, 4))).toBe(false); // wrong side of the track
    expect(tr.canBoard(new THREE.Vector3(60, 0, -2.6))).toBe(false); // far away
  });

  it('kills nobody who rides it and reports a hit on the rails', () => {
    const tr = make();
    run(tr, (x) => x.state === 'move', 60);
    const on = new THREE.Vector3(tr.span()[0] + 5, 0, 0);
    expect(tr.hits(on)).toBe(true);
    expect(tr.hits(new THREE.Vector3(on.x, 0, 4))).toBe(false);
    tr.rider = true;
    expect(tr.hits(on)).toBe(false);
  });

  it('does not hit somebody standing on the platform deck, even at its edge', () => {
    const tr = make();
    run(tr, (x) => x.state === 'dwell');
    const x = (tr.span()[0] + tr.span()[1]) / 2;
    expect(tr.hits(new THREE.Vector3(x, 0.45, -1.5))).toBe(false); // deck edge (ground height is smoothed there)
    expect(tr.hits(new THREE.Vector3(x, -0.2, -1.0))).toBe(true); // still on the rails
  });

  it('turns around at the end of the line when carrying a passenger and comes back to stop', () => {
    const tr = make();
    run(tr, (x) => x.state === 'dwell');
    tr.rider = true;
    run(tr, (x) => x.dir === -1 && x.stopping, 300);
    expect(tr.dir).toBe(-1);
    run(tr, (x) => x.state === 'dwell', 300);
    expect(tr.state).toBe('dwell');
    expect(tr.front).toBeCloseTo(meta.platform.x0 + 2, 1);
  });

  it('hides the walls while a passenger looks out (single sided) and restores them', () => {
    const tr = make();
    tr.setFirstPerson(true);
    for (const m of tr.mats) expect(m.side).toBe(THREE.FrontSide);
    expect(tr.glassMesh.visible).toBe(false);
    tr.setFirstPerson(false);
    for (const m of tr.mats) expect(m.side).toBe(THREE.DoubleSide);
    expect(tr.glassMesh.visible).toBe(true);
  });
});
