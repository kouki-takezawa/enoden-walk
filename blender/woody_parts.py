"""Woody (Toy Story) - geometry of the procedural character: cartoon head / face, hair, cowboy hat, plaid shirt, cow-hide vest, bandana,
jeans + belt + holster, cowboy boots, sheriff badge, pull-string ring.

Built on the same skeleton / mesh builder as the 20s-male character (char_core.MB, rest A-pose, +Z up, faces -Y, his left = +X);
woody.py lengthens the neck / head bones before anything is built.  The legs keep the male skeleton, so the gait code of char_anim
works unchanged.  Every part is tagged per vertex for char_rig.skin_object."""
import math
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from mathutils import noise as mnoise
from char_core import *
import char_body as CB
from char_cloth import closed_path_tube

# slim torso: the male table, narrower and flatter
WOODY_TAB = [(z, hw * 0.88, fr * 0.92, bk * 0.92, cy) for (z, hw, fr, bk, cy) in CB.TORSO_TAB]


def sgnpow(c, p):
    return math.copysign(abs(c) ** p, c)


def path_tube(mb, pts, radii, n=16, mat=0, tag=None, hint=X, caps=(False, False), e=2.0):
    """Tube through points; radii[k] = r or (r_lateral, r_front).  Frames follow the local tangent."""
    pts = [Vector(p) for p in pts]
    m = len(pts)
    st = []
    for k in range(m):
        a = (pts[min(k + 1, m - 1)] - pts[max(k - 1, 0)]).normalized()
        u = hint - a * hint.dot(a)
        if u.length < 1e-6:
            u = Y - a * a.y
        u.normalize()
        v = a.cross(u)
        r = radii[k]
        rx, ry = (r, r) if not isinstance(r, tuple) else r
        st.append((pts[k], u, v, rx, ry, e))
    return mb.tube(st, n, mat, tag, caps)


def loop_tube(mb, pts, normals, r, n=6, mat=0, tag=None, closed=True):
    """Thin tube along a (closed) poly-line lying on a surface; normals = surface normals at the points."""
    m = len(pts)
    rings = []
    for k in range(m):
        if closed:
            t = (pts[(k + 1) % m] - pts[(k - 1) % m]).normalized()
        else:
            t = (pts[min(k + 1, m - 1)] - pts[max(k - 1, 0)]).normalized()
        u = normals[k] - t * normals[k].dot(t)
        u.normalize()
        v = t.cross(u)
        rings.append([mb.vert(pts[k] + u * (r * math.cos(2 * math.pi * i / n)) + v * (r * math.sin(2 * math.pi * i / n)), tag) for i in range(n)])
    for k in range(m if closed else m - 1):
        mb.bridge(rings[k], rings[(k + 1) % m], mat)


def torus(mb, c, axis, R, r, n=24, nm=8, mat=0, tag=None):
    axis = Vector(axis).normalized()
    u = (Z if abs(axis.z) < 0.9 else X) - axis * axis.dot(Z if abs(axis.z) < 0.9 else X)
    u.normalize()
    v = axis.cross(u)
    rings = []
    for i in range(n):
        a = 2 * math.pi * i / n
        d = u * math.cos(a) + v * math.sin(a)
        p = Vector(c) + d * R
        rings.append([mb.vert(p + d * (r * math.cos(2 * math.pi * k / nm)) + axis * (r * math.sin(2 * math.pi * k / nm)), tag) for k in range(nm)])
    for i in range(n):
        mb.bridge(rings[i], rings[(i + 1) % n], mat)


def bvh_of(*mbs):
    verts, polys = [], []
    for mb in mbs:
        b = len(verts)
        verts += [Vector(v) for v in mb.v]
        polys += [tuple(i + b for i in f) for f in mb.f]
    return BVHTree.FromPolygons(verts, polys)


def cast(bvh, origin, direction, outward_from=None):
    loc, nrm, idx, dist = bvh.ray_cast(Vector(origin), Vector(direction).normalized())
    if loc is None:
        raise RuntimeError("ray missed the surface at %s" % (tuple(origin),))
    if outward_from is not None and nrm.dot(loc - Vector(outward_from)) < 0:
        nrm = -nrm
    elif outward_from is None and nrm.dot(Vector(direction)) > 0:
        nrm = -nrm
    return loc, nrm


def front_hit(bvh, x, z, center=None):
    return cast(bvh, (x, -1.0, z), (0, 1, 0), center)


