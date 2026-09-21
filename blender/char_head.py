"""Head: skull + face relief (East-Asian male, 20s), ears, eyeballs, eyelids, lips, eyebrows, hair.
All positions are metres in the rest pose (character faces -Y, left = +X).  The skull is a displaced sphere; the eyelids, lips, ears, brows and
hair are separate lofted meshes placed on the skull surface with a BVH ray-cast."""
import math
import random
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from char_core import *

HZ = HEAD_C.z                                             # 1.5975
RX, RY, RZ = 0.0775, 0.097, 0.1125                        # head breadth 15.5 cm, length 19.4 cm, height 22.5 cm
EYE_X, EYE_Z, EYE_R = 0.0325, 1.5950, 0.0125
EYE_Y = -0.0690              # pupil distance 65 mm, eyeball radius 12 mm


def _face_relief(x, z_rel, out):
    """Forward (-Y) displacement of the face at (|x|, z relative to the head centre)."""
    ax = abs(x)
    d = 0.0
    d += 0.004 * gauss(ax, z_rel - 0.055, 0.050, 0.030)                       # forehead
    d += 0.006 * gauss(ax - 0.030, z_rel - 0.024, 0.027, 0.008)               # brow ridge
    d += 0.003 * gauss(ax, z_rel - 0.020, 0.012, 0.012)                       # glabella
    d -= 0.0050 * gauss(ax - EYE_X, z_rel + 0.000, 0.020, 0.0125)             # eye socket
    d += 0.008 * gauss(ax, z_rel + 0.000, 0.009, 0.020)                       # nasal root (low bridge)
    d += 0.018 * gauss(ax, z_rel + 0.026, 0.0100, 0.016)                      # bridge -> tip
    d += 0.024 * gauss(ax, z_rel + 0.046, 0.0130, 0.0095)                     # nose tip
    d += 0.013 * gauss(ax - 0.0185, z_rel + 0.046, 0.0080, 0.0080)            # alae
    d -= 0.008 * gauss(ax - 0.009, z_rel + 0.056, 0.0040, 0.0030)             # nostrils
    d -= 0.0015 * gauss(ax, z_rel + 0.060, 0.0045, 0.006)                     # philtrum
    d += 0.007 * gauss(ax, z_rel + 0.064, 0.026, 0.010)                       # muzzle (lips sit on it)
    d += 0.004 * gauss(ax, z_rel + 0.084, 0.024, 0.008)                       # lower-lip base / mentolabial
    d -= 0.004 * gauss(ax, z_rel + 0.088, 0.020, 0.0035)                      # mentolabial groove
    d += 0.010 * gauss(ax, z_rel + 0.105, 0.022, 0.014)                       # chin
    d += 0.004 * gauss(ax - 0.058, z_rel + 0.025, 0.021, 0.020)               # cheekbones (broad, flat)
    d -= 0.004 * gauss(ax - 0.046, z_rel + 0.070, 0.020, 0.020)               # cheek hollow / masseter
    d -= 0.0022 * gauss(ax - 0.028, z_rel + 0.062, 0.0045, 0.020)             # nasolabial fold
    d += 0.003 * gauss(ax - 0.026, z_rel + 0.012, 0.012, 0.007)               # lower-lid roll
    return d


# z relative to the head centre, half width, front depth, back depth  (male skull + mandible; lower rows = jaw underside)
HEAD_TAB = [
    (-0.1125, 0.012, 0.058, 0.030),
    (-0.1080, 0.030, 0.072, 0.040),
    (-0.0950, 0.045, 0.080, 0.056),
    (-0.0800, 0.054, 0.084, 0.072),
    (-0.0600, 0.0600, 0.0865, 0.084),
    (-0.0350, 0.0655, 0.0895, 0.092),
    (-0.0050, 0.0715, 0.0930, 0.097),
    (0.0250, 0.0755, 0.0940, 0.101),
    (0.0550, 0.0775, 0.0880, 0.101),
    (0.0800, 0.0725, 0.0730, 0.092),
    (0.0985, 0.0570, 0.0530, 0.068),
    (0.1090, 0.0360, 0.0340, 0.044),
    (0.1125, 0.0080, 0.0080, 0.010),
]


