"""Clothes: crew-neck T-shirt with rib collar, slim chino trousers, low-top sneakers, wrist watch (rest pose = A-pose)."""
import math
import random
from mathutils import Vector, Matrix
from mathutils import noise as mnoise
from char_core import *
from char_body import torso, limb, THIGH, SHANK, UPARM, FOREARM, _tab_at, SHIRT_TAB


def closed_path_tube(mb, pts, radial, rz, rr, n=8, tag=None, mat=0):
    """Tube (rz along the vertical, rr in the radial direction) around a closed path."""
    rings = []
    m = len(pts)
    for i in range(m):
        p = pts[i]
        rad = radial[i]
        ring = []
        for k in range(n):
            a = 2 * math.pi * k / n
            ring.append(mb.vert(p + rad * (rr * math.cos(a)) + Z * (rz * math.sin(a)), tag))
        rings.append(ring)
    for i in range(m):
        mb.bridge(rings[i], rings[(i + 1) % m], mat)


def tshirt(mb):
    """Regular-fit cotton tee.  Materials: 0 = fabric, 1 = rib collar / hem trim."""
    def flare(z):
        return 1.0 + 0.030 * smoothstep(0.98, 0.905, z)
    rings = torso(mb, ease=0.011, scale=1.045, mat=0, tag="shirt", z0=0.905, z1=1.445, nz=34, n=40, detail=True, fold=0.0026, flare=flare, tab=SHIRT_TAB, ease_fn=lambda z: 0.020 * smoothstep(1.16, 1.02, z))
    for sd in (1, -1):                                                                   # trapezius / shoulder-top filler
        mb.sphere(Vector((sd * 0.112, 0.0, 1.398)), 0.075, 14, 10, 0, 'shirt', (1.0, 1.0, 0.42))
    # neckline: the front dips 3.4 cm, the back stays high
    top = rings[-1]
    n = len(top)
    pts, rad = [], []
    for k, vi in enumerate(top):
        x, y, z = mb.v[vi]
        th = 2 * math.pi * k / n
        s_ = math.sin(th)
        if s_ < 0:
            z -= 0.038 * (-s_) ** 1.6
            mb.v[vi] = (x, y, z)
        c = Vector((0.0, 0.010, 0.0))
        r = Vector((x, y - 0.006, 0.0))
        r = r.normalized() if r.length > 1e-6 else Vector((0, -1, 0))
        pts.append(Vector((x, y, z)) + r * 0.002)
        rad.append(r)
    closed_path_tube(mb, pts, rad, 0.0095, 0.0036, 8, "shirt", 1)
    # hem trim
    rings0 = rings[0]
    pts, rad = [], []
    for vi in rings0:
        x, y, z = mb.v[vi]
        r = Vector((x, y - 0.006, 0.0)).normalized()
        pts.append(Vector((x, y, z + 0.008)))
        rad.append(r)
    closed_path_tube(mb, pts, rad, 0.007, 0.0028, 6, "shirt", 1)
    # sleeves (short, ending mid-biceps)
    for side in (1, -1):
        sn = "L" if side > 0 else "R"
        h, t = ARM_L["Arm"]
        p0, p1 = side_vec(h, side), side_vec(t, side)
        u, v, a = frame_along(p0, p1, X)
        prof = [(0.02, 0.050, 0.052), (0.10, 0.057, 0.059), (0.22, 0.061, 0.063), (0.38, 0.061, 0.066), (0.56, 0.060, 0.065), (0.60, 0.059, 0.064)]
        st = []
        for (tt, rx, ry) in prof:
            st.append((p0.lerp(p1, tt) + Z * (0.004 if tt > 0.05 else -0.004), u, v, rx * 0.97, ry * 0.97, 2.0))
        rings_s = mb.tube(st, 20, 0, "sleeve_" + sn, caps=(True, False))
        mb.sphere(p0 + Z * -0.008, 0.055, 14, 10, 0, "sleeve_" + sn, (1.0, 1.05, 1.0))                 # shoulder cap closes the armhole
        # fold noise
        for r_ in rings_s:
            for vi in r_:
                x, y, z = mb.v[vi]
                o = 0.0028 * mnoise.noise(Vector((x * 22, y * 22, z * 16)))
                mb.v[vi] = (x + o * (1 if x > 0 else -1) * 0.5, y + o, z)
        # hem trim: thin rib ring at the sleeve end (in the plane of the arm section)
        r_end = rings_s[-1]
        n_ = len(r_end)
        cc = p0.lerp(p1, 0.60) + Z * 0.004
        rings_h = []
        for zz in (0.0, 0.006):
            rings_h.append([mb.vert(Vector(mb.v[vi]) + a * zz + (Vector(mb.v[vi]) - cc).normalized() * (0.0015 if zz > 0 else 0.0), "sleeve_" + sn) for vi in r_end])
        mb.bridge(rings_h[0], rings_h[1], 1)