# ------------------------------------------------------------------------------------------------------ head
# z, half width, front depth, back depth, centre y.  Long face, big chin, head top at 1.845 m (covered by the hat).
HEAD_TAB = [
    (1.468, 0.014, 0.010, 0.010, -0.070),
    (1.476, 0.040, 0.022, 0.024, -0.068),
    (1.490, 0.058, 0.032, 0.040, -0.060),
    (1.510, 0.069, 0.040, 0.056, -0.050),
    (1.535, 0.078, 0.048, 0.072, -0.040),
    (1.565, 0.085, 0.056, 0.086, -0.030),
    (1.600, 0.091, 0.066, 0.096, -0.022),
    (1.640, 0.092, 0.074, 0.103, -0.016),
    (1.680, 0.095, 0.078, 0.107, -0.012),
    (1.720, 0.096, 0.078, 0.108, -0.008),
    (1.760, 0.093, 0.072, 0.104, -0.004),
    (1.795, 0.084, 0.060, 0.094, 0.000),
    (1.820, 0.068, 0.046, 0.076, 0.004),
    (1.836, 0.044, 0.030, 0.050, 0.006),
    (1.845, 0.010, 0.008, 0.012, 0.008),
]
HEAD_Z0, HEAD_Z1 = HEAD_TAB[0][0], HEAD_TAB[-1][0]
HEAD_CENTER = Vector((0.0, -0.010, 1.660))
EYE_X, EYE_Z, EYE_R, EYE_SCALE = 0.037, 1.681, 0.0275, (1.0, 0.92, 1.10)
MOUTH_Z, MOUTH_W = 1.558, 0.046


def _catmull(p0, p1, p2, p3, t):
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t * t * t)


def head_row(z):
    tab = HEAD_TAB
    z = clamp(z, tab[0][0], tab[-1][0])
    for i in range(len(tab) - 1):
        if z <= tab[i + 1][0]:
            break
    a, b = tab[max(i - 1, 0)], tab[i]
    c, d = tab[i + 1], tab[min(i + 2, len(tab) - 1)]
    t = (z - b[0]) / (c[0] - b[0])
    out = [_catmull(a[k], b[k], c[k], d[k], t) for k in range(1, 5)]
    return max(out[0], 0.002), max(out[1], 0.002), max(out[2], 0.002), out[3]


def face_relief(px, z, f):
    """Forward (-Y) displacement of the front of the head: nose, sockets, brow, cheeks, muzzle, chin.  f = frontness 0..1."""
    ax = abs(px)
    dy = 0.0
    dy -= 0.022 * gauss(px, z - 1.628, 0.016, 0.030)                 # nose
    dy -= 0.014 * gauss(px, z - 1.608, 0.022, 0.016)                 # round nose tip
    dy -= 0.006 * gauss(px, z - 1.665, 0.011, 0.020)                 # bridge
    dy += 0.009 * gauss(ax - 0.040, z - 1.678, 0.020, 0.016)         # eye sockets
    dy -= 0.005 * gauss(ax - 0.040, z - 1.709, 0.028, 0.010)         # brow ridge
    dy -= 0.011 * gauss(ax - 0.056, z - 1.598, 0.024, 0.024)         # cheeks (smiling)
    dy -= 0.006 * gauss(px, z - 1.570, 0.038, 0.022)                 # muzzle / upper lip
    dy += 0.0025 * gauss(px, z - 1.556, 0.036, 0.006)                # mouth crease
    dy -= 0.010 * gauss(px, z - 1.492, 0.028, 0.018)                 # chin
    return dy * f


def head_point(z, th, ease=0.0, features=True):
    hw, fr, bk, cy = head_row(z)
    e = 2.25
    c, s = math.cos(th), math.sin(th)
    px = (hw + ease) * sgnpow(c, 2.0 / e)
    sy = sgnpow(s, 2.0 / e)
    py = ((fr if sy < 0 else bk) + ease) * sy
    dy = face_relief(px, z, -sy) if (features and sy < 0) else 0.0
    return Vector((px, cy + py + dy, z)), (-sy if sy < 0 else 0.0)


def head_mesh(mb, n=96, nz=100):
    rings = []
    for i in range(nz):
        t = i / (nz - 1)
        z = HEAD_Z0 + (HEAD_Z1 - HEAD_Z0) * (1 - math.cos(math.pi * t)) / 2
        ring = []
        for k in range(n):
            th = 2 * math.pi * k / n
            p, f = head_point(z, th)
            vi = mb.vert(p, "head")
            ax = abs(p.x)
            mb.attr.setdefault("cheek", {})[vi] = gauss(ax - 0.058, z - 1.598, 0.020, 0.016) * f
            ring.append(vi)
        rings.append(ring)
    for a, b in zip(rings, rings[1:]):
        mb.bridge(a, b, 0)
    mb.cap(rings[0], 0, top=True)
    mb.cap(rings[-1], 0, top=False)
    return bvh_of(mb)


def ear(mb, side):
    hw, fr, bk, cy = head_row(1.645)
    c = Vector((side * (hw + 0.004), cy + 0.030, 1.645))
    mb.sphere(c, 0.032, 16, 10, 0, "head", (0.32, 0.62, 1.0))
    mb.sphere(c + Vector((side * 0.006, -0.004, 0.0)), 0.020, 12, 8, 0, "head", (0.25, 0.50, 0.85))


def eye_centre(bvh, side):
    loc, nrm = front_hit(bvh, side * EYE_X, EYE_Z, HEAD_CENTER)
    return Vector((side * EYE_X, loc.y + 0.013, EYE_Z))


def _scaled(c, d, r):
    return c + Vector((d.x * r * EYE_SCALE[0], d.y * r * EYE_SCALE[1], d.z * r * EYE_SCALE[2]))