def _head_tab(zr):
    tab = HEAD_TAB
    if zr <= tab[0][0]:
        return tab[0][1:]
    for a, b in zip(tab, tab[1:]):
        if zr <= b[0]:
            t = (zr - a[0]) / (b[0] - a[0])
            t = t * t * (3 - 2 * t) * 0.4 + t * 0.6
            return tuple(lerp(a[i], b[i], t) for i in range(1, 4))
    return tab[-1][1:]


def head_point(zr, ph):
    """Row height zr (relative to the head centre) and angle ph (0 = +X, -pi/2 = straight ahead) -> point on the skull / face."""
    hw, fr, bk = _head_tab(zr)
    e = 2.35 + 0.35 * smoothstep(-0.03, -0.09, zr)                              # squarer around the jaw
    c, s = math.cos(ph), math.sin(ph)
    sx = math.copysign(abs(c) ** (2.0 / e), c)
    sy = math.copysign(abs(s) ** (2.0 / e), s)
    x = hw * sx
    y = (fr * sy) if sy < 0 else (bk * sy)                                       # sy < 0 = front (-Y)
    wf = smoothstep(-0.30, -0.75, sy)
    y -= _face_relief(x, zr, 0.0) * wf
    return Vector((x, y + HEAD_C.y, zr + HZ))


def build_head(mb, nseg=112, nring=112):
    """Skull mesh; returns the BVH.  Point attributes: lip / brow / nostril / cheek / eyering (for the skin shader)."""
    tag = "head"
    zlo, zhi = HEAD_TAB[0][0], HEAD_TAB[-1][0]
    top = mb.vert(Vector((0.0, HEAD_C.y, HZ + zhi)), tag)
    rings = []
    for j in range(1, nring):
        t = j / nring
        zr = lerp(zhi, zlo, t)
        ring = []
        for i in range(nseg):
            ph = 2 * math.pi * i / nseg
            ring.append(mb.vert(head_point(zr, ph), tag))
        rings.append(ring)
    bot = mb.vert(Vector((0.0, HEAD_C.y - 0.020, HZ + zlo)), tag)
    for i in range(nseg):
        j = (i + 1) % nseg
        mb.face((top, rings[0][i], rings[0][j]), 0)
        mb.face((bot, rings[-1][j], rings[-1][i]), 0)
    for a, b in zip(rings, rings[1:]):
        for i in range(nseg):
            j = (i + 1) % nseg
            mb.face((a[i], b[i], b[j], a[j]), 0)
    # skin-shader masks
    for k in ("lip", "brow", "nostril", "cheek", "eyering"):
        mb.attr[k] = {}
    for i, (x, y, z) in enumerate(mb.v):
        if y > -0.03:
            continue
        zr, ax = z - HZ, abs(x)
        lip = gauss(ax, zr + 0.070, 0.022, 0.0075) * 1.0 + gauss(ax, zr + 0.080, 0.021, 0.006)
        mb.attr["lip"][i] = clamp(lip)
        mb.attr["brow"][i] = clamp(gauss(ax - 0.035, zr - 0.026, 0.022, 0.010))
        mb.attr["nostril"][i] = clamp(gauss(ax - 0.0095, zr + 0.0575, 0.0055, 0.0042))
        mb.attr["cheek"][i] = clamp(gauss(ax - 0.050, zr + 0.040, 0.030, 0.026))
        mb.attr["eyering"][i] = clamp(gauss(ax - EYE_X, zr - 0.0, 0.020, 0.013))
    bvh = BVHTree.FromPolygons(mb.v, mb.f)
    return bvh


def surf_pt(bvh, x, z, y0=-0.4):
    """Ray-cast the head surface from the front at (x, z)."""
    hit = bvh.ray_cast(Vector((x, y0, z)), Vector((0, 1, 0)), 1.0)
    if hit[0] is None:
        return None, None
    return hit[0], hit[1]


