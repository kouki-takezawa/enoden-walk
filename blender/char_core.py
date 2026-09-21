"""Shared helpers for the Japanese-man-in-his-20s character (mesh builder, anthropometry, skeleton definition).

Units: metres.  +Z up, the character faces -Y, his left side is +X.  Standing height 1.71 m (average Japanese man in his 20s: 171 cm)."""
import math
import random
from mathutils import Vector, Matrix, Quaternion, Euler

HEIGHT = 1.71
X = Vector((1.0, 0.0, 0.0))
Y = Vector((0.0, 1.0, 0.0))
Z = Vector((0.0, 0.0, 1.0))


def clamp(v, a=0.0, b=1.0):
    return a if v < a else (b if v > b else v)


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(e0, e1, x):
    if e0 == e1:
        return 0.0 if x < e0 else 1.0
    t = clamp((x - e0) / (e1 - e0))
    return t * t * (3.0 - 2.0 * t)


def gauss(dx, dz, sx, sz):
    return math.exp(-((dx / sx) ** 2 + (dz / sz) ** 2))


def V(*a):
    return Vector(a)


def mirror_x(v):
    return Vector((-v[0], v[1], v[2]))


# ------------------------------------------------------------------------------------------------------ skeleton (rest pose)
# Rest pose = relaxed A-pose, armature space.  Only the LEFT side (+X) is listed; the right side is mirrored.
SPINE = {
    "Hips": ((0.0, 0.010, 0.930), (0.0, 0.010, 1.020)),
    "Spine": ((0.0, 0.010, 1.020), (0.0, 0.006, 1.140)),
    "Spine1": ((0.0, 0.006, 1.140), (0.0, 0.000, 1.270)),
    "Spine2": ((0.0, 0.000, 1.270), (0.0, -0.004, 1.395)),
    "Neck": ((0.0, -0.004, 1.395), (0.0, -0.002, 1.500)),
    "Head": ((0.0, -0.002, 1.500), (0.0, -0.002, 1.710)),
}
ARM_L = {
    "Shoulder": ((0.020, -0.030, 1.398), (0.170, 0.000, 1.378)),
    "Arm": ((0.170, 0.000, 1.378), (0.2345, 0.000, 1.076)),
    "ForeArm": ((0.2345, 0.000, 1.076), (0.2705, -0.027, 0.822)),
    "Hand": ((0.2705, -0.027, 0.822), (0.2800, -0.033, 0.722)),
}
LEG_L = {
    "UpLeg": ((0.088, 0.000, 0.905), (0.092, -0.008, 0.490)),
    "Leg": ((0.092, -0.008, 0.490), (0.090, 0.008, 0.088)),
    "Foot": ((0.090, 0.008, 0.088), (0.090, -0.115, 0.032)),
    "Toe": ((0.090, -0.115, 0.032), (0.090, -0.190, 0.022)),
}
HEAD_C = Vector((0.0, 0.006, 1.5975))            # skull centre (head bone rotates about the atlas at z=1.50)


def side_vec(v, side):
    return Vector(v) if side > 0 else mirror_x(v)


def bone_defs():
    """name -> (head, tail, parent, connected) for every bone of the skeleton (no fingers; see finger_defs)."""
    d = {}
    d["Root"] = (V(0, 0, 0), V(0, 0, 0.12), None, False)
    order = ["Hips", "Spine", "Spine1", "Spine2", "Neck", "Head"]
    par = {"Hips": "Root", "Spine": "Hips", "Spine1": "Spine", "Spine2": "Spine1", "Neck": "Spine2", "Head": "Neck"}
    for n in order:
        h, t = SPINE[n]
        d[n] = (Vector(h), Vector(t), par[n], n not in ("Hips",))
    for side, sn in ((1, "Left"), (-1, "Right")):
        prev = "Spine2"
        for n, (h, t) in ARM_L.items():
            name = sn + n
            par_ = prev if n != "Shoulder" else "Spine2"
            d[name] = (side_vec(h, side), side_vec(t, side), par_, n not in ("Shoulder",))
            prev = name
        prev = "Hips"
        for n, (h, t) in LEG_L.items():
            name = sn + n
            d[name] = (side_vec(h, side), side_vec(t, side), prev if n == "UpLeg" else prev, n != "UpLeg")
            prev = name
    # facial bones
    d["Jaw"] = (Vector((0.0, -0.004, 1.545)), Vector((0.0, -0.075, 1.510)), "Head", False)
    for side, sn in ((1, "Left"), (-1, "Right")):
        d[sn + "Eye"] = (side_vec((0.0325, -0.0690, 1.5950), side), side_vec((0.0325, -0.100, 1.5950), side), "Head", False)
    return d


# fingers: (name, base offset from wrist in hand-local, lengths, radii); built in char_body.  Finger bone names:  Left<Finger><1..3>
FINGERS = ("Thumb", "Index", "Middle", "Ring", "Pinky")


