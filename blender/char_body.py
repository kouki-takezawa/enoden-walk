"""Body geometry: torso, limbs, hands, feet (skin) and the clothes shells.  Everything is built from lofted superellipse rings in the
rest (A-pose) skeleton of char_core, tagged per vertex for the skin-weight pass."""
import math
import random
from mathutils import Vector, Matrix
from char_core import *

# ------------------------------------------------------------------------------------------------------ torso
# z, half width, front depth, back depth, centre y   (male 171 cm, slim-athletic; chest 35 cm wide at the armpits, waist 28 cm)
TORSO_TAB = [
    (0.830, 0.150, 0.100, 0.105, 0.010),
    (0.880, 0.165, 0.102, 0.118, 0.010),
    (0.940, 0.171, 0.100, 0.122, 0.010),
    (1.000, 0.160, 0.094, 0.110, 0.008),
    (1.060, 0.143, 0.090, 0.098, 0.006),
    (1.130, 0.147, 0.094, 0.098, 0.004),
    (1.200, 0.157, 0.102, 0.098, 0.002),
    (1.270, 0.168, 0.112, 0.100, 0.000),
    (1.330, 0.175, 0.112, 0.100, -0.002),
    (1.370, 0.176, 0.100, 0.096, -0.002),
    (1.400, 0.138, 0.082, 0.090, 0.000),
    (1.423, 0.086, 0.068, 0.078, 0.004),
    (1.445, 0.060, 0.058, 0.064, 0.010),
]


SHIRT_TAB = [t for t in TORSO_TAB]
SHIRT_TAB[-4] = (1.370, 0.181, 0.104, 0.098, -0.002)
SHIRT_TAB[-3] = (1.400, 0.170, 0.086, 0.092, 0.000)
SHIRT_TAB[-2] = (1.423, 0.108, 0.070, 0.079, 0.004)
SHIRT_TAB[-1] = (1.445, 0.062, 0.058, 0.064, 0.010)


def _tab_at(z, tab=TORSO_TAB):
    if z <= tab[0][0]:
        return tab[0][1:]
    for a, b in zip(tab, tab[1:]):
        if z <= b[0]:
            t = (z - a[0]) / (b[0] - a[0])
            t = t * t * (3 - 2 * t) * 0.35 + t * 0.65
            return tuple(lerp(a[i], b[i], t) for i in range(1, 5))
    return tab[-1][1:]


def torso(mb, ease=0.0, scale=1.0, mat=0, tag="torso", z0=0.83, z1=1.445, nz=30, n=32, detail=True, cy_shift=0.0, fold=0.0, flare=None, tab=None, ease_fn=None):
    """Loft the torso.  ease = offset for clothing (metres), scale multiplies the half widths, detail adds pecs / back / glutes."""
    rings = []
    zs = [lerp(z0, z1, i / (nz - 1)) for i in range(nz)]
    e = 2.35
    for z in zs:
        hw, fr, bk, cy = _tab_at(z, tab or TORSO_TAB)
        e_ = ease + (ease_fn(z) if ease_fn else 0.0)
        hw, fr, bk = hw * scale + e_, fr * scale + e_, bk * scale + e_
        ring = []
        for k in range(n):
            th = 2.0 * math.pi * k / n
            s_, c_ = math.sin(th), math.cos(th)
            px = hw * math.copysign(abs(c_) ** (2.0 / e), c_)
            sy = math.copysign(abs(s_) ** (2.0 / e), s_)
            py = (fr if sy < 0 else bk) * sy
            dy = 0.0
            if detail:
                fx = abs(px)
                if sy < 0:                                                   # front: pecs, abs, sternal groove
                    dy -= 0.014 * gauss(fx - 0.078, z - 1.290, 0.055, 0.040) * -sy
                    dy += 0.004 * gauss(fx - 0.030, z - 1.150, 0.028, 0.055) * -sy
                    dy += 0.003 * gauss(fx, z - 1.290, 0.010, 0.05) * -sy
                else:                                                        # back: scapulae, spine groove, glutes
                    dy += 0.010 * gauss(fx - 0.070, z - 1.300, 0.055, 0.050) * sy
                    dy += 0.006 * gauss(fx - 0.080, z - 0.900, 0.060, 0.050) * sy
                    dy -= 0.004 * gauss(fx, z - 1.20, 0.008, 0.20) * sy
            if fold:                                                             # cloth wrinkles: radial noise, stronger near the hem
                from mathutils import noise as _nz
                rad = math.hypot(px, py) + 1e-6
                amp = fold * (1.0 + 1.2 * smoothstep(1.02, 0.90, z))
                o = amp * _nz.noise(Vector((px * 26.0, py * 26.0, z * 16.0)))
                px, py = px + px / rad * o, py + py / rad * o
            if flare is not None:
                k_ = flare(z)
                px, py = px * k_, py * k_
            ring.append(mb.vert((px, cy + cy_shift + py + dy, z), tag))
        rings.append(ring)
    for a, b in zip(rings, rings[1:]):
        mb.bridge(a, b, mat)
    return rings