def eyeball(mb, c, side, nseg=40, nring=28):
    """Sphere with its pole at the front, attribute eyedot = cos(angle from the gaze)."""
    gaze = Vector((-side * 0.06, -1.0, -0.02)).normalized()         # a little cross-eyed toward the viewer, slightly down
    u = X - gaze * gaze.dot(X)
    u.normalize()
    v = gaze.cross(u)
    front = mb.vert(_scaled(c, gaze, EYE_R), "eye")
    mb.attr.setdefault("eyedot", {})[front] = 1.0
    rings = []
    for j in range(1, nring):
        al = math.pi * j / nring
        ring = []
        for i in range(nseg):
            b = 2 * math.pi * i / nseg
            d = gaze * math.cos(al) + (u * math.cos(b) + v * math.sin(b)) * math.sin(al)
            vi = mb.vert(_scaled(c, d, EYE_R), "eye")
            mb.attr["eyedot"][vi] = math.cos(al)
            ring.append(vi)
        rings.append(ring)
    back = mb.vert(_scaled(c, -gaze, EYE_R), "eye")
    mb.attr["eyedot"][back] = -1.0
    for i in range(nseg):
        j = (i + 1) % nseg
        mb.face((front, rings[0][i], rings[0][j]))
        mb.face((back, rings[-1][j], rings[-1][i]))
    for a, b in zip(rings, rings[1:]):
        mb.bridge(a, b, 0)


def eyelid(mb, c, th_max=0.96, nseg=40, nring=10):
    """Upper lid: a cap over the eyeball from the top down to th_max (rad from +Z); attribute lash = dark rim."""
    rings = []
    for j in range(nring + 1):
        th = 0.02 + (th_max - 0.02) * j / nring
        rr = 1.085 if j < nring else 1.04
        ring = []
        for i in range(nseg):
            b = 2 * math.pi * i / nseg
            d = Vector((math.sin(th) * math.cos(b), math.sin(th) * math.sin(b), math.cos(th)))
            vi = mb.vert(_scaled(c, d, EYE_R * rr), "head")
            mb.attr.setdefault("lash", {})[vi] = 1.0 if j >= nring - 1 else 0.0
            ring.append(vi)
        rings.append(ring)
    # tuck the rim under
    th = th_max + 0.06
    ring = []
    for i in range(nseg):
        b = 2 * math.pi * i / nseg
        d = Vector((math.sin(th) * math.cos(b), math.sin(th) * math.sin(b), math.cos(th)))
        vi = mb.vert(_scaled(c, d, EYE_R * 1.005), "head")
        mb.attr["lash"][vi] = 1.0
        ring.append(vi)
    rings.append(ring)
    for a, b in zip(rings, rings[1:]):
        mb.bridge(a, b, 0)
    mb.cap(rings[0], 0, top=False)


def brow(mb, bvh, side):
    xs = [0.010 + 0.064 * i / 9 for i in range(10)]
    pts, nrms = [], []
    for x in xs:
        t = (x - 0.010) / 0.064
        z = 1.724 + 0.017 * math.sin(math.pi * (0.12 + 0.8 * t)) - 0.006 * t
        loc, nrm = front_hit(bvh, side * x, z, HEAD_CENTER)
        pts.append(loc + nrm * 0.0035)
        nrms.append(nrm)
    st = []
    m = len(pts)
    for k in range(m):
        t = (pts[min(k + 1, m - 1)] - pts[max(k - 1, 0)]).normalized()
        u = nrms[k] - t * nrms[k].dot(t)
        u.normalize()
        v = t.cross(u)
        f = k / (m - 1)
        h = 0.0040 + 0.0080 * math.sin(math.pi * (0.25 + 0.7 * f)) ** 0.8
        st.append((pts[k], u, v, 0.0038, h, 2.4))
    mb.tube(st, 10, 0, "head", caps=(True, True))


def mouth_edges(x):
    t = clamp(abs(x) / MOUTH_W)
    top = 0.004 + 0.012 * t * t
    bot = -0.024 * (1 - t * t) + 0.016 * t * t
    return bot, top


def mouth(mb_in, mb_line, bvh, cols=30, rows=12):
    """Open grin painted on the face surface: dark inside, upper teeth, tongue (attribute mouthv 0 bottom -> 1 top) + a lip outline."""
    grid = []
    for i in range(cols + 1):
        x = -MOUTH_W + 2 * MOUTH_W * i / cols
        x *= 0.999
        bot, top = mouth_edges(x)
        col = []
        for j in range(rows + 1):
            w = j / rows
            z = MOUTH_Z + lerp(bot, top, w)
            loc, nrm = front_hit(bvh, x, z, HEAD_CENTER)
            vi = mb_in.vert(loc + nrm * 0.0012, "head")
            mb_in.attr.setdefault("mouthv", {})[vi] = w
            col.append(vi)
        grid.append(col)
    for i in range(cols):
        for j in range(rows):
            mb_in.face((grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]))
    # outline (top edge left->right, bottom edge right->left)
    pts, nrms = [], []
    for i in range(cols + 1):
        x = (-MOUTH_W + 2 * MOUTH_W * i / cols) * 0.999
        loc, nrm = front_hit(bvh, x, MOUTH_Z + mouth_edges(x)[1], HEAD_CENTER)
        pts.append(loc + nrm * 0.0014)
        nrms.append(nrm)
    for i in range(cols - 1, 0, -1):
        x = (-MOUTH_W + 2 * MOUTH_W * i / cols) * 0.999
        loc, nrm = front_hit(bvh, x, MOUTH_Z + mouth_edges(x)[0], HEAD_CENTER)
        pts.append(loc + nrm * 0.0014)
        nrms.append(nrm)
    loop_tube(mb_line, pts, nrms, 0.0019, 6, 0, "head")