# ------------------------------------------------------------------------------------------------------ ears
def build_ear(mb, side, bvh):
    """Auricle: polar grid, front surface with helix rim / antihelix / concha, back surface pressed against the head."""
    tag = "head"
    ns, nr = 28, 8
    rw, rh = 0.0155, 0.031                                     # half width / half height (ear height 62 mm)
    front, back = [], []
    for k in range(nr + 1):
        rho = k / nr
        rf, rb = [], []
        for i in range(ns):
            ps = 2 * math.pi * i / ns
            # outline: egg (wider at the top)
            outline = 1.0 + 0.10 * math.sin(ps) - 0.05 * math.cos(2 * ps)
            a = rw * rho * math.cos(ps) * outline
            b = rh * rho * math.sin(ps) * outline + 0.004 * rho
            # relief on the outside (+X for the left ear)
            h = 0.004 * (1 - rho ** 3)
            h += 0.0075 * math.exp(-((rho - 0.90) / 0.10) ** 2)                            # helix rim
            h += 0.0040 * math.exp(-((rho - 0.60) / 0.12) ** 2) * (0.6 + 0.4 * math.sin(ps))  # antihelix ridge
            h -= 0.0070 * math.exp(-(((a + 0.002) / 0.008) ** 2 + ((b + 0.004) / 0.011) ** 2))  # concha hollow
            h -= 0.0030 * math.exp(-(((a - 0.006) / 0.003) ** 2 + ((b - 0.006) / 0.006) ** 2))  # crus groove
            lobe = smoothstep(-0.012, -0.030, b)
            h *= (1 - 0.6 * lobe)
            rf.append((a, b, h))
            rb.append((a, b, -0.004 - 0.003 * (1 - rho)))
        front.append(rf)
        back.append(rb)
    # placement: rotate the ear plane so that its rear edge stands ~16 deg off the skull, tilt the top back by 10 deg
    sgn = 1.0 if side > 0 else -1.0
    R = Matrix.Rotation(math.radians(-16.0 * sgn), 3, "Z") @ Matrix.Rotation(math.radians(10.0), 3, "X")
    base = Vector((0.0, 0.0, 0.0))
    ex, ez = 0.0755 * sgn, HZ - 0.008
    zone = None
    hit, nrm = surf_pt_side(bvh, sgn, 0.006, ez)
    if hit is not None:
        base = hit
    else:
        base = Vector((ex, 0.006, ez))

    def place(pt):
        a, b, h = pt
        local = Vector((h * sgn, -a * sgn * 0 + a, b))                # y (front-back) = a, z = b, x = height
        local = Vector((h * sgn, a, b))
        return base + R @ local + Vector((0.0025 * sgn, 0, 0))
    idf = [[mb.vert(place(p), tag) for p in ring] for ring in front]
    idb = [[mb.vert(place(p), tag) for p in ring] for ring in back]
    for k in range(nr):
        for i in range(ns):
            j = (i + 1) % ns
            q = (idf[k][i], idf[k][j], idf[k + 1][j], idf[k + 1][i])
            mb.face(q if sgn > 0 else q[::-1], 0)
    for i in range(ns):
        j = (i + 1) % ns
        q = (idf[nr][i], idf[nr][j], idb[nr][j], idb[nr][i])
        mb.face(q if sgn > 0 else q[::-1], 0)
    for k in range(nr):
        for i in range(ns):
            j = (i + 1) % ns
            q = (idb[k][i], idb[k + 1][i], idb[k + 1][j], idb[k][j])
            mb.face(q if sgn > 0 else q[::-1], 0)
    for i in range(ns):                                                # centre fan
        j = (i + 1) % ns
        mb.face((idf[0][i], idf[0][j], idb[0][j], idb[0][i]) if sgn > 0 else (idf[0][i], idb[0][i], idb[0][j], idf[0][j]), 0)


def surf_pt_side(bvh, sgn, y, z):
    hit = bvh.ray_cast(Vector((0.3 * sgn, y, z)), Vector((-sgn, 0, 0)), 1.0)
    if hit[0] is None:
        return None, None
    return hit[0], hit[1]


# ------------------------------------------------------------------------------------------------------ eyes
def build_eyeball(mb_eye, side):
    """Sclera sphere (+ iris/pupil painted by the shader in generated coordinates), plus the transparent cornea dome."""
    sgn = 1.0 if side > 0 else -1.0
    c = Vector((EYE_X * sgn, EYE_Y, EYE_Z))
    mb_eye.sphere(c, EYE_R, 40, 28, 0, "eye_" + ("L" if side > 0 else "R"))
    # cornea: a slightly larger cap on the front (-Y) half only
    cor = MB()
    r = EYE_R * 1.012
    rings = []
    n_a, n_p = 28, 8
    for j in range(n_p + 1):
        a = math.radians(38.0) * j / n_p
        rings.append([cor.vert(c + Vector((r * math.sin(a) * math.cos(2 * math.pi * i / n_a), -r * math.cos(a) * 1.0 - (0.0016 * (1 - (j / n_p) ** 2)) * 0,
                                          r * math.sin(a) * math.sin(2 * math.pi * i / n_a))), "eye_" + ("L" if side > 0 else "R")) for i in range(n_a)])
    for a, b in zip(rings, rings[1:]):
        cor.bridge(a, b, 0)
    return cor