# ------------------------------------------------------------------------------------------------------ limbs
def limb(mb, p0, p1, prof, n=16, mat=0, tag=None, side_hint=X, offs=None, caps=(False, False), ease=0.0, e=2.0):
    """prof: [(t, rx, ry[, dy_shift])] along p0->p1 (rx lateral, ry front/back)."""
    u, v, a = frame_along(p0, p1, side_hint)
    st = []
    for item in prof:
        t, rx, ry = item[:3]
        shift = item[3] if len(item) > 3 else 0.0
        c = Vector(p0).lerp(Vector(p1), t) + Vector((0, 1, 0)) * shift
        st.append((c, u, v, rx + ease, ry + ease, e))
    return mb.tube(st, n, mat, tag, caps)


THIGH = [(0.00, 0.098, 0.100), (0.12, 0.092, 0.096), (0.32, 0.081, 0.082), (0.60, 0.069, 0.070), (0.86, 0.057, 0.059), (1.00, 0.054, 0.056)]
SHANK = [(0.00, 0.054, 0.056), (0.14, 0.055, 0.060, 0.008), (0.30, 0.056, 0.063, 0.012), (0.60, 0.043, 0.048, 0.006), (0.88, 0.032, 0.036), (1.00, 0.031, 0.034)]
UPARM = [(0.00, 0.038, 0.040), (0.12, 0.044, 0.046), (0.42, 0.042, 0.046), (0.80, 0.036, 0.038), (1.00, 0.034, 0.036)]
FOREARM = [(0.00, 0.036, 0.039), (0.20, 0.038, 0.040), (0.55, 0.031, 0.031), (0.90, 0.025, 0.021), (1.00, 0.025, 0.020)]


def arm_skin(mb, side, n=16):
    sn = "L" if side > 0 else "R"
    h, t = ARM_L["Arm"]
    limb(mb, side_vec(h, side), side_vec(t, side), UPARM, n, 0, "arm_" + sn)
    h, t = ARM_L["ForeArm"]
    limb(mb, side_vec(h, side), side_vec(t, side), FOREARM, n, 0, "arm_" + sn)


def leg_skin(mb, side, n=18):
    sn = "L" if side > 0 else "R"
    r_thigh = limb(mb, side_vec(LEG_L["UpLeg"][0], side), side_vec(LEG_L["UpLeg"][1], side), THIGH, n, 0, "leg_" + sn)
    h, t = LEG_L["Leg"]
    r_shank = limb(mb, side_vec(h, side), side_vec(t, side), SHANK, n, 0, "leg_" + sn)
    mb.bridge(r_thigh[-1], r_shank[0], 0)
    # foot: heel -> toes, low wedge
    ax = side_vec(LEG_L["Foot"][0], side).x
    rings = []
    ys = [(0.075, 0.030, 0.034, 0.045), (0.040, 0.034, 0.042, 0.052), (0.000, 0.036, 0.044, 0.048), (-0.050, 0.040, 0.030, 0.034),
          (-0.110, 0.045, 0.019, 0.022), (-0.185, 0.038, 0.013, 0.016)]
    for (y, rx, rz, zc) in ys:
        rings.append(mb.ring(Vector((ax, y, zc)), X, Z, rx, rz, 12, 2.4, "foot_" + sn))
    for r0, r1 in zip(rings, rings[1:]):
        mb.bridge(r0, r1, 0)
    mb.cap(rings[0], 0, top=False)
    mb.cap(rings[-1], 0, top=True)


# ------------------------------------------------------------------------------------------------------ hands
FINGER_TAB = {   # name: (offset y from the knuckle centre, offset x, segment lengths, radii at the joints)
    "Index": (-0.028, 0.002, (0.043, 0.025, 0.021), (0.0093, 0.0085, 0.0076, 0.0064)),
    "Middle": (-0.009, 0.003, (0.047, 0.029, 0.022), (0.0096, 0.0088, 0.0078, 0.0066)),
    "Ring": (0.010, 0.002, (0.043, 0.027, 0.021), (0.0090, 0.0082, 0.0074, 0.0062)),
    "Pinky": (0.027, -0.001, (0.034, 0.020, 0.019), (0.0078, 0.0070, 0.0064, 0.0055)),
}
CURL = {"Index": (10, 22, 14), "Middle": (14, 26, 16), "Ring": (18, 30, 18), "Pinky": (22, 34, 20), "Thumb": (6, 12, 8)}