HAIRLINE = [(0.0, 1.790), (0.70, 1.780), (0.98, 1.725), (1.08, 1.622), (1.27, 1.622), (1.37, 1.700), (1.85, 1.690), (2.15, 1.575), (math.pi, 1.550)]


def hairline(d):
    for (d0, z0), (d1, z1) in zip(HAIRLINE, HAIRLINE[1:]):
        if d <= d1:
            t = (d - d0) / (d1 - d0)
            return lerp(z0, z1, t * t * (3 - 2 * t))
    return HAIRLINE[-1][1]


def hair(mb, n=96, rows=34):
    """Short brown hair shell from the hairline (sideburns in front of the ears, nape at the back) to the crown."""
    cols = []
    top = HEAD_Z1 - 0.0005
    for k in range(n):
        th = 2 * math.pi * k / n
        d = abs(((th - 1.5 * math.pi + math.pi) % (2 * math.pi)) - math.pi)          # angle from the face centre
        hl = hairline(d)
        if math.cos(th) > 0:                                              # lock of hair on his left forehead, under the brim
            hl -= 0.042 * math.exp(-((d - 0.62) / 0.24) ** 2)
        col = []
        for j in range(rows):
            t = j / (rows - 1)
            z = lerp(hl, top, 1 - (1 - t) ** 1.4)
            off = 0.0012 + 0.0072 * smoothstep(0.0, 0.10, t)
            p, f = head_point(z, th, ease=0.0)
            q, _ = head_point(z, th, ease=off)
            q += Vector((0, 0, 0.004 * smoothstep(0.0, 0.10, t)))
            o = 0.0022 * mnoise.noise(Vector((q.x * 60, q.y * 60, q.z * 25)))
            radial = (q - Vector((0, q.y * 0 + head_row(z)[3], z)))
            radial = Vector((q.x, q.y - head_row(z)[3], 0)).normalized() if radial.length > 1e-6 else Vector((0, 0, 1))
            vi = mb.vert(q + radial * o * smoothstep(0.0, 0.2, t), "head")
            col.append(vi)
        cols.append(col)
    for k in range(n):
        a, b = cols[k], cols[(k + 1) % n]
        for j in range(rows - 1):
            mb.face((a[j], b[j], b[j + 1], a[j + 1]))
    mb.cap([c[-1] for c in cols], 0, top=False)


# ------------------------------------------------------------------------------------------------------ hat
HAT_BASE = Vector((0.0, 0.012, 1.762))
HAT_TILT = math.radians(-6.0)                    # negative = front brim up (hat pushed back a little)
CROWN_RX, CROWN_RY = 0.113, 0.119


def hat_matrix():
    return Matrix.Translation(HAT_BASE) @ Matrix.Rotation(HAT_TILT, 4, "X")