def build_eyelids(mb, side):
    """Upper / lower eyelid shells on a sphere of radius 13.5 mm around the eyeball.  Almond palpebral fissure 30 x 9.5 mm, outer corner
    ~3 mm higher than the inner corner, monolid-to-narrow-double lid with a soft crease and the epicanthal fold at the inner corner."""
    sgn = 1.0 if side > 0 else -1.0
    tag = "lids_" + ("L" if side > 0 else "R")
    c = Vector((EYE_X * sgn, EYE_Y, EYE_Z))
    R0 = EYE_R + 0.0017
    nlon, nlat = 36, 9
    half_w = math.radians(37.0)
    lid_w = math.radians(58.0)                                            # +-38 deg of longitude ~ 30 mm at r=13.5 mm... (fissure length)
    tilt = math.radians(5.0)

    def pt(lon, lat, rad):
        # lon: 0 straight ahead, positive toward the outer corner; lat: elevation above the horizontal through the eye centre
        lo = lon * sgn
        d = Vector((math.sin(lo) * math.cos(lat), -math.cos(lo) * math.cos(lat), math.sin(lat)))
        return c + d * rad

    def slit(lon, upper):
        # lat of the lid margin as a function of lon (u in -1..1 from the inner to the outer corner)
        u = clamp(lon / half_w, -1, 1)
        u2 = (u + 1) * 0.5
        base = 0.0
        if upper:
            h = math.radians(26.0) * (1 - u * u) ** 0.5 * (0.85 + 0.35 * u2)              # peak toward the outer side
        else:
            h = -math.radians(16.0) * (1 - u * u) ** 0.6
        return h + tilt * (u)

    for upper in (True, False):
        rows = []
        n_l = nlat if upper else 6
        for k in range(n_l + 1):
            s = k / n_l
            row = []
            for i in range(nlon + 1):
                lon = -lid_w + 2 * lid_w * i / nlon
                lat0 = slit(lon, upper)
                span = math.radians(48.0 if upper else 30.0)
                lat = lat0 + (span * s if upper else -span * s)
                fade = smoothstep(0.55, 1.0, s)
                rad = R0 - 0.0022 * fade * fade
                if upper:                                                                # crease (double-eyelid line) at s ~ 0.42
                    rad += 0.0007 * math.exp(-((s - 0.55) / 0.10) ** 2) - 0.0012 * math.exp(-((s - 0.40) / 0.06) ** 2)
                # lid margin rolls inward
                rad += 0.0009 * (1 - smoothstep(0.0, 0.18, s))
                row.append(mb.vert(pt(lon, lat, rad), tag))
            rows.append(row)
        for a, b in zip(rows, rows[1:]):
            for i in range(nlon):
                q = (a[i], a[i + 1], b[i + 1], b[i])
                mb.face(q if (sgn > 0) == upper else q[::-1], 0)
    # epicanthal fold: small pad at the inner corner
    inner = c + Vector((-math.sin(0.0) * 0, 0, 0))
    lo = -half_w * 0.96
    d = Vector((math.sin(lo * sgn) * 1.0, -math.cos(lo * sgn) * 1.0, 0.02))
    d.normalize()
    mb.sphere(c + d * (R0 + 0.0006), 0.0022, 8, 6, 0, tag, (1.0, 0.7, 1.4))