def finger_chain(head, direction, bend_axis, lengths, curls_deg):
    """Points of a finger: joint positions P0..P3 curling around bend_axis (rotating direction toward the palm)."""
    pts = [Vector(head)]
    d = Vector(direction).normalized()
    ang = 0.0
    for L, c in zip(lengths, curls_deg):
        ang += math.radians(c)
        dd = Matrix.Rotation(ang, 3, bend_axis) @ d
        pts.append(pts[-1] + dd * L)
    return pts


def _finger_tube(mb, pts, rad, tag):
    """One continuous tube through the joint positions (no gaps between phalanges); frames follow the local tangent."""
    st = []
    n = len(pts)
    for k in range(n):
        a = (pts[min(k + 1, n - 1)] - pts[max(k - 1, 0)]).normalized()
        u = (X - a * X.dot(a))
        u.normalize()
        v = a.cross(u)
        r0 = rad[k] if k < len(rad) else rad[-1]
        st.append((pts[k], u, v, r0 * 1.02, r0 * 0.92))
        if k < n - 1:                                            # mid-phalanx station keeps the segment slightly waisted
            r1 = rad[k + 1] if k + 1 < len(rad) else rad[-1]
            mid = pts[k].lerp(pts[k + 1], 0.5)
            st.append((mid, u, v, (r0 + r1) / 2 * 0.93, (r0 + r1) / 2 * 0.86))
    mb.tube(st, 8, 0, tag, caps=(False, True))


def hand_skin(mb, side, fingers_out, n=10):
    """Palm + 5 fingers.  fingers_out[name] = [(head, tail), ...] for the rig.  Palm faces the thigh, thumb to the front."""
    sn = "L" if side > 0 else "R"
    hh, ht = ARM_L["Hand"]
    wrist = Vector(side_vec(hh, side))
    knuckle = Vector(side_vec(ht, side))
    u, v, a = frame_along(wrist, knuckle, -Y)              # u = front->back (-Y projected... ) : lateral hint = -Y
    # u points to the front (-Y), v = a x u; thickness axis is v
    st = [(wrist, u, v, 0.031, 0.018), (wrist.lerp(knuckle, 0.45), u, v, 0.037, 0.017), (wrist.lerp(knuckle, 0.85), u, v, 0.042, 0.015),
          (knuckle, u, v, 0.043, 0.0135)]
    rings = []
    for c, uu, vv, rx, ry in st:
        rings.append(mb.ring(c, uu, vv, rx, ry, 12, 2.6, "hand_" + sn))
    for r0, r1 in zip(rings, rings[1:]):
        mb.bridge(r0, r1, 0)
    mb.cap(rings[-1], 0, top=True)
    palm_n = Vector((-1.0 if side > 0 else 1.0, 0.0, 0.0))          # palm normal: toward the body
    bend_axis = a.cross(palm_n)                                      # rotating a about this axis moves the finger toward palm_n
    if (Matrix.Rotation(0.3, 3, bend_axis) @ a).dot(palm_n) < 0:
        bend_axis = -bend_axis
    for name, (oy, ox, lens, rad) in FINGER_TAB.items():
        head = knuckle + Vector((ox * (1 if side > 0 else -1) * -1, oy, -0.004))
        pts = finger_chain(head, a, bend_axis, lens, CURL[name])
        fingers_out[name] = list(zip(pts[:-1], pts[1:]))
        _finger_tube(mb, pts, rad, "finger_%s_%s" % (sn, name))
    # thumb: from the base of the palm (front side), pointing forward-down
    tb = wrist + Vector((0.0, -0.030, -0.018))
    td = Vector((0.0, -0.62, -0.78))
    tp = finger_chain(tb, td, bend_axis, (0.048, 0.034, 0.029), CURL["Thumb"])
    fingers_out["Thumb"] = list(zip(tp[:-1], tp[1:]))
    trad = (0.0125, 0.0108, 0.0092, 0.0078)
    _finger_tube(mb, tp, trad, "finger_%s_Thumb" % sn)
    # thenar pad
    mb.sphere(wrist + Vector((0.0, -0.022, -0.030)), 0.020, 8, 6, 0, "hand_" + sn, (0.7, 1.0, 1.25))


# ------------------------------------------------------------------------------------------------------ neck
def neck_skin(mb):
    st = []
    prof = [(1.395, 0.062, 0.062, 0.004), (1.43, 0.058, 0.058, 0.002), (1.46, 0.055, 0.057, 0.001), (1.495, 0.052, 0.056, 0.0), (1.535, 0.050, 0.054, -0.004)]
    rings = []
    for z, rx, ry, cy in prof:
        rings.append(mb.ring(Vector((0, cy, z)), X, Y, rx, ry, 20, 2.1, "neck"))
    for a, b in zip(rings, rings[1:]):
        mb.bridge(a, b, 0)
    # Adam's apple + sternocleidomastoid hints
    for i in rings[2]:
        x, y, z = mb.v[i]
        if y < 0:
            mb.v[i] = (x, y - 0.004 * gauss(x, 0, 0.012, 1) * 1.0, z)