def hat(mb, n=72):
    """Crown with a centre crease + front pinches, band, wide brim curled up at the sides with a rolled edge.
    Materials: 0 felt, 1 band.  Built in hat space then moved onto the head."""
    M = hat_matrix()
    b0 = len(mb.v)
    prof = [(1.0, 0.000), (1.0, 0.030), (0.988, 0.070), (0.965, 0.104), (0.925, 0.128), (0.85, 0.143), (0.72, 0.150), (0.55, 0.153),
            (0.36, 0.154), (0.18, 0.154), (0.05, 0.154)]
    rings = []
    for rf, z in prof:
        ring = []
        for k in range(n):
            ph = 2 * math.pi * k / n
            c, s = math.cos(ph), math.sin(ph)
            x, y = CROWN_RX * rf * c, CROWN_RY * rf * s
            zz = z
            hz = smoothstep(0.06, 0.15, z)
            zz -= 0.040 * math.exp(-(x / 0.038) ** 2) * hz * (0.6 + 0.4 * (1 - rf))          # centre crease front-to-back
            if s < 0:                                                                        # front pinches
                pin = hz * (-s) ** 2 * 0.16
                x *= 1.0 - pin * (1.0 - 0.6 * (1 - rf))
            if rf > 0.9:
                zz += 0.012 * (-s) * hz * 0.0
            ring.append(mb.vert((x, y, zz), "hat"))
        rings.append(ring)
    for a, b in zip(rings, rings[1:]):
        mb.bridge(a, b, 0)
    mb.cap(rings[-1], 0, top=False)
    # band
    band = []
    for z in (0.002, 0.026):
        band.append([mb.vert((CROWN_RX * 1.024 * math.cos(2 * math.pi * k / n), CROWN_RY * 1.024 * math.sin(2 * math.pi * k / n), z), "hat") for k in range(n)])
    mb.bridge(band[0], band[1], 1)
    # brim
    brim = []
    OX, OY = 0.268, 0.252
    nr = 9
    for j in range(nr + 1):
        t = j / nr
        ring = []
        for k in range(n):
            ph = 2 * math.pi * k / n
            c, s = math.cos(ph), math.sin(ph)
            x = lerp(CROWN_RX, OX, t) * c
            y = lerp(CROWN_RY, OY, t) * s
            z = 0.068 * t ** 2.2 * abs(c) ** 2.4 - 0.014 * t ** 2 * abs(s) ** 2 + 0.006 * t ** 2 * (1 if s < 0 else 0) * abs(s) ** 4
            ring.append(mb.vert((x, y, z), "hat"))
        brim.append(ring)
    for a, b in zip(brim, brim[1:]):
        mb.bridge(a, b, 0)
    # rolled edge
    edge = [Vector(mb.v[i]) for i in brim[-1]]
    nr_ = []
    for k in range(n):
        p0, p1 = edge[(k - 1) % n], edge[(k + 1) % n]
        tng = (p1 - p0).normalized()
        out = Vector((edge[k].x, edge[k].y, 0)).normalized()
        up = tng.cross(out).normalized()
        if up.z < 0:
            up = -up
        nr_.append(up)
    loop_tube(mb, edge, nr_, 0.0065, 8, 0, "hat")
    # stitching: short light dashes just inside the rolled edge (material 2)
    tb = 0.90

    def brim_pt(ph_):
        c, s_ = math.cos(ph_), math.sin(ph_)
        return Vector((lerp(CROWN_RX, OX, tb) * c, lerp(CROWN_RY, OY, tb) * s_,
                       0.068 * tb ** 2.2 * abs(c) ** 2.4 - 0.014 * tb ** 2 * abs(s_) ** 2 + 0.006 * tb ** 2 * (1 if s_ < 0 else 0) * abs(s_) ** 4))
    ns = 110
    for k in range(ns):
        ph = 2 * math.pi * (k + 0.5) / ns
        p = brim_pt(ph)
        tg = (brim_pt(ph + 0.01) - brim_pt(ph - 0.01)).normalized()
        outv = Vector((p.x, p.y, 0)).normalized()
        up = tg.cross(outv).normalized()
        if up.z < 0:
            up = -up
        sd = up.cross(tg).normalized()
        R = Matrix((tg, sd, up)).transposed()
        mb.box(p + up * 0.0038, (0.0085, 0.0028, 0.0018), 2, "hat", R)
    # to head space
    mb.v[b0:] = [tuple(M @ Vector(p)) for p in mb.v[b0:]]


# ------------------------------------------------------------------------------------------------------ neck, hands
def neck(mb):
    path_tube(mb, [(0, -0.004, 1.385), (0, -0.008, 1.45), (0, -0.012, 1.52), (0, -0.014, 1.565)], [0.047, 0.043, 0.041, 0.040], 20, 0, "neck", X)


def hands(mb, fingers):
    for side, sn in ((1, "L"), (-1, "R")):
        CB.hand_skin(mb, side, fingers[sn])
        hh, ht = ARM_L["Hand"]
        fh, ft = ARM_L["ForeArm"]
        w = side_vec(hh, side)
        d = (side_vec(ft, side) - side_vec(fh, side)).normalized()
        path_tube(mb, [w - d * 0.06, w - d * 0.03, w + d * 0.004], [0.030, 0.029, (0.030, 0.018)], 14, 0, "hand_" + sn, -Y)


# ------------------------------------------------------------------------------------------------------ shirt, vest, bandana
def shirt(mb):
    """Long-sleeved yellow plaid shirt tucked into the jeans.  Materials: 0 plaid, 1 cuffs."""
    CB.torso(mb, ease=0.006, scale=1.0, mat=0, tag="shirt", z0=0.95, z1=1.445, nz=30, n=40, detail=False, fold=0.0018, tab=WOODY_TAB)
    for sd in (1, -1):
        mb.sphere(Vector((sd * 0.100, 0.0, 1.396)), 0.064, 14, 10, 0, "shirt", (1.0, 1.0, 0.42))
    for side in (1, -1):
        sn = "L" if side > 0 else "R"
        p0 = side_vec(ARM_L["Arm"][0], side)
        el = side_vec(ARM_L["ForeArm"][0], side)
        wr = side_vec(ARM_L["Hand"][0], side)
        d = (wr - el).normalized()
        pts = [p0, p0.lerp(el, 0.33), p0.lerp(el, 0.66), el, el.lerp(wr, 0.33), el.lerp(wr, 0.66), wr - d * 0.030]
        rad = [0.050, 0.048, 0.045, 0.043, 0.041, 0.039, 0.037]
        rings = path_tube(mb, pts, rad, 20, 0, "sleeve_" + sn, X)
        for r_ in rings[1:-1]:
            for vi in r_:
                x, y, z = mb.v[vi]
                o = 0.0022 * mnoise.noise(Vector((x * 22, y * 22, z * 16)))
                mb.v[vi] = (x + o * 0.5 * side, y + o, z)
        mb.sphere(p0 + Z * -0.006, 0.052, 16, 10, 0, "sleeve_" + sn, (1.0, 1.05, 1.0))
        path_tube(mb, [wr - d * 0.034, wr - d * 0.004], [0.0395, 0.0385], 20, 1, "sleeve_" + sn, X)


VEST_EASE = 0.012