# ------------------------------------------------------------------------------------------------------ lips
def build_lips(mb, bvh):
    """Closed lip ring: cupid's-bow upper lip, fuller lower lip, mouth corners; a tube along the mouth outline sunk into the face."""
    tag = "head"
    n = 44
    path = []
    for i in range(n):
        th = 2 * math.pi * i / n
        c, s = math.cos(th), math.sin(th)
        x = 0.0238 * c
        if s >= 0:                                                                      # upper lip (M-shaped bow)
            zc = 0.0068 * s * (1.0 - 0.30 * math.exp(-((x / 0.0055) ** 2)))
            rr = 0.0037
        else:                                                                           # lower lip
            zc = 0.0090 * s
            rr = 0.0038
        z = HZ - 0.0705 + zc + 0.0012 * (x / 0.0238) ** 2
        p, nrm = surf_pt(bvh, x, z)
        if p is None:
            continue
        path.append((p, nrm, rr * (1.0 - 0.55 * abs(c) ** 6)))
    rings = []
    m = len(path)
    for i, (p, nrm, r) in enumerate(path):
        tan = (path[(i + 1) % m][0] - path[i - 1][0]).normalized()
        side = tan.cross(nrm).normalized()
        ring = []
        for k in range(8):
            a = 2 * math.pi * k / 8
            ring.append(mb.vert(p + nrm * (r * 0.9 * math.sin(a) + 0.0004 - 0.0007) + side * (r * math.cos(a)), tag))
        rings.append(ring)
    for i in range(len(rings)):
        mb.bridge(rings[i], rings[(i + 1) % len(rings)], 0)
    mb.attr["lip"] = {i: 1.0 for i in range(len(mb.v))}


# ------------------------------------------------------------------------------------------------------ eyebrows
def build_brows(mb, bvh, rng):
    tag = "head"
    for side in (1, -1):
        for _ in range(170):
            s = rng.random()
            x = 0.011 + 0.049 * s
            zc = 0.0245 + 0.006 * math.sin(math.pi * min(1.0, s * 1.1)) - 0.012 * max(0.0, s - 0.75) / 0.25 * 0.0
            thick = 0.0043 * (1.0 - 0.45 * s) * (1.0 - 0.25 * (abs(s - 0.5) * 2) ** 2) + 0.0015
            zc = zc + (rng.random() - 0.5) * thick * 2 - 0.0035 * max(0.0, s - 0.7)
            p, nrm = surf_pt(bvh, x * side, HZ + zc + 0.0)
            if p is None:
                continue
            # flow: medial hairs point up-out, central out, lateral out-down
            ang = math.radians(50 - 100 * s) + (rng.random() - 0.5) * 0.35
            tang = Vector((side * math.cos(ang), 0.0, math.sin(ang)))
            tang = (tang - nrm * tang.dot(nrm)).normalized()
            L = rng.uniform(0.0075, 0.0115)
            pts = [p + nrm * 0.0002, p + nrm * 0.0009 + tang * L * 0.5, p + nrm * 0.0013 + tang * L]
            rad = [0.00042, 0.00036, 0.00014]
            rings = []
            for q, r in zip(pts, rad):
                w = nrm.cross(tang).normalized()
                rings.append([mb.vert(q + w * (r * math.cos(a)) + nrm * (r * math.sin(a)), tag) for a in (0, 2.09, 4.19)])
            for a, b in zip(rings, rings[1:]):
                mb.bridge(a, b, 0)


# ------------------------------------------------------------------------------------------------------ hair
def hairline_mask(p):
    """True where scalp hair grows (p on the skull surface, absolute coordinates)."""
    x, y, z = p.x, p.y - HEAD_C.y, p.z - HZ
    ax = abs(x)
    front_line = 0.068 - 0.030 * smoothstep(0.018, 0.070, ax)                           # temple recession
    if y < -0.02 and z < front_line:
        return False
    if ax > 0.062 and -0.058 < z < 0.030 and -0.045 < y < 0.045:                        # ear region
        return False
    if z < -0.052 - 0.008 * smoothstep(0.0, 0.05, ax):                                  # nape line
        return False
    return True