def trousers(mb):
    """Slim tapered chinos.  Materials: 0 = cloth, 1 = belt / waistband trim (dark), 2 = pocket lining."""
    torso(mb, ease=0.008, scale=1.03, mat=0, tag="pants_hip", z0=0.86, z1=1.045, nz=16, n=36, detail=False, fold=0.0012)
    mb.sphere(Vector((0.0, 0.006, 0.845)), 0.115, 18, 12, 0, "pants_hip", (1.28, 1.0, 0.78))               # crotch / seat filler
    for side in (1, -1):
        sn = "L" if side > 0 else "R"
        h, t = LEG_L["UpLeg"]
        p0, p1 = side_vec(h, side), side_vec(t, side)
        mb.sphere(p0, 0.108, 16, 12, 0, "pants_" + sn)                                                     # hip ball closes the thigh tube
        thigh = [(tt, rx + 0.010, ry + 0.010) for (tt, rx, ry, *_) in [(a, b, c) for (a, b, c) in THIGH]]
        rings = limb(mb, p0, p1, thigh, 20, 0, "pants_" + sn)
        h2, t2 = LEG_L["Leg"]
        q0, q1 = side_vec(h2, side), side_vec(t2, side)
        shank = [(0.00, 0.064, 0.066, 0.0), (0.16, 0.062, 0.070, 0.008), (0.34, 0.058, 0.070, 0.010), (0.62, 0.052, 0.058, 0.004), (0.88, 0.048, 0.050, 0.0),
                 (1.00, 0.047, 0.049, 0.0), (1.04, 0.0475, 0.050, 0.0)]
        # extend a little below the ankle (hem rests on the shoe)
        rings2 = limb(mb, q0, q1 + (q1 - q0).normalized() * 0.004, shank, 20, 0, "pants_" + sn)
        mb.bridge(rings[-1], rings2[0], 0)
        for rr in rings + rings2:
            for vi in rr:
                x, y, z = mb.v[vi]
                o = 0.0022 * mnoise.noise(Vector((x * 24, y * 24, z * 18)))
                mb.v[vi] = (x + o * 0.6, y + o, z)
    # belt loops / belt (dark) at the waist
    n = 36
    pts, rad = [], []
    hw, fr, bk, cy = _tab_at(1.03)
    for k in range(n):
        th = 2 * math.pi * k / n
        c_, s_ = math.cos(th), math.sin(th)
        e = 2.35
        px = (hw * 1.03 + 0.0075) * math.copysign(abs(c_) ** (2 / e), c_)
        sy = math.copysign(abs(s_) ** (2 / e), s_)
        py = ((fr if sy < 0 else bk) * 1.03 + 0.0075) * sy
        pts.append(Vector((px, cy + py, 1.033)))
        rad.append(Vector((px, py, 0)).normalized())
    closed_path_tube(mb, pts, rad, 0.0165, 0.0018, 6, "pants_hip", 1)
    mb.box(Vector((0, cy - fr * 1.03 - 0.0115, 1.033)), (0.038, 0.006, 0.030), 1, "pants_hip")            # buckle