def vest_open_w(z):
    return 0.020 + 0.050 * smoothstep(1.10, 1.44, z)


def _vest_pt(z, th):
    hw, fr, bk, cy = CB._tab_at(z, WOODY_TAB)
    e = 2.35
    c, s = math.cos(th), math.sin(th)
    px = (hw + VEST_EASE + 0.004 * (1 - smoothstep(1.34, 1.44, z))) * sgnpow(c, 2 / e)
    sy = sgnpow(s, 2 / e)
    py = ((fr if sy < 0 else bk) + VEST_EASE) * sy
    return Vector((px, cy + py, z)), sy, c


def _vest_hole(z, th):
    p, sy, c = _vest_pt(z, th)
    if sy < 0 and abs(p.x) < vest_open_w(z):                                              # open front
        return True
    ang = math.acos(min(1.0, abs(c)))                                                     # 0 at the side seam
    return (ang / 0.78) ** 2 + ((z - 1.300) / 0.118) ** 2 < 1.0                           # arm hole


def vest(mb, n=64, nz=30):
    """Open-front cow-hide vest (single surface; woody.py adds thickness).  Arm holes on the sides.  Grid vertices next to a hole
    are slid along their row onto the hole boundary, so the edges are smooth instead of stair-stepped."""
    z0, z1 = 1.06, 1.448
    grid, keep = [], []
    step = 2 * math.pi / n
    for i in range(nz):
        z = lerp(z0, z1, i / (nz - 1))
        holes = [_vest_hole(z, step * k) for k in range(n)]
        row = []
        for k in range(n):
            th = step * k
            if not holes[k]:
                for nb in (-1, 1):
                    if holes[(k + nb) % n]:
                        a, b = th, th + nb * step                                           # a kept, b in the hole
                        for _ in range(14):
                            m = (a + b) / 2
                            if _vest_hole(z, m):
                                b = m
                            else:
                                a = m
                        th = a
                        break
            row.append(mb.vert(_vest_pt(z, th)[0], "shirt"))
        grid.append(row)
        keep.append([not h for h in holes])
    for i in range(nz - 1):
        for k in range(n):
            j = (k + 1) % n
            quad = [(i, k), (i, j), (i + 1, j), (i + 1, k)]
            kept = [grid[a][b_] for a, b_ in quad if keep[a][b_]]
            if len(kept) >= 3:                                   # a triangle closes the diagonal steps of the boundary
                mb.face(tuple(kept))


def collars(mb, bvh):
    """Pointed shirt-collar tips lying over the vest opening."""
    for side in (1, -1):
        tri = [(0.020, 1.442), (0.074, 1.428), (0.060, 1.342)]
        N = 5
        idx = {}
        for a in range(N + 1):
            for b in range(N + 1 - a):
                w0, w1 = a / N, b / N
                w2 = 1 - w0 - w1
                x = side * (tri[0][0] * w2 + tri[1][0] * w0 + tri[2][0] * w1)
                z = tri[0][1] * w2 + tri[1][1] * w0 + tri[2][1] * w1
                loc, nrm = front_hit(bvh, x, z)
                idx[(a, b)] = mb.vert(loc + nrm * 0.0065 + Vector((0, -0.002 * w1, 0)), "shirt")
        for a in range(N):
            for b in range(N - a):
                mb.face((idx[(a, b)], idx[(a + 1, b)], idx[(a, b + 1)]))
                if b + 1 <= N - a - 1:
                    mb.face((idx[(a + 1, b)], idx[(a + 1, b + 1)], idx[(a, b + 1)]))


def bandana(mb, bvh):
    """Red polka-dot neckerchief: roll around the neck, knot with two ends on his left side."""
    n = 32
    pts, rad = [], []
    for k in range(n):
        a = 2 * math.pi * k / n
        r = 0.057 + 0.004 * max(0.0, -math.sin(a))
        pts.append(Vector((r * math.cos(a), -0.008 + r * math.sin(a), 1.436 - 0.010 * max(0.0, -math.sin(a)) ** 2)))
        rad.append(Vector((math.cos(a), math.sin(a), 0)))
    closed_path_tube(mb, pts, rad, 0.015, 0.009, 10, "shirt", 0)
    # knot on his left, a little to the front, with the two ends sticking out
    a = math.radians(-38)
    k = Vector((0.066 * math.cos(a), -0.008 + 0.066 * math.sin(a), 1.432))
    mb.sphere(k, 0.017, 12, 8, 0, "shirt", (1.0, 0.85, 1.1))
    out = Vector((math.cos(a), math.sin(a), 0.0))
    for dz, L in ((0.020, 0.060), (-0.018, 0.052)):
        tip = k + out * L + Vector((0.012, 0.004, dz))
        mid = k.lerp(tip, 0.5) + Vector((0, 0, dz * 0.3))
        path_tube(mb, [k, mid, tip], [(0.016, 0.004), (0.013, 0.0035), (0.002, 0.0015)], 10, 0, "shirt", Z, caps=(False, True))