# ------------------------------------------------------------------------------------------------------ mesh builder
class MB:
    """Vertices / faces / material indices / per-vertex tags & attributes."""

    def __init__(self):
        self.v = []
        self.f = []
        self.m = []
        self.tag = []                 # per vertex: string tag (used for skin weights)
        self.attr = {}                # name -> {vertex index: float}
        self.uv = {}                  # face index -> [(u, v), ...]
        self.smooth = True

    def vert(self, p, tag=None):
        self.v.append((float(p[0]), float(p[1]), float(p[2])))
        self.tag.append(tag)
        return len(self.v) - 1

    def face(self, idx, mat=0, uv=None):
        self.f.append(tuple(idx))
        self.m.append(mat)
        if uv is not None:
            self.uv[len(self.f) - 1] = uv

    def ring(self, c, u, v, rx, ry, n, e=2.0, tag=None, fn=None, phase=0.0):
        """Superellipse ring; fn(theta, px, py) -> (dx, dy) optional shape offset in the ring plane."""
        out = []
        for i in range(n):
            th = 2.0 * math.pi * i / n + phase
            ct, st = math.cos(th), math.sin(th)
            px = rx * math.copysign(abs(ct) ** (2.0 / e), ct)
            py = ry * math.copysign(abs(st) ** (2.0 / e), st)
            if fn is not None:
                dx, dy = fn(th, px, py)
                px += dx
                py += dy
            out.append(self.vert(c + u * px + v * py, tag))
        return out

    def bridge(self, r0, r1, mat=0, close=True, flip=False):
        n = len(r0)
        for i in range(n):
            j = (i + 1) % n
            if not close and j == 0:
                break
            q = (r0[i], r0[j], r1[j], r1[i])
            self.face(q[::-1] if flip else q, mat)

    def cap(self, r, mat=0, top=True, tag=None):
        c = sum((Vector(self.v[i]) for i in r), Vector()) / len(r)
        ci = self.vert(c, tag if tag else self.tag[r[0]])
        n = len(r)
        for i in range(n):
            j = (i + 1) % n
            self.face((ci, r[j], r[i]) if top else (ci, r[i], r[j]), mat)

    def tube(self, stations, n=14, mat=0, tag=None, caps=(False, False), fn=None, phase=0.0):
        """stations: [(centre, u, v, rx, ry[, exponent]), ...] along an axis with u x v = axis direction."""
        rings = []
        for st in stations:
            c, u, v, rx, ry = st[:5]
            e = st[5] if len(st) > 5 else 2.0
            rings.append(self.ring(Vector(c), u, v, rx, ry, n, e, tag, fn, phase))
        for a, b in zip(rings, rings[1:]):
            self.bridge(a, b, mat)
        if caps[0]:
            self.cap(rings[0], mat, top=False)
        if caps[1]:
            self.cap(rings[-1], mat, top=True)
        return rings

    def sphere(self, c, r, segs=12, rings=8, mat=0, tag=None, scale=(1, 1, 1)):
        c = Vector(c)
        top = self.vert(c + Vector((0, 0, r * scale[2])), tag)
        rs = []
        for j in range(1, rings):
            th = math.pi * j / rings
            rs.append([self.vert(c + Vector((r * scale[0] * math.sin(th) * math.cos(2 * math.pi * i / segs),
                                              r * scale[1] * math.sin(th) * math.sin(2 * math.pi * i / segs),
                                              r * scale[2] * math.cos(th))), tag) for i in range(segs)])
        bot = self.vert(c - Vector((0, 0, r * scale[2])), tag)
        for i in range(segs):
            j = (i + 1) % segs
            self.face((top, rs[0][j], rs[0][i]), mat)
            self.face((bot, rs[-1][i], rs[-1][j]), mat)
        for a, b in zip(rs, rs[1:]):
            for i in range(segs):
                j = (i + 1) % segs
                self.face((a[i], a[j], b[j], b[i]), mat)
        return top

    def box(self, c, s, mat=0, tag=None, R=None):
        hx, hy, hz = s[0] / 2, s[1] / 2, s[2] / 2
        idx = []
        for sx, sy, sz in ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)):
            p = Vector((sx * hx, sy * hy, sz * hz))
            if R is not None:
                p = R @ p
            idx.append(self.vert(Vector(c) + p, tag))
        for q in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            self.face([idx[i] for i in q], mat)

    def transform(self, M):
        self.v = [tuple(M @ Vector(p)) for p in self.v]

    def append(self, o):
        b = len(self.v)
        self.v += o.v
        self.tag += o.tag
        for i, f in enumerate(o.f):
            self.f.append(tuple(k + b for k in f))
            self.m.append(o.m[i])
            if i in o.uv:
                self.uv[len(self.f) - 1] = o.uv[i]
        for k, d in o.attr.items():
            self.attr.setdefault(k, {}).update({i + b: val for i, val in d.items()})
        return b


def frame_along(p0, p1, side_hint=X):
    """Right-handed frame (u, v, a) for a limb from p0 to p1: a = axis, u = lateral (side_hint projected), v = a x u  (u x v = a)."""
    a = (Vector(p1) - Vector(p0)).normalized()
    u = (side_hint - a * side_hint.dot(a))
    if u.length < 1e-6:
        u = Vector((0, 1, 0)) - a * a.y
    u.normalize()
    v = a.cross(u)
    return u, v, a