def sneakers(mb, side):
    """White leather low-top: 0 = upper, 1 = rubber sole, 2 = laces / eyelets, 3 = dark lining / heel tab."""
    sn = "L" if side > 0 else "R"
    tag = "shoe_" + sn
    ax = side_vec(LEG_L["Foot"][0], side).x
    toe_out = 0.0
    up = [(0.090, 0.033, 0.066, 0.030), (0.062, 0.037, 0.098, 0.030), (0.020, 0.040, 0.108, 0.030), (-0.030, 0.043, 0.090, 0.030),
          (-0.085, 0.046, 0.068, 0.030), (-0.140, 0.047, 0.054, 0.030), (-0.185, 0.041, 0.042, 0.028), (-0.208, 0.028, 0.032, 0.026)]
    rings = []
    for (y, hw, zt, zb) in up:
        zc, rz = (zt + zb) / 2.0, (zt - zb) / 2.0
        rings.append(mb.ring(Vector((ax, y, zc)), X, Z, hw, rz, 16, 2.6, tag))
    for a, b in zip(rings, rings[1:]):
        mb.bridge(a, b, 0)
    mb.cap(rings[0], 0, top=False)
    mb.cap(rings[-1], 0, top=True)
    # rubber sole (cupsole)
    sole = [(0.094, 0.036, 0.0, 0.030), (0.060, 0.043, 0.0, 0.032), (0.000, 0.045, 0.0, 0.032), (-0.060, 0.049, 0.0, 0.032), (-0.120, 0.052, 0.004, 0.032),
            (-0.170, 0.047, 0.010, 0.032), (-0.203, 0.036, 0.016, 0.030), (-0.214, 0.026, 0.020, 0.028)]
    rs = []
    for (y, hw, zb, zt) in sole:
        rs.append(mb.ring(Vector((ax, y, (zb + zt) / 2.0)), X, Z, hw, (zt - zb) / 2.0, 14, 3.4, tag))
    for a, b in zip(rs, rs[1:]):
        mb.bridge(a, b, 1)
    mb.cap(rs[0], 1, top=False)
    mb.cap(rs[-1], 1, top=True)
    # collar padding (dark) around the ankle opening
    ring_pts, rad = [], []
    for k in range(14):
        a = 2 * math.pi * k / 14
        ring_pts.append(Vector((ax + 0.043 * math.cos(a), 0.030 + 0.048 * math.sin(a), 0.104)))
        rad.append(Vector((math.cos(a) * 0.0, 0, 1)))
    # tongue + laces
    for k in range(6):
        y = -0.012 - 0.021 * k
        zt = 0.108 - 0.0007 * (k * k) - 0.011 * k * 0.9 + 0.006
        zt = float(sorted(u[2] for u in up)[0])
        # top height at this y (interpolate the upper profile)
        for (y0, hw0, zt0, zb0), (y1, hw1, zt1, zb1) in zip(up, up[1:]):
            if y1 <= y <= y0:
                tt = (y0 - y) / (y0 - y1)
                zt = lerp(zt0, zt1, tt)
                hwl = lerp(hw0, hw1, tt)
                break
        for sgn in (-1, 1):                                       # eyelet stays
            mb.box(Vector((ax + sgn * 0.017, y, zt - 0.001)), (0.007, 0.012, 0.003), 2, tag)
        mb.box(Vector((ax, y, zt + 0.0022)), (0.040, 0.0038, 0.0035), 2, tag, Matrix.Rotation(math.radians(8 * (1 if k % 2 else -1)), 3, "Z"))
    # heel tab + toe cap seam
    mb.box(Vector((ax, 0.094, 0.062)), (0.020, 0.006, 0.030), 3, tag)


def watch(mb, side):
    """Simple black-dial analogue wristwatch on the left wrist (side = 1) with a dark strap."""
    h, t = ARM_L["ForeArm"]
    p0, p1 = side_vec(h, side), side_vec(t, side)
    u, v, a = frame_along(p0, p1, X)
    c = p0.lerp(p1, 0.90)
    tag = "watch_" + ("L" if side > 0 else "R")
    # strap
    st = [(c + a * dz, u, v, 0.0285, 0.0235, 2.0) for dz in (-0.013, 0.0, 0.013)]
    mb.tube(st, 18, 0, tag)
    # case on the outer (dorsal) side = +u for the left arm ... the dorsal side of a hanging forearm faces away from the palm (palm faces the body)
    dorsal = (u if side > 0 else -u) * 0.0 + Vector((1.0 if side > 0 else -1.0, 0.0, 0.0))
    cc = c + dorsal * 0.0295
    axis = dorsal
    for r_, z0, z1, m in ((0.0195, 0.000, 0.0085, 1), (0.0155, 0.0085, 0.0092, 2)):
        rings = []
        w = axis.cross(a).normalized()
        w2 = axis.cross(w).normalized()
        for zz in (z0, z1):
            ring = []
            for k in range(20):
                ang = 2 * math.pi * k / 20
                ring.append(mb.vert(cc + axis * zz + w * (r_ * math.cos(ang)) + w2 * (r_ * math.sin(ang)), tag))
            rings.append(ring)
        mb.bridge(rings[0], rings[1], m)
        mb.cap(rings[1], m, top=True)