def badge(mb, bvh):
    """Gold five-pointed sheriff star with round tips on his left chest.  mat 0."""
    loc, nrm = front_hit(bvh, 0.090, 1.275)
    c = loc + nrm * 0.004
    u = X - nrm * nrm.dot(X)
    u.normalize()
    v = nrm.cross(u)
    if v.z < 0:
        v = -v
    outline = []
    for i in range(10):
        a = math.pi / 2 + 2 * math.pi * i / 10
        r = 0.038 if i % 2 == 0 else 0.0165
        outline.append((math.cos(a) * r, math.sin(a) * r))
    rings = []
    for h in (0.0, 0.0055):
        rings.append([mb.vert(c + u * x + v * y + nrm * h, "shirt") for x, y in outline])
    mb.bridge(rings[0], rings[1], 0)
    mb.cap(rings[1], 0, top=False)
    mb.cap(rings[0], 0, top=True)
    for i in range(0, 10, 2):
        x, y = outline[i]
        mb.sphere(c + u * x * 1.04 + v * y * 1.04 + nrm * 0.003, 0.0065, 10, 6, 0, "shirt")
    mb.sphere(c + nrm * 0.0055, 0.0115, 16, 6, 0, "shirt", (1, 1, 0.30))


def pull_ring(mb, bvh):
    loc, nrm = cast(bvh, (0.0, 1.0, 1.20), (0, -1, 0))
    c = loc + nrm * 0.004 + Vector((0, 0, -0.018))
    torus(mb, c, nrm, 0.016, 0.0042, 24, 8, 0, "shirt")
    path_tube(mb, [loc - nrm * 0.004, loc + nrm * 0.004, c + Vector((0, 0, 0.012))], [0.0022, 0.0022, 0.0022], 6, 0, "shirt", X)


# ------------------------------------------------------------------------------------------------------ jeans, belt, holster
def jeans(mb):
    """Blue jeans (0), brown belt (1), gold buckle (2)."""
    CB.torso(mb, ease=0.012, scale=1.03, mat=0, tag="pants_hip", z0=0.86, z1=1.05, nz=14, n=40, detail=False, fold=0.0012, tab=WOODY_TAB)
    mb.sphere(Vector((0.0, 0.006, 0.850)), 0.100, 18, 12, 0, "pants_hip", (1.20, 1.0, 0.80))
    for side in (1, -1):
        sn = "L" if side > 0 else "R"
        hp, kn = side_vec(LEG_L["UpLeg"][0], side), side_vec(LEG_L["UpLeg"][1], side)
        an = side_vec(LEG_L["Leg"][1], side)
        mb.sphere(hp, 0.080, 16, 12, 0, "pants_" + sn)
        pts = [hp, hp.lerp(kn, 0.15), hp.lerp(kn, 0.40), hp.lerp(kn, 0.70), kn, kn.lerp(an, 0.22), kn.lerp(an, 0.50), kn.lerp(an, 0.80),
               an + Vector((0, -0.004, 0.0)), an + Vector((0, -0.006, -0.016))]
        rad = [0.082, 0.078, 0.070, 0.062, 0.056, 0.056, 0.052, 0.053, 0.057, 0.060]
        rings = path_tube(mb, pts, rad, 22, 0, "pants_" + sn, X)
        for r_ in rings[1:-1]:
            for vi in r_:
                x, y, z = mb.v[vi]
                o = 0.0022 * mnoise.noise(Vector((x * 24, y * 24, z * 18)))
                mb.v[vi] = (x + o * 0.6, y + o, z)
    # belt
    n = 40
    pts, rad = [], []
    zb = 1.034
    hw, fr, bk, cy = CB._tab_at(zb, WOODY_TAB)
    e = 2.35
    for k in range(n):
        th = 2 * math.pi * k / n
        c_, s_ = math.cos(th), math.sin(th)
        px = (hw * 1.03 + 0.019) * sgnpow(c_, 2 / e)
        sy = sgnpow(s_, 2 / e)
        py = ((fr if sy < 0 else bk) * 1.03 + 0.019) * sy
        pts.append(Vector((px, cy + py, zb)))
        rad.append(Vector((px, py, 0)).normalized())
    closed_path_tube(mb, pts, rad, 0.018, 0.0025, 6, "pants_hip", 1)
    yf = cy - fr * 1.03 - 0.022
    # big oval buckle
    rings = []
    for dy, sc in ((0.0, 1.0), (-0.004, 0.96), (-0.006, 0.80)):
        rings.append([mb.vert((0.034 * sc * math.cos(2 * math.pi * k / 20), yf + dy, zb + 0.024 * sc * math.sin(2 * math.pi * k / 20)), "pants_hip") for k in range(20)])
    mb.bridge(rings[0], rings[1], 2)
    mb.bridge(rings[1], rings[2], 2)
    mb.cap(rings[2], 2, top=True)


def holster(mb):
    """Empty leather holster hanging from the belt on his right hip (1 = leather)."""
    side = -1
    pts = [(-0.172, 0.028, 1.040), (-0.180, 0.030, 0.990), (-0.184, 0.034, 0.925), (-0.182, 0.040, 0.860), (-0.177, 0.046, 0.805), (-0.172, 0.050, 0.785)]
    rad = [(0.010, 0.040), (0.013, 0.042), (0.015, 0.040), (0.015, 0.034), (0.013, 0.026), (0.010, 0.016)]
    path_tube(mb, pts, rad, 14, 1, "pants_R", X, caps=(True, True), e=2.6)