def build_hair(mb, cap, bvh, rng, n_locks=2300):
    """Short Japanese men's cut: side-swept fringe over the forehead, layered top, tapered sides and nape.  Each lock is a tapered ribbon
    with UVs (u across, v along) so the shader can paint fine strands."""
    tag = "hair"
    made = tries = 0
    whorl = Vector((-0.012, 0.045, HZ + 0.100))
    part_x = 0.018                                                                   # side part
    while made < n_locks and tries < n_locks * 12:
        tries += 1
        d = Vector((rng.gauss(0, 1), rng.gauss(0, 1), abs(rng.gauss(0, 1)) * 0.9 + 0.05 * rng.random() - 0.35)).normalized()
        hit = bvh.ray_cast(HEAD_C + d * 0.35, -d, 0.5)
        if hit[0] is None:
            continue
        p, n = hit[0], hit[1]
        if not hairline_mask(p):
            continue
        x, y, z = p.x, p.y - HEAD_C.y, p.z - HZ
        top_w = smoothstep(0.02, 0.07, z)
        L_top = 0.046 + 0.014 * smoothstep(-0.02, -0.075, y)                                # front slightly longer (fringe ends at the brows)
        L_side = 0.016 + 0.024 * smoothstep(0.02, 0.09, z + 0.02)                            # tapered sides
        L_back = 0.020 + 0.016 * smoothstep(0.0, 0.08, z)
        L = lerp(L_side, L_top, top_w)
        if y > 0.02:
            L = lerp(L, L_back, smoothstep(0.02, 0.06, y) * (1 - top_w * 0.6))
        L *= rng.uniform(0.85, 1.15) if not (y < -0.01 and z > 0.02) else rng.uniform(0.62, 1.22)
        if z < -0.015:                                                                   # sideburns / nape stay short
            L = min(L, 0.010 + 0.012 * smoothstep(-0.05, -0.015, z))
        if y < -0.01 and z > 0.02:                                                        # fringe: forward + down, swept toward his right (-x)
            flow = Vector((-0.60 if x > part_x else -0.05, -1.0, -0.55))
        else:
            outv = Vector((x, y, 0.0))
            outv = outv.normalized() if outv.length > 1e-5 else Vector((0, 1, 0))
            flow = outv * 0.6 + Vector((0, 0, -0.9))
            if z > 0.07:
                flow = Vector((p.x - whorl.x, p.y - whorl.y, 0)).normalized() * 0.9 + Vector((0, -0.25, -0.5))
        flow.normalize()
        nseg = 6
        pts = [p + n * 0.0012]
        nw = 0.55 if top_w > 0.5 else 0.18
        dcur = (n * nw + flow * (1.0 - nw)).normalized()
        step = L / nseg
        for k in range(1, nseg + 1):
            t = k / nseg
            dcur = (dcur * (0.55 - 0.15 * t) + flow * (0.30 + 0.20 * t) + Vector((0, 0, -1.0)) * (0.10 + 0.35 * t * t)).normalized()
            q = pts[-1] + dcur * step
            near = bvh.find_nearest(q)
            if near[0] is not None:
                loc, nrm = near[0], near[1]
                marg = 0.0022 + 0.0030 * math.sin(math.pi * min(1.0, t * 1.15)) * top_w
                if (q - loc).dot(nrm) < marg:
                    q = loc + nrm * marg
            pts.append(q)
        w0 = rng.uniform(0.0026, 0.0038)
        rr = rng.random()
        rings = []
        for k, q in enumerate(pts):
            t = k / nseg
            tan = (pts[min(k + 1, nseg)] - pts[max(k - 1, 0)]).normalized()
            nn = bvh.find_nearest(q)[1]
            if nn is None:
                nn = n
            wv = tan.cross(nn).normalized()
            th_ = w0 * (1.0 - 0.55 * t ** 1.5)
            wd = 0.0009 * (1.0 - 0.4 * t)
            rings.append([mb.vert(q + wv * (th_ * math.cos(a)) + nn * (wd * math.sin(a)), tag) for a in (0.0, 1.5708, 3.1416, 4.7124)])
        for k in range(nseg):
            for i in range(4):
                j = (i + 1) % 4
                mb.face((rings[k][i], rings[k][j], rings[k + 1][j], rings[k + 1][i]), 0,
                        uv=[(i / 4.0, k / nseg), (j / 4.0, k / nseg), (j / 4.0, (k + 1) / nseg), (i / 4.0, (k + 1) / nseg)])
        for ring in rings:
            for vi in ring:
                mb.attr.setdefault("lockrand", {})[vi] = rr
        made += 1
    return made


def build_scalp_cap(cap, head_mb):
    """Skull faces inside the hairline, lifted 1.6 mm (dark roots hide the skin between the locks)."""
    keep = {}
    for fi, f in enumerate(head_mb.f):
        if len(f) < 3:
            continue
        pts = [Vector(head_mb.v[i]) for i in f]
        c = sum(pts, Vector()) / len(pts)
        if not hairline_mask(c) or c.z < HZ - 0.03:
            continue
        ids = []
        for i in f:
            if i not in keep:
                pp = Vector(head_mb.v[i])
                keep[i] = cap.vert(pp + (pp - HEAD_C).normalized() * 0.0016, "hair")
            ids.append(keep[i])
        cap.face(ids, 0)