# ------------------------------------------------------------------------------------------------------ boots
def boot(mb, side):
    """Brown cowboy boot: pointed toe, stacked heel, shaft (hidden under the jeans).  0 leather, 1 sole / heel, 2 stitching."""
    sn = "L" if side > 0 else "R"
    tag = "shoe_" + sn
    ax = side_vec(LEG_L["Foot"][0], side).x
    up = [(0.094, 0.031, 0.100, 0.036), (0.072, 0.038, 0.128, 0.032), (0.030, 0.041, 0.142, 0.026), (-0.020, 0.042, 0.120, 0.016),
          (-0.070, 0.044, 0.091, 0.012), (-0.120, 0.043, 0.069, 0.012), (-0.165, 0.035, 0.055, 0.012), (-0.200, 0.022, 0.043, 0.014),
          (-0.222, 0.008, 0.032, 0.018)]
    rings = []
    for (y, hw, zt, zb) in up:
        rings.append(mb.ring(Vector((ax, y, (zt + zb) / 2)), X, Z, hw, (zt - zb) / 2, 18, 2.5, tag))
    for a, b in zip(rings, rings[1:]):
        mb.bridge(a, b, 0)
    mb.cap(rings[0], 0, top=False)
    mb.cap(rings[-1], 0, top=True)
    # sole: bottom rises over the arch, thin toe spring
    def sole_bottom(y):
        if y > 0.028:
            return 0.033
        if y > -0.050:
            return lerp(0.0, 0.033, smoothstep(-0.050, 0.028, y))
        if y > -0.190:
            return 0.0
        return 0.006 * smoothstep(-0.190, -0.228, y)
    sl = [(0.095, 0.032), (0.060, 0.041), (0.028, 0.043), (-0.010, 0.044), (-0.050, 0.046), (-0.100, 0.047), (-0.150, 0.042), (-0.190, 0.029), (-0.215, 0.016), (-0.228, 0.005)]
    rs = []
    for (y, hw) in sl:
        zb = sole_bottom(y)
        rs.append(mb.ring(Vector((ax, y, zb + 0.0065)), X, Z, hw, 0.0065, 16, 4.0, tag))
    for a, b in zip(rs, rs[1:]):
        mb.bridge(a, b, 1)
    mb.cap(rs[0], 1, top=False)
    mb.cap(rs[-1], 1, top=True)
    # stacked heel (slightly tapered block)
    hr = []
    for z, s in ((0.0, 0.88), (0.034, 1.0)):
        hr.append(mb.ring(Vector((ax, 0.062, z)), X, Y, 0.031 * s, 0.033 * s, 16, 3.5, tag))
    mb.bridge(hr[0], hr[1], 1)
    mb.cap(hr[0], 1, top=True)
    # shaft (inside the jeans) + decorative stitch ring on the vamp
    path_tube(mb, [(ax, 0.022, 0.100), (ax, 0.006, 0.170), (ax, 0.004, 0.290)], [(0.040, 0.046), (0.042, 0.043), (0.044, 0.044)], 18, 0, tag, X)
    pts, nrms = [], []
    for k in range(12):
        t = k / 11
        y = lerp(-0.030, -0.195, t)
        hw_ = 0.030 * (1 - 0.75 * t)
        for (y0, w0, zt0, zb0), (y1, w1, zt1, zb1) in zip(up, up[1:]):
            if y1 <= y <= y0:
                tt = (y0 - y) / (y0 - y1)
                zt = lerp(zt0, zt1, tt)
                break
        pts.append(Vector((ax, y, zt + 0.0012)))
        nrms.append(Vector((0, -0.3, 1)).normalized())
    loop_tube(mb, pts, nrms, 0.0015, 5, 2, tag, closed=False)


def shirt_buttons(mb, bvh):
    """White snap buttons down the shirt front (visible in the vest opening)."""
    for z in (1.375, 1.285, 1.195, 1.105):
        loc, nrm = front_hit(bvh, 0.0, z)
        mb.sphere(loc + nrm * 0.002, 0.0072, 14, 6, 0, "shirt", (1.0, 0.35, 1.0))


def vest_trim(mb, vest_mb):
    """White whip-stitched piping along every open edge of the vest (front opening, hem, arm holes, neck)."""
    from collections import defaultdict
    cnt = defaultdict(int)
    for f in vest_mb.f:
        for i in range(len(f)):
            cnt[tuple(sorted((f[i], f[(i + 1) % len(f)])))] += 1
    adj = defaultdict(list)
    for (a, b), c in cnt.items():
        if c == 1:
            adj[a].append(b)
            adj[b].append(a)
    seen = set()
    for start in list(adj):
        if start in seen:
            continue
        loop = [start]
        seen.add(start)
        prev, cur = None, start
        while True:
            nxt = [v for v in adj[cur] if v != prev and v not in seen]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            loop.append(cur)
            seen.add(cur)
        if len(loop) < 4:
            continue
        closed = start in adj[loop[-1]]
        pts = [Vector(vest_mb.v[i]) for i in loop]
        nrms = [Vector((p.x, p.y, 0)).normalized() for p in pts]
        loop_tube(mb, pts, nrms, 0.0042, 6, 0, "shirt", closed=closed)
