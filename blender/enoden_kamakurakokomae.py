# -*- coding: utf-8 -*-
"""
enoden_kamakurakokomae.py
江ノ島電鉄 鎌倉高校前駅 / 鎌倉高校前1号踏切 / 国道134号・相模湾  --  Blender 5.x procedural scene generator

  Background base : Project PLATEAU (Kamakura 2024) terrain + buildings, baked by fetch_plateau.py
                    (run it once:  python fetch_plateau.py  ->  plateau_data/kamakura_koko.json)
  Foreground      : railway, level crossing, station platform, poles/wires, Enoden 1000 train, sea wall, ocean ...
                    all generated procedurally in this file.

Run (headless):
  blender -b --python enoden_kamakurakokomae.py -- --render cam1            (writes output/*.png + .blend)
  blender -b --python enoden_kamakurakokomae.py -- --render both --samples 256 --res-x 2560 --res-y 1440
Run (GUI): open this file in the Text Editor and press Run Script (builds the scene, no render).

Coordinates (spec 2.2): origin = centre of the 1号踏切 on the track centre-line, +X = track toward 七里ヶ浜/鎌倉,
+Y = mountain side (north), +Z up, 1 unit = 1 m.  Z = 0 is the rail-head level.
(The true track bearing is 97.3 deg, i.e. scene +Y is ~7.3 deg east of true north; PLATEAU/OSM data are rotated
 into this frame by fetch_plateau.py.)

Phases (spec 6):  0 Research (RESEARCH dict)  ->  1 Infrastructure  ->  2 Architecture & props  ->  3 Train
                  ->  4 Materials / lighting / cameras
"""
import argparse, json, math, os, random, sys, time, warnings, zlib

import bpy
import bmesh
from mathutils import Euler, Matrix, Vector

warnings.filterwarnings("ignore", category=DeprecationWarning)      # Material.use_nodes / World.use_nodes (Blender 6.0)
T0 = time.time()


def log(*a):
    print("[enoden %6.1fs]" % (time.time() - T0), *a, flush=True)


try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:                                                    # Text-editor run
    HERE = os.path.dirname(bpy.data.filepath) or os.getcwd()


# =====================================================================================================================
#  CLI
# =====================================================================================================================
def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="enoden_kamakurakokomae.py")
    ap.add_argument("--render", choices=["none", "cam1", "cam2", "both"], default="none")
    ap.add_argument("--engine", choices=["CYCLES", "EEVEE"], default="CYCLES")
    ap.add_argument("--samples", type=int, default=128)
    ap.add_argument("--res-x", type=int, default=1920)
    ap.add_argument("--res-y", type=int, default=1080)
    ap.add_argument("--percent", type=int, default=100, help="render resolution percentage")
    ap.add_argument("--out", default=os.path.join(HERE, "output"))
    ap.add_argument("--plateau", default=os.path.join(HERE, "plateau_data", "kamakura_koko.json"))
    ap.add_argument("--no-plateau", action="store_true", help="skip PLATEAU terrain/buildings (procedural hill only)")
    ap.add_argument("--no-trees", action="store_true")
    ap.add_argument("--web-export", default=None, help="write the web-viewer assets (glTF/Draco, ground grid, trees) into this folder and stop")
    ap.add_argument("--no-character", action="store_true", help="do not place the rigged 20s man (output/character/character_male20s.blend)")
    ap.add_argument("--tetrapods", action="store_true", help="add the spec's wave-dissipating blocks (not present on this stretch in reality)")
    ap.add_argument("--no-blend", action="store_true", help="do not save the .blend")
    ap.add_argument("--quick", action="store_true", help="lighter scene for previews (fewer ballast rocks / trees)")
    ap.add_argument("--custom", action="append", default=[], metavar="NAME=px,py,pz>tx,ty,tz@lens",
                    help="extra camera to render (repeatable), e.g. close=4,6,1.8>3.6,2.7,2.5@35")
    ap.add_argument("--exposure", type=float, default=None, help="override view exposure (EV)")
    ap.add_argument("--look", default=None, help="override the colour-management look, e.g. 'AgX - Punchy'")
    ap.add_argument("--aerosol", type=float, default=None, help="sky aerosol (spec 'Dust') override")
    ap.add_argument("--ozone", type=float, default=None, help="sky ozone override")
    ap.add_argument("--haze", type=float, default=None, help="override the world haze density (1/m); 0 disables it")
    ap.add_argument("--view", default=None, help="override the view transform (AgX / Filmic / Standard / Khronos PBR Neutral)")
    return ap.parse_args(argv)


ARGS = parse_args()

# =====================================================================================================================
#  Phase 0  --  Research results (see comments for provenance; "ASSUMPTION" = not publicly documented)
# =====================================================================================================================
RESEARCH = {
    # --- 1. Enoden 1000 series (Wikipedia 江ノ島鎌倉観光1000形電車 諸元表; enoden.co.jp museum) ---------------------
    "train_1000": {
        "set_length": 25.400,          # 2-car set, mm/1000
        "car_length": 12.700,          # ASSUMPTION: set_length / 2 (the published value is for the 2-car set)
        "body_width": 2.400, "max_width": 2.450,
        "height_max": 3.900,           # published 全高 (pantograph folded)
        "roof_height": 3.400,          # published 屋根高
        "floor_height": 1.070,         # published 床面高  (platform 1.1 m in the spec matches)
        "bogie_center": 9.500,         # published 台車中心間距離 (x2)
        "axle_base": 1.600,            # published 固定軸距 (1st-3rd batch; 4th/5th: 1.650)
        "wheel_dia": 0.860,            # published 車輪径
        "gauge": 1.067,
        "pantograph_folded_height": 3.900,   # ASSUMPTION: = 全高 (single-arm pantographs since 2013-15)
        "pantograph_working_height": 4.600,  # ASSUMPTION: trolley wire height (DC 600 V, source: Enoden line data)
        "voltage_dc": 600,
    },
    # 300 series is articulated and every set differs (Wikipedia table); the extraction gave a 2.85 m height for the
    # 302/303 sets which is obviously a typo, so it is NOT used.  Reference only (301F): length 24.814, width 2.400,
    # height 3.910, bogie centres 8.900, axle base 1.473, floor 1.015.
    "train_300_301F": {"length": 24.814, "width": 2.400, "height": 3.910, "bogie_center": 8.900, "axle_base": 1.473},

    # --- 2. Level crossing equipment -------------------------------------------------------------------------------
    # Model numbers / cabinet positions of the signal equipment are not published.  OSM tags on the crossing node:
    # crossing:barrier=full, crossing:bell=yes, crossing:light=yes.  JIS colours: cross-mark yellow/black, barrier post
    # yellow, barrier arm stripes yellow 180-300 mm : black 120-200 mm (~3:2).  Layout below = ASSUMPTION from the
    # typical Enoden layout (4 gates, 4 alarm masts, control cabinet beside the NE mast).
    "crossing": {"road_width": 6.5, "stripe_yellow": 0.24, "stripe_black": 0.16, "arm_length": 3.2, "arm_height": 0.95,
                 "mast_height": 3.9, "cabinet": (0.55, 0.35, 1.15), "model": None},

    # --- 3. Route 134 / sea wall (Kanagawa Pref. 国道134号擁壁改修事業 pamphlet, standard cross-section) -------------
    "route134": {"lane": 3.25, "shoulder": 0.5, "sidewalk_planned": 3.5, "total_planned": 11.0,
                 "wall_type": "場所打擁壁 (化粧コンクリート) on steel-pipe piles (phi 900-1200)",
                 "wall_height_pamphlet": "4.5-7.5 m (beach to road)",
                 "tetrapods_here": False,      # the sand beach borders the wall; no wave-dissipating blocks on this stretch
                 "railing": "tubular steel guard fence on the wall top"},

    # --- 4. Station equipment (not published) -> ASSUMPTIONS from photos: PASMO simple gate (blue), vinyl cover against
    #        salt, vending machine behind glass door ---------------------------------------------------------------
    "station": {"passage_gate": (0.22, 0.20, 1.05), "vending": (0.75, 0.65, 1.85), "platform_len": 45.0,
                "platform_width": 2.6, "platform_height": 1.1},
}

# =====================================================================================================================
#  Master plan (spec 2.3) + decisions
# =====================================================================================================================
CFG = {
    "gauge": 1.067,
    "rail_x": (-125.0, 125.0),
    "platform": {"x0": -55.0, "x1": -10.0, "y0": 1.35, "width": 2.6, "height": 1.1},   # y0: see note in build_platform
    "crossing_half": 3.25,
    "r134": {"y_n": -6.0, "carriage": 7.5, "walk": 2.5, "y_s": -16.0, "z": -0.30, "walk_z": -0.20},
    # Street View (2025): low cable fence on the pavement edge, a flat concrete apron, then a sloped concrete revetment down to the
    # sand -- no vertical wall and no tetrapods on this stretch (the spec asked for a 2.8 m wall + blocks).
    "wall": {"y": -17.5, "apron_end": -19.5, "slope_end": -26.0, "toe_z": -2.80},
    "sea": {"y_edge": -20.0, "shore_y": -30.3, "z": -3.75, "sx": 300.0, "sy": 200.0},
    "sun": {"elevation": 7.5, "rotation": 225.0, "dust": 4.0, "ozone": 2.0},
    "train_front_x": 0.6,                # x of the leading cab end: the set is just entering the crossing (Cam 1 keeps the
                                         # alarm, gates and the bay in view instead of a wall of train side)
    "train_front_cam2": 46.0,           # for Camera 2 the set has already left the crossing (keeps the platform visible)
    "cam2_target": (4.0, 0.5, 0.6),   # spec gives only the position; looks east along the coast (bay on the right)
    "exposure": -1.2,
    "grade": {"cam1": (-2.2, "None"),                    # shaded (north-facing) view: keep the shadows open
              "cam2": (-1.2, "AgX - Punchy")},           # sun-lit view: punchier
    "clouds": True,                     # procedural stratus in the world shader (sun stays clear)
    "far_land": True,                   # Enoshima / headlands / Hakone / Fuji silhouettes
    "haze_density": 0.0,                # a world volume (Volume Scatter) blacks out the sun/sky lighting in Cycles 5.2 -> off
    "warm_grade": (0.045, -0.055),      # (+R, -B) at mid-tones via the colour-management curve: golden-hour warmth
    "look": ("AgX - Punchy", "None"),
    # the rigged man (char_*.py): waits on the south-side footway beside the crossing, facing the track, looking west toward the approaching train
    "character": {"pos": (3.9, -5.0), "yaw_deg": 180.0, "neck_yaw_deg": 22.0, "head_yaw_deg": 32.0, "idle_frame": 20},
    "crossing_active": True,             # alarm lamps lit + gates down
    "tetrapods": ARGS.tetrapods,
    "ballast_density": 120.0 if ARGS.quick else 520.0,
    "trees": 0 if ARGS.no_trees else (400 if ARGS.quick else 2200),
    "grass_clumps": 700 if ARGS.quick else 7000,
    "litter": 700 if ARGS.quick else 3200,
}

random.seed(20260921)


def rnd(a=0.0, b=1.0):
    return random.uniform(a, b)


# =====================================================================================================================
#  Small helpers
# =====================================================================================================================
def clamp(v, a=0.0, b=1.0):
    return a if v < a else (b if v > b else v)


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(e0, e1, x):
    t = clamp((x - e0) / (e1 - e0)) if e1 != e0 else (1.0 if x >= e1 else 0.0)
    return t * t * (3 - 2 * t)


def hexc(h, a=1.0):
    """'#RRGGBB' (sRGB) -> linear RGBA tuple."""
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    f = lambda v: v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return (f(c[0]), f(c[1]), f(c[2]), a)


SCENE = bpy.context.scene
_COLL = {}


def coll(name, parent=None):
    """Get/create a collection linked under `parent` (or the scene collection)."""
    if name in _COLL:
        return _COLL[name]
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    par = parent or SCENE.collection
    if c.name not in par.children:
        par.children.link(c)
    _COLL[name] = c
    return c


def rot_mat(rot):
    if rot is None:
        return None
    if isinstance(rot, Matrix):
        return rot.to_3x3()
    return Euler(rot, "XYZ").to_matrix()


# =====================================================================================================================
#  MeshBuilder: accumulate boxes / cylinders / extrusions and turn them into one object
# =====================================================================================================================
class MB:
    def __init__(self):
        self.v, self.f, self.mi, self.sm = [], [], [], []
        self.fattr = {}
        self.uvs = {}                                                        # face index -> [(u, v), ...] (one per corner)

    def nv(self):
        return len(self.v)

    def face(self, idx, mat=0, smooth=False, uv=None, **attrs):
        self.f.append(tuple(idx))
        self.mi.append(mat)
        self.sm.append(smooth)
        if uv is not None:
            self.uvs[len(self.f) - 1] = uv
        for k, val in attrs.items():
            self.fattr.setdefault(k, {})[len(self.f) - 1] = val

    def verts(self, pts):
        b = len(self.v)
        self.v.extend((float(p[0]), float(p[1]), float(p[2])) for p in pts)
        return b

    # ---- primitives -------------------------------------------------------------------------------------------
    def box(self, c, s, mat=0, rot=None, smooth=False, **attrs):
        hx, hy, hz = s[0] / 2.0, s[1] / 2.0, s[2] / 2.0
        R = rot_mat(rot)
        c = Vector(c)
        pts = []
        for sx, sy, sz in ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)):
            p = Vector((sx * hx, sy * hy, sz * hz))
            if R is not None:
                p = R @ p
            pts.append(c + p)
        b = self.verts(pts)
        for q in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            self.face([b + i for i in q], mat, smooth, **attrs)

    def cyl(self, p0, p1, r0, r1=None, segs=12, mat=0, caps=True, smooth=True, **attrs):
        p0, p1 = Vector(p0), Vector(p1)
        r1 = r0 if r1 is None else max(r1, 1e-4)
        ax = p1 - p0
        L = ax.length
        if L < 1e-9:
            return
        d = ax / L
        up = Vector((0, 0, 1)) if abs(d.z) < 0.99 else Vector((1, 0, 0))
        u = d.cross(up).normalized()
        w = d.cross(u)
        ang = [2 * math.pi * i / segs for i in range(segs)]
        ring = [(u * math.cos(a) + w * math.sin(a)) for a in ang]
        b0 = self.verts([p0 + r * r0 for r in ring])
        b1 = self.verts([p1 + r * r1 for r in ring])
        for i in range(segs):
            j = (i + 1) % segs
            self.face((b0 + i, b0 + j, b1 + j, b1 + i), mat, smooth, **attrs)
        if caps:
            t = self.verts([p1 + r * r1 for r in ring])
            self.face([t + i for i in range(segs)], mat, False, **attrs)
            bt = self.verts([p0 + r * r0 for r in ring])
            self.face([bt + i for i in reversed(range(segs))], mat, False, **attrs)

    def sphere(self, c, r, segs=10, rings=6, mat=0, smooth=True, scale=(1, 1, 1), **attrs):
        c = Vector(c)
        b = self.nv()
        pts = [c + Vector((0, 0, r * scale[2]))]
        for j in range(1, rings):
            th = math.pi * j / rings
            for i in range(segs):
                ph = 2 * math.pi * i / segs
                pts.append(c + Vector((r * scale[0] * math.sin(th) * math.cos(ph), r * scale[1] * math.sin(th) * math.sin(ph),
                                       r * scale[2] * math.cos(th))))
        pts.append(c - Vector((0, 0, r * scale[2])))
        self.verts(pts)
        for i in range(segs):
            self.face((b, b + 1 + i, b + 1 + (i + 1) % segs), mat, smooth, **attrs)
        for j in range(rings - 2):
            for i in range(segs):
                a0 = b + 1 + j * segs + i
                a1 = b + 1 + j * segs + (i + 1) % segs
                self.face((a0, a0 + segs, a1 + segs, a1), mat, smooth, **attrs)
        last = b + len(pts) - 1
        for i in range(segs):
            self.face((last, b + 1 + (rings - 2) * segs + (i + 1) % segs, b + 1 + (rings - 2) * segs + i), mat, smooth, **attrs)

    def quad(self, p0, p1, p2, p3, mat=0, smooth=False, **attrs):
        b = self.verts((p0, p1, p2, p3))
        self.face((b, b + 1, b + 2, b + 3), mat, smooth, **attrs)

    def prism_x(self, profile, x0, x1, seg_mats=0, cap_mat=None, smooth=False, **attrs):
        """Extrude a closed (y, z) profile along +X from x0 to x1.  seg_mats: int or list (per profile edge)."""
        pts = list(profile)
        area = 0.0
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            area += a[0] * b[1] - b[0] * a[1]
        n = len(pts)
        mats = [seg_mats] * n if isinstance(seg_mats, int) else list(seg_mats)
        if area < 0:                                                   # make CCW seen from +X
            pts.reverse()
            mats = list(reversed(mats[:n]))
            mats = mats[1:] + mats[:1]                                 # reversed edge i == original edge n-2-i
        b0 = self.verts([(x0, y, z) for y, z in pts])
        b1 = self.verts([(x1, y, z) for y, z in pts])
        for i in range(n):
            j = (i + 1) % n
            self.face((b0 + i, b0 + j, b1 + j, b1 + i), mats[i % len(mats)], smooth, **attrs)
        cm = mats[0] if cap_mat is None else cap_mat
        e1 = self.verts([(x1, y, z) for y, z in pts])
        self.face([e1 + i for i in range(n)], cm, False, **attrs)
        e0 = self.verts([(x0, y, z) for y, z in pts])
        self.face([e0 + i for i in reversed(range(n))], cm, False, **attrs)

    def loft_x(self, prof0, x0, prof1, x1, seg_mats=0, cap_mat=None, smooth=False, cap=True, **attrs):
        """Skin between two (y, z) rings with the same vertex count (both CCW seen from +X).  x0 / x1: number or per-vertex list.
        Returns (base0, base1) vertex indices of the two rings so that the caller can build the end face itself."""
        n = len(prof0)
        mats = [seg_mats] * n if isinstance(seg_mats, int) else list(seg_mats)
        xs0 = list(x0) if isinstance(x0, (list, tuple)) else [x0] * n
        xs1 = list(x1) if isinstance(x1, (list, tuple)) else [x1] * n
        b0 = self.verts([(xs0[i], y, z) for i, (y, z) in enumerate(prof0)])
        b1 = self.verts([(xs1[i], y, z) for i, (y, z) in enumerate(prof1)])
        for i in range(n):
            j = (i + 1) % n
            self.face((b0 + i, b0 + j, b1 + j, b1 + i), mats[i % len(mats)], smooth, **attrs)
        if cap:
            e1 = self.verts([(xs1[i], y, z) for i, (y, z) in enumerate(prof1)])
            self.face([e1 + i for i in range(n)], mats[0] if cap_mat is None else cap_mat, False, **attrs)
        return b0, b1

    def append(self, other, M=None, mat_map=None, **attrs):
        """Copy another MB (optionally transformed by a 4x4 matrix) into this one."""
        b = self.nv()
        if M is None:
            self.v.extend(other.v)
        else:
            self.v.extend(tuple(M @ Vector(p)) for p in other.v)
        for i, f in enumerate(other.f):
            m = other.mi[i]
            if mat_map is not None:
                m = mat_map.get(m, m)
            self.face([b + k for k in f], m, other.sm[i], uv=other.uvs.get(i), **attrs)
            for k, d in other.fattr.items():
                if i in d:
                    self.fattr.setdefault(k, {})[len(self.f) - 1] = d[i]

    def build(self, name, collection, mats=(), smooth_angle=None, bevel=None):
        me = bpy.data.meshes.new(name)
        me.from_pydata(self.v, [], self.f)
        me.update()
        n = len(me.polygons)
        me.polygons.foreach_set("material_index", self.mi[:n])
        me.polygons.foreach_set("use_smooth", self.sm[:n])
        for k, d in self.fattr.items():
            a = me.attributes.new(k, "FLOAT", "FACE")
            a.data.foreach_set("value", [d.get(i, 0.0) for i in range(n)])
        if self.uvs:
            uvl = me.uv_layers.new(name="UVMap")
            flat = []
            for i, f in enumerate(self.f[:n]):
                uv = self.uvs.get(i)
                if uv is None:
                    flat += [0.0, 0.0] * len(f)
                else:
                    for (u_, v_) in uv:
                        flat += [u_, v_]
            uvl.data.foreach_set("uv", flat)
        for m in mats:
            me.materials.append(m)
        if smooth_angle is not None:
            bm = bmesh.new()
            bm.from_mesh(me)
            for e in bm.edges:
                if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > smooth_angle:
                    e.smooth = False
            bm.to_mesh(me)
            bm.free()
        ob = bpy.data.objects.new(name, me)
        collection.objects.link(ob)
        if bevel:
            bv = ob.modifiers.new("Bevel", "BEVEL")
            bv.width = bevel
            bv.segments = 2
            bv.limit_method = "ANGLE"
            bv.angle_limit = math.radians(35)
        return ob


def add_bevel(ob, width=0.006, segments=2, angle=35.0):
    bv = ob.modifiers.new("Bevel", "BEVEL")
    bv.width, bv.segments, bv.limit_method, bv.angle_limit = width, segments, "ANGLE", math.radians(angle)
    return bv


def make_empty(name, loc, collection, kind="PLAIN_AXES", size=0.3):
    e = bpy.data.objects.new(name, None)
    e.empty_display_type, e.empty_display_size = kind, size
    e.location = loc
    collection.objects.link(e)
    return e


def wire(name, pts, radius, mat, collection, cyclic=False):
    """Poly curve with a round bevel (cables, catenary wires, pipes)."""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius
    cu.bevel_resolution = 1
    cu.resolution_u = 1
    sp = cu.splines.new("POLY")
    sp.points.add(len(pts) - 1)
    for p, q in zip(sp.points, pts):
        p.co = (q[0], q[1], q[2], 1.0)
    sp.use_cyclic_u = cyclic
    ob = bpy.data.objects.new(name, cu)
    collection.objects.link(ob)
    cu.materials.append(mat)
    return ob


def catenary(p0, p1, sag, n=20):
    p0, p1 = Vector(p0), Vector(p1)
    out = []
    for i in range(n + 1):
        t = i / n
        p = p0.lerp(p1, t)
        p.z -= sag * 4.0 * t * (1.0 - t)
        out.append(tuple(p))
    return out


_FONT = {}


def cjk_font():
    if "f" in _FONT:
        return _FONT["f"]
    f = None
    for path in (r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\meiryob.ttc", r"C:\Windows\Fonts\msgothic.ttc",
                 r"C:\Windows\Fonts\meiryo.ttc", "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"):
        if os.path.exists(path):
            try:
                f = bpy.data.fonts.load(path)
                break
            except Exception:
                f = None
    _FONT["f"] = f
    return f


def text_obj(name, body, loc, rot, size, mat, collection, extrude=0.0, align="CENTER", scale=(1, 1, 1), cjk=True):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.size = size
    cu.align_x = align
    cu.align_y = "CENTER"
    cu.extrude = extrude
    if cjk and cjk_font() is not None:
        cu.font = cjk_font()
    ob = bpy.data.objects.new(name, cu)
    ob.location = loc
    ob.rotation_euler = rot
    ob.scale = scale
    cu.materials.append(mat)
    collection.objects.link(ob)
    return ob


# =====================================================================================================================
#  Materials (spec 4 + supporting props).  Procedural, weathered.  All colours are hex sRGB.
# =====================================================================================================================
class SG:
    """Tiny shader-graph helper."""

    def __init__(self, name):
        self.mat = bpy.data.materials.new(name)
        self.mat.use_nodes = True
        self.nt = self.mat.node_tree
        self.nt.nodes.clear()
        self.out = self.nt.nodes.new("ShaderNodeOutputMaterial")
        self._tc = None

    # -- plumbing
    def n(self, idname, **props):
        nd = self.nt.nodes.new(idname)
        for k, v in props.items():
            setattr(nd, k, v)
        return nd

    def put(self, sock, val):
        if val is None:
            return
        if isinstance(val, bpy.types.NodeSocket):
            self.nt.links.new(val, sock)
            return
        if isinstance(val, str):
            val = hexc(val)
        try:
            sock.default_value = val
        except TypeError:
            sock.default_value = tuple(val)

    @staticmethod
    def sk(node, io, name, typ=None):
        socks = node.inputs if io == "in" else node.outputs
        for s in socks:
            if s.name == name and s.enabled and (typ is None or s.type == typ):
                return s
        return socks[name]

    # -- nodes
    def coord(self):
        if self._tc is None:
            self._tc = self.n("ShaderNodeTexCoord")
        return self._tc.outputs["Object"]

    def mapping(self, vec=None, scale=(1, 1, 1), loc=(0, 0, 0), rot=(0, 0, 0)):
        m = self.n("ShaderNodeMapping")
        self.put(m.inputs["Vector"], vec if vec is not None else self.coord())
        m.inputs["Scale"].default_value = scale
        m.inputs["Location"].default_value = loc
        m.inputs["Rotation"].default_value = rot
        return m.outputs["Vector"]

    def noise(self, scale, detail=3.0, rough=0.55, vec=None, distortion=0.0):
        nd = self.n("ShaderNodeTexNoise", noise_dimensions="3D")
        self.put(nd.inputs["Vector"], vec if vec is not None else self.coord())
        nd.inputs["Scale"].default_value = scale
        nd.inputs["Detail"].default_value = detail
        nd.inputs["Roughness"].default_value = rough
        nd.inputs["Distortion"].default_value = distortion
        return nd.outputs["Fac"]

    def voro_edge(self, scale, vec=None, rand=1.0):
        nd = self.n("ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature="DISTANCE_TO_EDGE")
        self.put(nd.inputs["Vector"], vec if vec is not None else self.coord())
        nd.inputs["Scale"].default_value = scale
        nd.inputs["Randomness"].default_value = rand
        return nd.outputs["Distance"]

    def sep(self, vec):
        s = self.n("ShaderNodeSeparateXYZ")
        self.put(s.inputs["Vector"], vec)
        return s.outputs["X"], s.outputs["Y"], s.outputs["Z"]

    def world_pos(self):
        g = self.n("ShaderNodeNewGeometry")
        return g.outputs["Position"]

    def math(self, op, a, b=None, clamp=False):
        m = self.n("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.put(m.inputs[0], a)
        if b is not None:
            self.put(m.inputs[1], b)
        return m.outputs[0]

    def mapr(self, val, a, b, c, d, clamp=True):
        m = self.n("ShaderNodeMapRange", data_type="FLOAT", clamp=clamp)
        self.put(m.inputs[0], val)
        m.inputs[1].default_value, m.inputs[2].default_value = a, b
        m.inputs[3].default_value, m.inputs[4].default_value = c, d
        return m.outputs[0]

    def ramp(self, fac, stops, interp="LINEAR"):
        r = self.n("ShaderNodeValToRGB")
        r.color_ramp.interpolation = interp
        els = r.color_ramp.elements
        while len(els) < len(stops):
            els.new(1.0)
        for e, (pos, col) in zip(els, stops):
            e.position = pos
            e.color = hexc(col) if isinstance(col, str) else col
        self.put(r.inputs["Fac"], fac)
        return r.outputs["Color"]

    def mix(self, fac, a, b):
        m = self.n("ShaderNodeMix", data_type="RGBA", blend_type="MIX", clamp_factor=True)
        self.put(self.sk(m, "in", "Factor", "VALUE"), fac)
        self.put(self.sk(m, "in", "A", "RGBA"), a)
        self.put(self.sk(m, "in", "B", "RGBA"), b)
        return self.sk(m, "out", "Result", "RGBA")

    def bump(self, height, strength=0.3, dist=0.02, normal=None):
        b = self.n("ShaderNodeBump")
        self.put(b.inputs["Height"], height)
        b.inputs["Strength"].default_value = strength
        b.inputs["Distance"].default_value = dist
        if normal is not None:
            self.put(b.inputs["Normal"], normal)
        return b.outputs["Normal"]

    def attr(self, name, kind="GEOMETRY", out="Fac"):
        a = self.n("ShaderNodeAttribute", attribute_type=kind, attribute_name=name)
        return a.outputs[out]

    def principled(self, base="#808080", metallic=0.0, rough=0.5, **kw):
        p = self.n("ShaderNodeBsdfPrincipled")
        self.put(p.inputs["Base Color"], base)
        self.put(p.inputs["Metallic"], metallic)
        self.put(p.inputs["Roughness"], rough)
        names = {"coat": "Coat Weight", "coat_rough": "Coat Roughness", "transmission": "Transmission Weight",
                 "ior": "IOR", "emit": "Emission Color", "emit_strength": "Emission Strength", "spec": "Specular IOR Level",
                 "alpha": "Alpha", "normal": "Normal", "sheen": "Sheen Weight"}
        for k, v in kw.items():
            self.put(p.inputs[names.get(k, k)], v)
        return p.outputs["BSDF"]

    def emission(self, color, strength):
        e = self.n("ShaderNodeEmission")
        self.put(e.inputs["Color"], color)
        self.put(e.inputs["Strength"], strength)
        return e.outputs["Emission"]

    def mix_shader(self, fac, a, b):
        m = self.n("ShaderNodeMixShader")
        self.put(m.inputs["Fac"], fac)
        self.nt.links.new(a, m.inputs[1])
        self.nt.links.new(b, m.inputs[2])
        return m.outputs["Shader"]

    def transparent(self):
        return self.n("ShaderNodeBsdfTransparent").outputs["BSDF"]

    def finish(self, shader):
        self.nt.links.new(shader, self.out.inputs["Surface"])
        return self.mat


MAT = {}


def reg(g_or_mat, shader=None):
    m = g_or_mat.finish(shader) if shader is not None else g_or_mat
    MAT[m.name] = m
    return m


def simple(name, base, metallic=0.0, rough=0.5, **kw):
    g = SG(name)
    return reg(g, g.principled(base, metallic, rough, **kw))


def emissive(name, color, strength, base=None):
    g = SG(name)
    e = g.emission(color, strength)
    if base:
        e = g.mix_shader(0.85, g.principled(base, 0.0, 0.15), e)
    return reg(g, e)


# ---- reusable weathering graphs -----------------------------------------------------------------------------------
def concrete_graph(g, base, rough=(0.62, 0.9), wet_z=None, salt=False, cracks=True, streak=True, scale=1.0):
    """Returns (color, roughness, normal) sockets for weathered concrete (world-space procedural)."""
    dark = hexc(base)
    dark = (dark[0] * 0.62, dark[1] * 0.62, dark[2] * 0.62, 1.0)
    mott = g.noise(3.0 * scale, 8.0, 0.6)
    col = g.mix(g.ramp(mott, [(0.35, (0, 0, 0, 1)), (0.65, (1, 1, 1, 1))]), dark, base)
    if streak:                                         # rain streaks: noise stretched along Z
        st = g.noise(2.5 * scale, 4.0, 0.5, vec=g.mapping(scale=(1.0, 1.0, 0.12)))
        col = g.mix(g.math("MULTIPLY", g.ramp(st, [(0.5, (0, 0, 0, 1)), (0.8, (1, 1, 1, 1))]), 0.55), col, hexc("#3B3A36"))
    height = g.noise(140.0, 4.0, 0.6)
    if cracks:
        vd = g.voro_edge(0.9 * scale)
        gate = g.ramp(g.noise(0.35 * scale, 2.0), [(0.55, (0, 0, 0, 1)), (0.7, (1, 1, 1, 1))])
        crack = g.math("MULTIPLY", g.math("LESS_THAN", vd, 0.018), gate)
        col = g.mix(g.math("MULTIPLY", crack, 0.9), col, hexc("#1B1B1A"))
        height = g.math("SUBTRACT", height, g.math("MULTIPLY", crack, 0.7))
    r = g.mapr(g.noise(6.0 * scale, 3.0), 0.35, 0.65, rough[0], rough[1])
    if wet_z is not None:                              # wet/dark toward the bottom, dry & salt-bloomed on top
        z = g.sep(g.world_pos())[2]
        wet = g.mapr(z, wet_z[1], wet_z[0], 0.0, 1.0)                 # 1 at the bottom
        col = g.mix(g.math("MULTIPLY", wet, 0.75), col, hexc("#3E4041"))
        r = g.math("MULTIPLY", r, g.mapr(wet, 0.0, 1.0, 1.0, 0.35))
        if salt:
            sn = g.ramp(g.noise(9.0, 5.0, 0.65, vec=g.mapping(scale=(1.0, 1.0, 0.4))), [(0.55, (0, 0, 0, 1)), (0.85, (1, 1, 1, 1))])
            col = g.mix(g.math("MULTIPLY", sn, g.mapr(wet, 0.0, 1.0, 0.65, 0.0)), col, hexc("#C9C6BC"))
    return col, r, g.bump(height, 0.35, 0.02)


def steel_graph(g, base, metallic=0.85, rough=0.45, rust=0.4, scale=1.0):
    n1 = g.noise(7.0 * scale, 6.0, 0.65)
    rust_mask = g.ramp(g.math("MULTIPLY", n1, rust * 2.2), [(0.45, (0, 0, 0, 1)), (0.8, (1, 1, 1, 1))])
    col = g.mix(rust_mask, base, hexc("#5B3A22"))
    met = g.math("MULTIPLY", metallic, g.mapr(rust_mask, 0.0, 1.0, 1.0, 0.25))
    r = g.mapr(rust_mask, 0.0, 1.0, rough, 0.85)
    return col, met, r, g.bump(g.noise(90.0, 3.0), 0.15, 0.01)


def build_materials():
    log("materials ...")
    # ---------------------------------------------------------------- spec table (section 4)
    g = SG("MAT_Enoden_Green")
    wear = g.ramp(g.noise(2.2, 4.0, 0.6), [(0.4, (0, 0, 0, 1)), (0.9, (1, 1, 1, 1))])
    col = g.mix(g.math("MULTIPLY", wear, 0.22), "#1A4325", "#4A5A44")                       # dust film
    zc = g.sep(g.world_pos())[2]
    col = g.mix(g.mapr(zc, 1.5, 0.95, 0.0, 0.5), col, "#2A2C24")                            # road splash near the sill
    finger = g.noise(45.0, 6.0, 0.7)
    reg(g, g.principled(col, 0.1, 0.25, coat=0.5, coat_rough=g.mapr(finger, 0.4, 0.7, 0.03, 0.22),
                        normal=g.bump(g.noise(300.0, 2.0), 0.03, 0.002)))

    g = SG("MAT_Enoden_Cream")
    wear = g.ramp(g.noise(2.6, 4.0, 0.6), [(0.4, (0, 0, 0, 1)), (0.9, (1, 1, 1, 1))])
    col = g.mix(g.math("MULTIPLY", wear, 0.30), "#E8E0CE", "#B8AE98")
    reg(g, g.principled(col, 0.0, 0.30, coat=0.4, coat_rough=g.mapr(g.noise(50.0, 5.0), 0.4, 0.7, 0.03, 0.2)))

    g = SG("MAT_Asphalt_Real")
    grain = g.noise(320.0, 3.0, 0.7)
    mott = g.noise(5.0, 5.0, 0.6)
    col = g.mix(g.ramp(mott, [(0.35, (0, 0, 0, 1)), (0.7, (1, 1, 1, 1))]), "#34363A", "#5A5C61")
    vd = g.voro_edge(0.7)
    gate = g.ramp(g.noise(0.22, 2.0), [(0.60, (0, 0, 0, 1)), (0.74, (1, 1, 1, 1))])
    crack = g.math("MULTIPLY", g.math("LESS_THAN", vd, 0.016), gate)
    col = g.mix(g.math("MULTIPLY", crack, 0.95), col, "#0E0F10")
    track = g.ramp(g.noise(2.0, 3.0, 0.5, vec=g.mapping(scale=(0.12, 3.0, 1.0))), [(0.45, (0, 0, 0, 1)), (0.75, (1, 1, 1, 1))])
    col = g.mix(g.math("MULTIPLY", track, 0.35), col, "#5A5C60")                            # polished wheel tracks
    wetness = g.ramp(g.noise(0.7, 3.0, 0.5), [(0.45, (0, 0, 0, 1)), (0.8, (1, 1, 1, 1))])
    rough = g.math("SUBTRACT", g.mapr(grain, 0.3, 0.7, 0.78, 0.92), g.math("MULTIPLY", wetness, 0.22))
    height = g.math("SUBTRACT", grain, g.math("MULTIPLY", crack, 0.8))
    reg(g, g.principled(col, 0.0, rough, normal=g.bump(height, 0.55, 0.012)))

    g = SG("MAT_Sea_Water")                                     # shallow emerald -> deep blue, foam, Transmission .95 IOR 1.333
    Y = g.sep(g.world_pos())[1]
    dt = g.mapr(Y, CFG["sea"]["shore_y"] + 0.5, -100.0, 0.0, 1.0)
    base = g.ramp(dt, [(0.0, "#3FB79E"), (0.10, "#1F8E8C"), (0.38, "#0F384C"), (1.0, "#061E30")])
    foam_attr = g.math("MULTIPLY", g.attr("foam", "GEOMETRY", "Fac"), 1.8, clamp=True)
    band = g.mapr(Y, CFG["sea"]["shore_y"] - 4.5, CFG["sea"]["shore_y"] + 0.8, 0.0, 1.0)
    wob = g.noise(1.1, 4.0, 0.6, vec=g.mapping(scale=(1.0, 0.6, 1.0)))
    shore = g.math("GREATER_THAN", g.math("MULTIPLY", wob, band), 0.32)
    lace = g.math("GREATER_THAN", g.noise(6.0, 3.0, 0.6), 0.42)
    foam = g.math("MAXIMUM", foam_attr, g.math("MULTIPLY", shore, g.math("MAXIMUM", lace, 0.35)))
    ripple = g.math("ADD", g.noise(1.4, 5.0, 0.55), g.math("MULTIPLY", g.noise(9.0, 3.0, 0.5), 0.5))
    water = g.principled(base, 0.0, 0.08, transmission=g.mapr(dt, 0.15, 0.6, 0.95, 0.55), ior=1.333,
                         normal=g.bump(ripple, 0.35, 0.10))
    reg(g, g.mix_shader(g.math("MINIMUM", foam, 1.0), water, g.principled("#EEF2F0", 0.0, 0.55)))

    simple("MAT_Rail_Shiny", "#CCCCCC", 0.95, 0.10)
    g = SG("MAT_Rail_Rust")
    n = g.noise(45.0, 6.0, 0.7)
    col = g.mix(g.ramp(g.noise(6.0, 4.0), [(0.3, (0, 0, 0, 1)), (0.8, (1, 1, 1, 1))]), "#5A3825", "#7B4A2B")
    reg(g, g.principled(col, 0.30, 0.80, normal=g.bump(n, 0.7, 0.01)))

    g = SG("MAT_Concrete_Sea")
    col, r, nrm = concrete_graph(g, "#7A7C7D", (0.7, 0.85), wet_z=(-3.6, -0.9), salt=True, scale=1.0)
    # form-liner panels: 4.0 x 0.9 m joints (bump only)
    br = g.n("ShaderNodeTexBrick", offset=0.0, squash=1.0)
    g.put(br.inputs["Vector"], g.mapping(scale=(1.0, 1.0, 1.0), rot=(math.pi / 2, 0, 0)))
    br.inputs["Color1"].default_value = (1, 1, 1, 1)
    br.inputs["Color2"].default_value = (1, 1, 1, 1)
    br.inputs["Mortar"].default_value = (0, 0, 0, 1)
    br.inputs["Scale"].default_value = 1.0
    br.inputs["Mortar Size"].default_value = 0.012
    br.inputs["Mortar Smooth"].default_value = 0.1
    br.inputs["Brick Width"].default_value = 4.0
    br.inputs["Row Height"].default_value = 0.9
    joint = g.math("SUBTRACT", 1.0, br.outputs["Color"])
    col = g.mix(g.math("MULTIPLY", joint, 0.8), col, "#2A2B2B")
    reg(g, g.principled(col, 0.0, r, normal=g.bump(g.math("SUBTRACT", g.noise(140.0, 4.0), g.math("MULTIPLY", joint, 0.9)), 0.5, 0.02)))

    g = SG("MAT_Yellow_Striped")
    x = g.sep(g.n("ShaderNodeTexCoord").outputs["Object"])[0]
    ys, ks = RESEARCH["crossing"]["stripe_yellow"], RESEARCH["crossing"]["stripe_black"]
    m = g.math("MODULO", g.math("ADD", x, 50.0), ys + ks)
    yellow = g.math("LESS_THAN", m, ys)
    tape = g.mix(yellow, "#1A1A1A", "#D99B00")
    reg(g, g.principled(tape, 0.1, 0.35, coat=0.25, coat_rough=0.15, normal=g.bump(g.noise(200.0, 2.0), 0.08, 0.002)))

    # ---------------------------------------------------------------- terrain / city / vegetation
    g = SG("MAT_Terrain")
    w_sand, w_grass, w_soil = g.attr("w_sand"), g.attr("w_grass"), g.attr("w_soil")
    n_big = g.noise(0.06, 4.0, 0.6)
    n_mid = g.noise(0.6, 5.0, 0.6)
    grass = g.mix(g.ramp(n_mid, [(0.30, (0, 0, 0, 1)), (0.65, (1, 1, 1, 1))]), "#34492A", "#5E7336")
    grass = g.mix(g.math("MULTIPLY", g.ramp(n_big, [(0.45, (0, 0, 0, 1)), (0.8, (1, 1, 1, 1))]), 0.6), grass, "#7C7E4C")
    grass = g.mix(g.math("MULTIPLY", g.ramp(g.noise(0.15, 3.0, 0.5), [(0.55, (0, 0, 0, 1)), (0.85, (1, 1, 1, 1))]), 0.7), grass, "#26391F")
    soil = g.mix(g.ramp(g.noise(2.0, 6.0, 0.65), [(0.3, (0, 0, 0, 1)), (0.8, (1, 1, 1, 1))]), "#5D5244", "#7E7364")
    sand = g.mix(g.ramp(g.noise(8.0, 6.0, 0.6), [(0.3, (0, 0, 0, 1)), (0.8, (1, 1, 1, 1))]), "#B8A47C", "#D3C29B")
    Y = g.sep(g.world_pos())[1]
    wetline = g.mapr(Y, CFG["sea"]["shore_y"] + 4.0, CFG["sea"]["shore_y"] - 0.6, 0.0, 1.0)    # sand darkens toward the water
    sand = g.mix(g.math("MULTIPLY", wetline, 0.8), sand, "#6F6249")
    col = g.mix(w_grass, soil, grass)
    col = g.mix(w_sand, col, sand)
    col = g.mix(g.math("MULTIPLY", w_soil, 0.9), col, "#6A6258")
    nz = g.sep(g.n("ShaderNodeNewGeometry").outputs["Normal"])[2]
    rock = g.mapr(nz, 0.86, 0.66, 0.0, 1.0)                                                # steep -> rock
    col = g.mix(g.math("MULTIPLY", rock, g.math("SUBTRACT", 1.0, w_sand)), col, "#66653A")
    reg(g, g.principled(col, 0.0, g.mapr(w_sand, 0.0, 1.0, 0.92, 0.8), normal=g.bump(g.noise(60.0, 4.0), 0.4, 0.05)))

    g = SG("MAT_Building_Wall")                     # PLATEAU boxes: kind (house / apartment / other) drives colour, brick tile, window grid
    br = g.attr("brand", "GEOMETRY", "Fac")
    kind = g.attr("bkind", "GEOMETRY", "Fac")
    fh = g.math("MAXIMUM", g.attr("bfloor", "GEOMETRY", "Fac"), 2.5)                       # storey height (m)
    is_apt = g.math("SUBTRACT", 1.0, g.math("MINIMUM", g.math("ABSOLUTE", g.math("SUBTRACT", kind, 1.0)), 1.0))
    is_oth = g.math("SUBTRACT", 1.0, g.math("MINIMUM", g.math("ABSOLUTE", g.math("SUBTRACT", kind, 2.0)), 1.0))
    house = g.ramp(br, [(0.0, "#E4DED0"), (0.14, "#CFC7B6"), (0.28, "#BFC6C8"), (0.42, "#E0D2B8"), (0.56, "#B3A99C"), (0.7, "#E9E9E4"),
                        (0.84, "#C7B296"), (0.95, "#A8B4A4")], "CONSTANT")
    plaster = g.ramp(br, [(0.0, "#E1DACB"), (0.5, "#C9BFAE"), (0.8, "#DAD7CE")], "CONSTANT")
    px, py, pz = g.sep(g.world_pos())
    wa = g.attr("wang", "GEOMETRY", "Fac")                                                 # wall direction (rad): u runs along the wall
    u = g.math("ADD", g.math("MULTIPLY", px, g.math("COSINE", wa)), g.math("MULTIPLY", py, g.math("SINE", wa)))
    wsd = g.attr("wsd", "GEOMETRY", "Fac")                                                 # per-wall random: window spacing / phase / blank walls
    zr_ = g.math("SUBTRACT", pz, g.attr("bz0", "GEOMETRY", "Fac"))                         # height above the building base
    tv = g.n("ShaderNodeCombineXYZ")                                                       # brick-tile coordinates (24 x 7 cm bricks)
    g.put(tv.inputs["X"], g.math("MULTIPLY", u, 4.2))
    g.put(tv.inputs["Y"], g.math("MULTIPLY", pz, 14.0))
    tile = g.n("ShaderNodeTexBrick", offset=0.5, squash=1.0)
    g.put(tile.inputs["Vector"], tv.outputs["Vector"])
    tile.inputs["Color1"].default_value = hexc("#8E4B33")
    tile.inputs["Color2"].default_value = hexc("#7A3E2B")
    tile.inputs["Mortar"].default_value = hexc("#BDB3A3")
    tile.inputs["Scale"].default_value = 1.0
    tile.inputs["Mortar Size"].default_value = 0.05
    tile.inputs["Mortar Smooth"].default_value = 0.1
    tile.inputs["Brick Width"].default_value = 1.0
    tile.inputs["Row Height"].default_value = 1.0
    apt = g.mix(g.math("LESS_THAN", br, 0.62), plaster, tile.outputs["Color"])             # most condos are brick-tiled, some plastered
    wall = g.mix(is_apt, house, apt)
    wall = g.mix(is_oth, wall, "#C8C9C6")
    dirt = g.ramp(g.noise(0.8, 5.0, 0.6, vec=g.mapping(scale=(1, 1, 0.35))), [(0.4, (0, 0, 0, 1)), (0.85, (1, 1, 1, 1))])
    wall = g.mix(g.math("MULTIPLY", dirt, 0.4), wall, "#5F5B52")
    uv = g.n("ShaderNodeCombineXYZ")                                                       # window grid: 1 window per (2.0 m x storey)
    g.put(uv.inputs["X"], g.math("DIVIDE", g.math("ADD", u, g.math("MULTIPLY", wsd, 6.0)),
                                 g.math("ADD", g.math("ADD", 1.8, g.math("MULTIPLY", wsd, 0.9)), g.math("MULTIPLY", is_apt, 0.8))))
    g.put(uv.inputs["Y"], g.math("DIVIDE", zr_, fh))
    win = g.n("ShaderNodeTexBrick", offset=0.0, squash=1.0)
    g.put(win.inputs["Vector"], uv.outputs["Vector"])
    win.inputs["Color1"].default_value = hexc("#27323B")
    win.inputs["Color2"].default_value = hexc("#33414B")
    g.put(win.inputs["Mortar"], wall)
    win.inputs["Scale"].default_value = 1.0
    g.put(win.inputs["Mortar Size"], g.math("ADD", g.math("SUBTRACT", 0.30, g.math("MULTIPLY", is_apt, 0.04)),
                                            g.math("MULTIPLY", g.math("GREATER_THAN", wsd, 0.82), 0.4)))
    win.inputs["Mortar Smooth"].default_value = 0.05
    win.inputs["Brick Width"].default_value = 1.0
    win.inputs["Row Height"].default_value = 1.0
    is_glass = g.math("LESS_THAN", g.sep(win.outputs["Color"])[0], 0.2)                     # dark pixels = glazing
    reg(g, g.principled(win.outputs["Color"], 0.0, g.mapr(is_glass, 0.0, 1.0, 0.85, 0.12), spec=g.mapr(is_glass, 0.0, 1.0, 0.5, 1.0)))

    g = SG("MAT_Building_Roof")                      # pitched tile / slate roofs and flat concrete roofs
    br = g.attr("brand", "GEOMETRY", "Fac")
    flat = g.attr("rflat", "GEOMETRY", "Fac")
    base = g.ramp(br, [(0.0, "#454A50"), (0.2, "#6B3E37"), (0.4, "#33504E"), (0.6, "#2A2C30"), (0.8, "#5A4A3E"), (0.92, "#7A7F86")], "CONSTANT")
    px, py, pz = g.sep(g.world_pos())
    rv = g.n("ShaderNodeCombineXYZ")
    g.put(rv.inputs["X"], g.math("MULTIPLY", px, 3.0))
    g.put(rv.inputs["Y"], g.math("MULTIPLY", py, 3.6))
    rt = g.n("ShaderNodeTexBrick", offset=0.5, squash=1.0)
    g.put(rt.inputs["Vector"], rv.outputs["Vector"])
    g.put(rt.inputs["Color1"], base)
    rt.inputs["Color2"].default_value = hexc("#888888")
    rt.inputs["Mortar"].default_value = hexc("#101010")
    rt.inputs["Mortar Size"].default_value = 0.04
    rt.inputs["Mortar Smooth"].default_value = 0.1
    rt.inputs["Brick Width"].default_value = 1.0
    rt.inputs["Row Height"].default_value = 1.0
    tilecol = g.mix(0.25, rt.outputs["Color"], base)
    concrete_ = g.mix(g.noise(2.0, 5.0, 0.6), "#6E7071", "#8B8C8A")
    col = g.mix(flat, tilecol, concrete_)
    reg(g, g.principled(col, 0.05, 0.62, normal=g.bump(g.math("SUBTRACT", 1.0, g.sep(rt.outputs["Color"])[0]), 0.25, 0.02)))
    simple("MAT_Balcony", "#D8D6CF", 0.0, 0.7)
    simple("MAT_Rail_Glass", "#8FADB4", 0.1, 0.12)

    g = SG("MAT_Gutter")                             # gutters, downpipes, porch canopies: colour follows the building hash
    br = g.attr("brand", "GEOMETRY", "Fac")
    reg(g, g.principled(g.ramp(br, [(0.0, "#3A2F29"), (0.25, "#D8D8D2"), (0.5, "#4B4F53"), (0.75, "#6A5A49"), (0.9, "#1F2124")], "CONSTANT"), 0.15, 0.42))

    g = SG("MAT_Door")
    br = g.math("FRACT", g.math("MULTIPLY", g.attr("brand", "GEOMETRY", "Fac"), 7.3))
    door = g.ramp(br, [(0.0, "#3E2A20"), (0.17, "#D9D8D2"), (0.34, "#5A4636"), (0.5, "#2F3B44"), (0.67, "#7A6A58"), (0.84, "#8B2E24")], "CONSTANT")
    reg(g, g.principled(door, 0.1, 0.45, normal=g.bump(g.noise(40.0, 2.0, 0.5), 0.15, 0.01)))

    g = SG("MAT_Shutter")                            # roller garage shutters: horizontal slats
    br = g.math("FRACT", g.math("MULTIPLY", g.attr("brand", "GEOMETRY", "Fac"), 5.7))
    base = g.ramp(br, [(0.0, "#8A8E90"), (0.25, "#5E6B60"), (0.5, "#B8B2A2"), (0.75, "#4A4D52")], "CONSTANT")
    slat = g.math("GREATER_THAN", g.math("PINGPONG", g.sep(g.world_pos())[2], 0.045), 0.022)
    reg(g, g.principled(g.mix(g.math("MULTIPLY", slat, 0.35), base, "#2A2B2C"), 0.5, 0.42, normal=g.bump(slat, 0.5, 0.01)))

    simple("MAT_AC_Body", "#E3E4E0", 0.0, 0.42)
    simple("MAT_Fence_Alu", "#2E3134", 0.7, 0.4)

    g = SG("MAT_Garbage_Box")                        # grey mesh bin store
    chk = g.n("ShaderNodeTexChecker")
    g.put(chk.inputs["Vector"], g.coord())
    chk.inputs["Scale"].default_value = 35.0
    chk.inputs["Color1"].default_value = hexc("#7A8285")
    chk.inputs["Color2"].default_value = hexc("#565D60")
    reg(g, g.principled(chk.outputs["Color"], 0.5, 0.45))

    g = SG("MAT_Block_Wall")                         # concrete block boundary walls (39 x 19 cm units)
    br = g.attr("brand", "GEOMETRY", "Fac")
    wa = g.attr("wang", "GEOMETRY", "Fac")
    px, py, pz = g.sep(g.world_pos())
    u = g.math("ADD", g.math("MULTIPLY", px, g.math("COSINE", wa)), g.math("MULTIPLY", py, g.math("SINE", wa)))
    tv = g.n("ShaderNodeCombineXYZ")
    g.put(tv.inputs["X"], g.math("DIVIDE", u, 0.39))
    g.put(tv.inputs["Y"], g.math("DIVIDE", pz, 0.19))
    blk = g.n("ShaderNodeTexBrick", offset=0.5, squash=1.0)
    g.put(blk.inputs["Vector"], tv.outputs["Vector"])
    c1 = g.ramp(br, [(0.0, "#B8B6AE"), (0.35, "#A6A49C"), (0.7, "#C9C2B2")], "CONSTANT")
    g.put(blk.inputs["Color1"], c1)
    g.put(blk.inputs["Color2"], g.mix(0.16, c1, "#6E6C66"))
    blk.inputs["Mortar"].default_value = hexc("#7E7C76")
    blk.inputs["Scale"].default_value = 1.0
    blk.inputs["Mortar Size"].default_value = 0.035
    blk.inputs["Mortar Smooth"].default_value = 0.1
    blk.inputs["Brick Width"].default_value = 1.0
    blk.inputs["Row Height"].default_value = 1.0
    dirt = g.ramp(g.noise(1.5, 5.0, 0.6, vec=g.mapping(scale=(1, 1, 0.5))), [(0.4, (0, 0, 0, 1)), (0.85, (1, 1, 1, 1))])
    col = g.mix(g.math("MULTIPLY", dirt, 0.45), blk.outputs["Color"], "#4E4B44")
    reg(g, g.principled(col, 0.0, 0.88, normal=g.bump(blk.outputs["Fac"], 0.7, 0.01)))

    g = SG("MAT_Wall_Plaster")                       # painted mortar boundary walls
    br = g.attr("brand", "GEOMETRY", "Fac")
    base = g.ramp(br, [(0.0, "#E6E1D3"), (0.3, "#D2C8B4"), (0.55, "#EDEBE4"), (0.8, "#BFB6A4")], "CONSTANT")
    streak = g.ramp(g.noise(3.0, 5.0, 0.6, vec=g.mapping(scale=(1.0, 1.0, 0.25))), [(0.45, (0, 0, 0, 1)), (0.85, (1, 1, 1, 1))])
    col = g.mix(g.math("MULTIPLY", streak, 0.35), base, "#6C665A")
    reg(g, g.principled(col, 0.0, 0.85, normal=g.bump(g.noise(90.0, 3.0, 0.6), 0.25, 0.01)))

    def foliage(name, dark, light, warm, noise_scale):
        g = SG(name)
        tr = g.attr("trand", "GEOMETRY", "Fac")
        sh = g.attr("tshade", "GEOMETRY", "Fac")
        col = g.mix(tr, dark, light)
        col = g.mix(g.ramp(g.noise(noise_scale, 4.0, 0.6), [(0.4, (0, 0, 0, 1)), (0.8, (1, 1, 1, 1))]), col, warm)
        gloom = g.mapr(sh, 0.0, 1.0, 0.55, 0.0)                                        # dark inside/below the crown, lit on top
        col = g.mix(gloom, col, "#040604")
        reg(g, g.principled(col, 0.0, 0.8, sheen=0.35, normal=g.bump(g.noise(26.0, 4.0, 0.6), 0.6, 0.04)))

    foliage("MAT_Tree_Leaf", "#15290F", "#2E4A1C", "#465A25", 1.2)                     # evergreen broadleaf
    foliage("MAT_Pine_Leaf", "#0D1811", "#1C2D22", "#2E3D24", 2.0)                     # black pine / cedar

    g = SG("MAT_Leaf_Card")                            # cluster of leaflets (procedural alpha) for broadleaf crowns and shrubs
    uv = g.n("ShaderNodeTexCoord").outputs["UV"]
    ux, uy, _uz = g.sep(uv)
    tr, cr, sh = g.attr("trand"), g.attr("crand"), g.attr("tshade")
    off = g.math("ADD", g.math("MULTIPLY", cr, 37.0), g.math("MULTIPLY", tr, 13.0))
    vec = g.n("ShaderNodeCombineXYZ")
    g.put(vec.inputs["X"], g.math("ADD", g.math("MULTIPLY", ux, 7.5), off))
    g.put(vec.inputs["Y"], g.math("ADD", g.math("MULTIPLY", uy, 7.5), g.math("MULTIPLY", off, 0.7)))
    vor = g.n("ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature="F1")
    g.put(vor.inputs["Vector"], vec.outputs["Vector"])
    vor.inputs["Scale"].default_value = 1.0
    vor.inputs["Randomness"].default_value = 0.9
    leaflet = g.mapr(vor.outputs["Distance"], 0.36, 0.60, 1.0, 0.0)
    cen = g.n("ShaderNodeCombineXYZ")
    g.put(cen.inputs["X"], g.math("MULTIPLY", g.math("SUBTRACT", ux, 0.5), 2.0))
    g.put(cen.inputs["Y"], g.math("MULTIPLY", g.math("SUBTRACT", uy, 0.5), 2.0))
    rad = g.n("ShaderNodeVectorMath", operation="LENGTH")
    g.put(rad.inputs[0], cen.outputs["Vector"])
    alpha = g.math("MULTIPLY", leaflet, g.mapr(rad.outputs["Value"], 0.65, 1.0, 1.0, 0.0))
    alpha = g.math("MULTIPLY", alpha, g.mapr(g.noise(9.0, 3.0, 0.5, vec=vec.outputs["Vector"]), 0.12, 0.30, 0.0, 1.0))         # ragged dropout
    col = g.mix(tr, "#274720", "#5F8632")
    lite = g.math("MULTIPLY", g.sep(vor.outputs["Color"])[0], 0.55)                          # per-leaflet brightness
    col = g.mix(lite, col, "#98A64B")
    col = g.mix(g.mapr(sh, 0.0, 1.0, 0.5, 0.0), col, "#040604")
    reg(g, g.mix_shader(alpha, g.transparent(), g.principled(col, 0.0, 0.72, sheen=0.3, spec=0.3)))

    g = SG("MAT_Pine_Card")                            # needle spray: radial spokes + dense centre
    uv = g.n("ShaderNodeTexCoord").outputs["UV"]
    ux, uy, _uz = g.sep(uv)
    tr, cr, sh = g.attr("trand"), g.attr("crand"), g.attr("tshade")
    off = g.math("ADD", g.math("MULTIPLY", cr, 6.0), g.math("MULTIPLY", tr, 3.0))
    px, py = g.math("MULTIPLY", g.math("SUBTRACT", ux, 0.5), 2.0), g.math("MULTIPLY", g.math("SUBTRACT", uy, 0.5), 2.0)
    cen = g.n("ShaderNodeCombineXYZ")
    g.put(cen.inputs["X"], px)
    g.put(cen.inputs["Y"], py)
    rad = g.n("ShaderNodeVectorMath", operation="LENGTH")
    g.put(rad.inputs[0], cen.outputs["Vector"])
    r_ = rad.outputs["Value"]
    ang = g.math("ARCTAN2", py, px)
    # needles: Voronoi cells in polar space (many angular cells, long radially) = irregular radial needle clusters
    polar = g.n("ShaderNodeCombineXYZ")
    g.put(polar.inputs["X"], g.math("ADD", g.math("MULTIPLY", ang, 3.9), off))
    g.put(polar.inputs["Y"], g.math("ADD", g.math("MULTIPLY", r_, 0.55), g.math("MULTIPLY", off, 0.37)))
    vp = g.n("ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature="F1")
    g.put(vp.inputs["Vector"], polar.outputs["Vector"])
    vp.inputs["Scale"].default_value = 1.0
    vp.inputs["Randomness"].default_value = 1.0
    needles = g.mapr(vp.outputs["Distance"], 0.16, 0.40, 1.0, 0.0)
    fine = g.mapr(g.noise(14.0, 3.0, 0.5, vec=cen.outputs["Vector"]), 0.30, 0.55, 0.0, 1.0)
    alpha = g.math("MAXIMUM", g.math("MULTIPLY", needles, g.mapr(r_, 0.5, 1.0, 1.0, 0.0)), g.mapr(r_, 0.08, 0.55, 1.0, 0.0))
    alpha = g.math("MULTIPLY", alpha, g.math("ADD", 0.6, g.math("MULTIPLY", fine, 0.4)))
    col = g.mix(tr, "#1B2D22", "#3E5D35")
    col = g.mix(g.math("MULTIPLY", fine, 0.35), col, "#6D7A45")
    col = g.mix(g.mapr(sh, 0.0, 1.0, 0.5, 0.0), col, "#030503")
    reg(g, g.mix_shader(alpha, g.transparent(), g.principled(col, 0.0, 0.75, sheen=0.2, spec=0.2)))

    g = SG("MAT_Grass_Dry")                            # dry golden grass and pampas on the banks
    col = g.mix(g.noise(1.6, 3.0), "#7E7A3C", "#C2AC62")
    col = g.mix(g.ramp(g.noise(0.4, 3.0), [(0.5, (0, 0, 0, 1)), (0.8, (1, 1, 1, 1))]), col, "#587336")
    reg(g, g.principled(col, 0.0, 0.75, sheen=0.4))

    g = SG("MAT_Leaf_Litter")
    lr = g.attr("lrand", "GEOMETRY", "Fac")
    col = g.ramp(lr, [(0.0, "#5A3A1F"), (0.25, "#7A5628"), (0.5, "#8F6C36"), (0.75, "#3F2C17"), (0.95, "#6E6A3A")], "CONSTANT")
    reg(g, g.principled(col, 0.0, 0.9))
    simple("MAT_Tree_Trunk", "#3A2E22", 0.0, 0.9)

    # ---------------------------------------------------------------- railway
    g = SG("MAT_Ballast_Bed")
    r_ = g.noise(220.0, 3.0, 0.7)
    col = g.mix(g.noise(7.0, 5.0, 0.6), "#5C5A56", "#8D8A83")
    col = g.mix(g.ramp(g.noise(3.0, 3.0, 0.5), [(0.5, (0, 0, 0, 1)), (0.8, (1, 1, 1, 1))]), col, "#3D3A36")   # oil / dirt
    reg(g, g.principled(col, 0.0, 0.9, normal=g.bump(r_, 1.2, 0.03)))

    g = SG("MAT_Ballast_Rock")
    rv = g.n("ShaderNodeObjectInfo").outputs["Random"]
    col = g.mix(rv, "#4D4B47", "#9A968E")
    col = g.mix(g.ramp(g.noise(40.0, 2.0), [(0.4, (0, 0, 0, 1)), (0.7, (1, 1, 1, 1))]), col, "#6E655A")
    reg(g, g.principled(col, 0.0, 0.85, normal=g.bump(g.noise(300.0, 2.0), 0.4, 0.004)))

    g = SG("MAT_Sleeper_Wood")
    grain = g.noise(26.0, 6.0, 0.7, vec=g.mapping(scale=(6.0, 0.7, 6.0)))
    col = g.mix(grain, "#2C2119", "#54402E")
    vd = g.voro_edge(3.0, vec=g.mapping(scale=(8.0, 0.5, 8.0)))
    col = g.mix(g.math("LESS_THAN", vd, 0.03), col, "#0E0B08")
    reg(g, g.principled(col, 0.0, 0.85, normal=g.bump(g.noise(80.0, 4.0, 0.6, vec=g.mapping(scale=(5.0, 0.6, 5.0))), 0.5, 0.01)))

    g = SG("MAT_Sleeper_PC")
    col, r, nrm = concrete_graph(g, "#8A8A85", (0.75, 0.92), cracks=False, streak=False)
    reg(g, g.principled(col, 0.0, r, normal=nrm))

    g = SG("MAT_Rubber_Crossing")
    ribs = g.math("GREATER_THAN", g.math("PINGPONG", g.sep(g.n("ShaderNodeTexCoord").outputs["Object"])[0], 0.06), 0.03)
    col = g.mix(g.noise(3.0, 5.0), "#1D1D1E", "#343436")
    reg(g, g.principled(col, 0.0, 0.88, normal=g.bump(g.math("ADD", ribs, g.noise(150.0, 3.0)), 0.6, 0.006)))

    # ---------------------------------------------------------------- concrete / platform / poles
    for nm, base, rough_ in (("MAT_Concrete", "#8E8F8B", (0.7, 0.9)), ("MAT_Concrete_Pole", "#9C9C95", (0.72, 0.9)),
                             ("MAT_Platform_Top", "#7C7D7A", (0.8, 0.95))):
        g = SG(nm)
        col, r, nrm = concrete_graph(g, base, rough_, cracks=(nm != "MAT_Concrete_Pole"), scale=1.0)
        reg(g, g.principled(col, 0.0, r, normal=nrm))
    g = SG("MAT_Platform_Wall")                       # weathered platform side: cracks + salt + wet foot
    col, r, nrm = concrete_graph(g, "#85857F", (0.7, 0.9), wet_z=(-0.6, 0.4), salt=True)
    reg(g, g.principled(col, 0.0, r, normal=nrm))

    g = SG("MAT_Slate_Roof")
    streak = g.ramp(g.noise(3.0, 5.0, 0.6, vec=g.mapping(scale=(1.6, 0.12, 0.12))), [(0.45, (0, 0, 0, 1)), (0.85, (1, 1, 1, 1))])
    col = g.mix(g.noise(1.2, 6.0, 0.65), "#8C8A85", "#6F6D66")
    col = g.mix(g.math("MULTIPLY", streak, 0.55), col, "#4D4A44")
    rust = g.ramp(g.noise(5.0, 4.0, 0.6, vec=g.mapping(scale=(2.5, 0.2, 0.2))), [(0.62, (0, 0, 0, 1)), (0.9, (1, 1, 1, 1))])
    col = g.mix(g.math("MULTIPLY", rust, 0.7), col, "#7A4A2A")
    moss = g.ramp(g.noise(2.0, 5.0, 0.6), [(0.68, (0, 0, 0, 1)), (0.85, (1, 1, 1, 1))])
    col = g.mix(g.math("MULTIPLY", moss, 0.6), col, "#5A6A3A")
    reg(g, g.principled(col, 0.05, 0.72, normal=g.bump(g.noise(120.0, 3.0), 0.3, 0.01)))

    # ---------------------------------------------------------------- paint / signs
    g = SG("MAT_Paint_White")                          # road paint, faded/scuffed (alpha-mixed onto asphalt)
    fade = g.math("GREATER_THAN", g.noise(9.0, 6.0, 0.7), 0.36)
    fade = g.math("MULTIPLY", fade, g.math("GREATER_THAN", g.noise(60.0, 3.0), 0.28))
    reg(g, g.mix_shader(fade, g.transparent(), g.principled("#D9D9D2", 0.0, 0.75, normal=g.bump(g.noise(200.0, 2.0), 0.3, 0.004))))
    g = SG("MAT_Revetment")                            # sloped concrete revetment: weathered slabs, joints, sand & wet toe
    col, r, nrm = concrete_graph(g, "#A3A4A0", (0.7, 0.88), wet_z=(-3.4, -1.0), salt=True, cracks=False, streak=False)
    br = g.n("ShaderNodeTexBrick", offset=0.0, squash=1.0)
    g.put(br.inputs["Vector"], g.mapping(scale=(1.0, 1.0, 1.0)))
    br.inputs["Color1"].default_value = (1, 1, 1, 1)
    br.inputs["Color2"].default_value = (1, 1, 1, 1)
    br.inputs["Mortar"].default_value = (0, 0, 0, 1)
    br.inputs["Scale"].default_value = 1.0
    br.inputs["Mortar Size"].default_value = 0.012
    br.inputs["Mortar Smooth"].default_value = 0.05
    br.inputs["Brick Width"].default_value = 3.0
    br.inputs["Row Height"].default_value = 2.6
    joint = g.math("SUBTRACT", 1.0, br.outputs["Color"])
    col = g.mix(g.math("MULTIPLY", joint, 0.85), col, "#3A3B3A")
    zz_ = g.sep(g.world_pos())[2]
    sand = g.math("MULTIPLY", g.mapr(zz_, -2.0, -2.9, 0.0, 1.0), g.ramp(g.noise(2.2, 4.0, 0.6), [(0.35, (0, 0, 0, 1)), (0.7, (1, 1, 1, 1))]))
    col = g.mix(g.math("MULTIPLY", sand, 0.85), col, "#B7A57F")                                          # drifted sand near the toe
    reg(g, g.principled(col, 0.0, r, normal=g.bump(joint, 0.6, 0.03, normal=nrm)))

    g = SG("MAT_Paint_Orange")                         # Route 134 centre line: no-overtaking (orange), faded like the white paint
    fade = g.math("GREATER_THAN", g.noise(8.0, 6.0, 0.7), 0.34)
    fade = g.math("MULTIPLY", fade, g.math("GREATER_THAN", g.noise(55.0, 3.0), 0.26))
    reg(g, g.mix_shader(fade, g.transparent(), g.principled("#E5751A", 0.0, 0.7, normal=g.bump(g.noise(200.0, 2.0), 0.3, 0.004))))

    g = SG("MAT_Stone_Black")                          # weathered black rubble-stone (nozura-zumi) wall north of the track
    vv = g.mapping(scale=(2.1, 2.1, 2.9))
    cell = g.n("ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature="F1")
    edge = g.n("ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature="DISTANCE_TO_EDGE")
    for vn in (cell, edge):
        g.put(vn.inputs["Vector"], vv)
        vn.inputs["Scale"].default_value = 1.0
        vn.inputs["Randomness"].default_value = 1.0
    blk = g.sep(cell.outputs["Color"])[0]                                          # random value per block
    shade = g.ramp(blk, [(0.0, "#060607"), (0.5, "#0F1011"), (1.0, "#1B1C1E")])
    joint = g.math("LESS_THAN", edge.outputs["Distance"], 0.055)
    col = g.mix(joint, shade, "#030304")
    zz_ = g.sep(g.world_pos())[2]
    moss = g.ramp(g.noise(3.0, 5.0, 0.6, vec=g.mapping(scale=(1, 1, 0.6))), [(0.55, (0, 0, 0, 1)), (0.85, (1, 1, 1, 1))])
    col = g.mix(g.math("MULTIPLY", moss, g.mapr(zz_, 0.9, -0.3, 0.0, 0.7)), col, "#2C3A29")             # green damp at the foot
    salt = g.ramp(g.noise(5.0, 4.0, 0.6), [(0.62, (0, 0, 0, 1)), (0.9, (1, 1, 1, 1))])
    col = g.mix(g.math("MULTIPLY", salt, 0.22), col, "#5E5D58")                                        # salt bloom
    hgt = g.math("ADD", g.mapr(edge.outputs["Distance"], 0.0, 0.25, 0.0, 1.0), g.math("MULTIPLY", g.noise(60.0, 4.0), 0.25))
    reg(g, g.principled(col, 0.0, g.mapr(blk, 0.0, 1.0, 0.62, 0.9), normal=g.bump(hgt, 1.1, 0.04)))

    g = SG("MAT_Wood_Fence")                           # sun-bleached timber rails
    grain = g.noise(24.0, 6.0, 0.7, vec=g.mapping(scale=(0.25, 7.0, 7.0)))
    col = g.mix(grain, "#4A4137", "#85796A")
    col = g.mix(g.ramp(g.noise(2.0, 4.0), [(0.55, (0, 0, 0, 1)), (0.85, (1, 1, 1, 1))]), col, "#33402B")   # mildew
    reg(g, g.principled(col, 0.0, 0.88, normal=g.bump(g.noise(90.0, 4.0, 0.6, vec=g.mapping(scale=(0.3, 6.0, 6.0))), 0.5, 0.01)))

    g = SG("MAT_Weeds")
    col = g.mix(g.noise(1.4, 3.0), "#465F26", "#9A9448")
    reg(g, g.principled(col, 0.0, 0.8, sheen=0.4))
    simple("MAT_Asphalt_Patch", "#212327", 0.0, 0.7)

    g = SG("MAT_Striped_Z")                              # alarm pole / gate machine box: yellow-black bands along world Z
    zz = g.sep(g.n("ShaderNodeTexCoord").outputs["Object"])[2]
    band = g.math("LESS_THAN", g.math("MODULO", g.math("ADD", zz, 50.0), 0.50), 0.28)
    col = g.mix(band, "#161616", "#E2A800")
    dirt = g.ramp(g.noise(6.0, 5.0, 0.6, vec=g.mapping(scale=(1, 1, 0.5))), [(0.55, (0, 0, 0, 1)), (0.9, (1, 1, 1, 1))])
    col = g.mix(g.math("MULTIPLY", dirt, 0.35), col, "#6E6A58")
    reg(g, g.principled(col, 0.1, 0.42, coat=0.2, normal=g.bump(g.noise(180.0, 3.0), 0.12, 0.003)))
    simple("MAT_Pole_White", "#DCDDDA", 0.3, 0.45)
    g = SG("MAT_Safety_Stripe")                          # yellow-black diagonal safety stripes (bogie guards, skirt, steps)
    tcx, tcy, tcz = g.sep(g.n("ShaderNodeTexCoord").outputs["Object"])
    u = g.math("ADD", g.math("ADD", tcx, tcy), tcz)
    yel = g.math("LESS_THAN", g.math("MODULO", g.math("ADD", u, 100.0), 0.36), 0.18)
    col = g.mix(yel, "#141414", "#E6B000")
    grime = g.ramp(g.noise(7.0, 5.0, 0.6, vec=g.mapping(scale=(1, 1, 0.6))), [(0.5, (0, 0, 0, 1)), (0.9, (1, 1, 1, 1))])
    col = g.mix(g.math("MULTIPLY", grime, 0.5), col, "#3A352A")
    reg(g, g.principled(col, 0.1, 0.5, coat=0.15, normal=g.bump(g.noise(150.0, 3.0), 0.15, 0.004)))
    g = SG("MAT_Cabinet_Brown")                        # rust-brown signal control cabinets (Street View)
    col = g.mix(g.ramp(g.noise(3.0, 5.0, 0.6, vec=g.mapping(scale=(1, 1, 0.5))), [(0.45, (0, 0, 0, 1)), (0.85, (1, 1, 1, 1))]), "#6E4B34", "#8A6446")
    col = g.mix(g.ramp(g.noise(40.0, 4.0), [(0.62, (0, 0, 0, 1)), (0.9, (1, 1, 1, 1))]), col, "#4A2E1C")            # rust speckle
    reg(g, g.principled(col, 0.35, 0.6, normal=g.bump(g.noise(120.0, 3.0), 0.25, 0.006)))
    g = SG("MAT_Cabinet_Beige")
    col = g.mix(g.ramp(g.noise(3.0, 5.0, 0.6, vec=g.mapping(scale=(1, 1, 0.5))), [(0.4, (0, 0, 0, 1)), (0.85, (1, 1, 1, 1))]), "#D2CAB8", "#A99F8A")
    reg(g, g.principled(col, 0.1, 0.55))
    simple("MAT_Wire_Feeder", "#0C0D0E", 0.0, 0.4)
    g = SG("MAT_Wood_Post")                            # weathered station timber (posts, beams)
    grain = g.noise(22.0, 6.0, 0.7, vec=g.mapping(scale=(6.0, 6.0, 0.3)))
    col = g.mix(grain, "#3E2F22", "#6A5640")
    col = g.mix(g.ramp(g.noise(2.2, 4.0, 0.6, vec=g.mapping(scale=(1, 1, 0.4))), [(0.55, (0, 0, 0, 1)), (0.85, (1, 1, 1, 1))]), col, "#8A8474")   # bleached
    reg(g, g.principled(col, 0.0, 0.88, normal=g.bump(g.noise(80.0, 4.0, 0.6, vec=g.mapping(scale=(6.0, 6.0, 0.4))), 0.5, 0.008)))
    simple("MAT_Wood_Dark", "#2B1F17", 0.0, 0.8)
    emissive("MAT_Lamp_Fluor", "#E9F2FF", 6.0, base="#DDDDDD")
    simple("MAT_Vending_Red", "#C2151B", 0.05, 0.35, coat=0.3)
    simple("MAT_Sign_Mint", "#A5D1BC", 0.0, 0.5)
    simple("MAT_Roof_Hut", "#B9BABA", 0.3, 0.6)
    simple("MAT_Granite", "#6D7072", 0.05, 0.55)

    g = SG("MAT_Ad_Poster")                            # advertisement boards along the platform back wall
    r_ = g.attr("adrand", "GEOMETRY", "Fac")
    col = g.ramp(r_, [(0.0, "#C7282B"), (0.125, "#2B63B3"), (0.25, "#F1C40F"), (0.375, "#2E9B57"), (0.5, "#F2F2F0"), (0.625, "#E67E22"),
                      (0.75, "#7D3C98"), (0.875, "#22A8C8")], "CONSTANT")
    col = g.mix(g.math("GREATER_THAN", g.noise(2.6, 2.0), 0.58), col, "#EFEFEA")
    reg(g, g.principled(col, 0.0, 0.5, spec=0.5))

    g = SG("MAT_Hut_Wall")                             # cream timber siding
    zw_ = g.sep(g.world_pos())[2]
    boards = g.math("PINGPONG", zw_, 0.075)
    col = g.mix(g.noise(2.5, 5.0, 0.6), "#D9CFB6", "#C0B497")
    col = g.mix(g.mapr(zw_, 1.2, 0.0, 0.0, 0.5), col, "#5A5644")                                 # splash / damp near the ground
    reg(g, g.principled(col, 0.0, 0.8, normal=g.bump(boards, 0.6, 0.02)))

    g = SG("MAT_Siding_Corr")                          # corrugated metal siding (gable ends), faces +-X
    yy_ = g.sep(g.world_pos())[1]
    wave = g.math("PINGPONG", yy_, 0.045)
    col = g.mix(g.noise(1.4, 5.0, 0.6, vec=g.mapping(scale=(1, 0.4, 0.2))), "#6D6744", "#8B8058")
    col = g.mix(g.ramp(g.noise(4.0, 4.0, 0.6, vec=g.mapping(scale=(1, 2.0, 0.15))), [(0.6, (0, 0, 0, 1)), (0.9, (1, 1, 1, 1))]), col, "#5B3B22")   # rust runs
    reg(g, g.principled(col, 0.3, 0.7, normal=g.bump(wave, 0.8, 0.03)))

    g = SG("MAT_Stone_Light")                          # yellow-brown rubble-stone masonry (Commons entrance photo)
    vv = g.mapping(scale=(3.4, 3.4, 4.4))
    cell = g.n("ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature="F1")
    edge = g.n("ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature="DISTANCE_TO_EDGE")
    for vn in (cell, edge):
        g.put(vn.inputs["Vector"], vv)
        vn.inputs["Scale"].default_value = 1.0
        vn.inputs["Randomness"].default_value = 1.0
    blk = g.sep(cell.outputs["Color"])[0]
    shade = g.ramp(blk, [(0.0, "#6B5F45"), (0.5, "#8B7C5A"), (1.0, "#A89873")])
    col = g.mix(g.math("LESS_THAN", edge.outputs["Distance"], 0.055), shade, "#2A2418")
    zz2 = g.sep(g.world_pos())[2]
    moss = g.ramp(g.noise(3.0, 5.0, 0.6, vec=g.mapping(scale=(1, 1, 0.6))), [(0.55, (0, 0, 0, 1)), (0.85, (1, 1, 1, 1))])
    col = g.mix(g.math("MULTIPLY", moss, g.mapr(zz2, 1.6, 0.0, 0.0, 0.6)), col, "#4A5B34")
    hgt = g.math("ADD", g.mapr(edge.outputs["Distance"], 0.0, 0.25, 0.0, 1.0), g.math("MULTIPLY", g.noise(60.0, 4.0), 0.25))
    reg(g, g.principled(col, 0.0, g.mapr(blk, 0.0, 1.0, 0.7, 0.92), normal=g.bump(hgt, 1.0, 0.04)))

    g = SG("MAT_Stone_House")                          # grey-brown random rubble facing of house retaining walls (finer than the station wall)
    vv = g.mapping(scale=(6.0, 6.0, 8.5))
    cell = g.n("ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature="F1")
    edge = g.n("ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature="DISTANCE_TO_EDGE")
    for vn in (cell, edge):
        g.put(vn.inputs["Vector"], vv)
        vn.inputs["Scale"].default_value = 1.0
        vn.inputs["Randomness"].default_value = 0.9
    blk = g.sep(cell.outputs["Color"])[0]
    shade = g.ramp(blk, [(0.0, "#4F4B43"), (0.5, "#6E695C"), (1.0, "#8C8676")])
    col = g.mix(g.math("LESS_THAN", edge.outputs["Distance"], 0.07), shade, "#26231D")
    zz2 = g.sep(g.world_pos())[2]
    moss = g.ramp(g.noise(3.0, 5.0, 0.6, vec=g.mapping(scale=(1, 1, 0.6))), [(0.55, (0, 0, 0, 1)), (0.85, (1, 1, 1, 1))])
    col = g.mix(g.math("MULTIPLY", moss, g.mapr(zz2, 1.6, 0.0, 0.0, 0.5)), col, "#44552F")
    hgt = g.math("ADD", g.mapr(edge.outputs["Distance"], 0.0, 0.25, 0.0, 1.0), g.math("MULTIPLY", g.noise(60.0, 4.0), 0.25))
    reg(g, g.principled(col, 0.0, g.mapr(blk, 0.0, 1.0, 0.75, 0.93), normal=g.bump(hgt, 1.0, 0.03)))

    simple("MAT_Tactile_Yellow", "#E0B300", 0.0, 0.6)
    simple("MAT_Sign_Yellow", "#F2C200", 0.0, 0.45)
    simple("MAT_Sign_Black", "#111111", 0.0, 0.5)
    simple("MAT_Sign_White", "#E8E8E4", 0.0, 0.45)
    simple("MAT_Sign_Blue", "#16407A", 0.0, 0.45)
    simple("MAT_Sign_Red", "#B31212", 0.0, 0.45)
    simple("MAT_Gate_Yellow", "#E0A800", 0.05, 0.4, coat=0.2)
    simple("MAT_Gate_Blue", "#1F4E8C", 0.05, 0.4, coat=0.2)
    simple("MAT_Reflector_Red", "#C01818", 0.0, 0.2, coat=0.6)
    simple("MAT_Black", "#111112", 0.0, 0.5)
    simple("MAT_Signal_Grey", "#9AA0A4", 0.2, 0.45)
    simple("MAT_Orange_Frame", "#E06A10", 0.1, 0.4)
    simple("MAT_Mirror_Curve", "#D8DEE0", 1.0, 0.02)
    simple("MAT_Wood_Bench", "#6B4A2E", 0.0, 0.75)
    simple("MAT_Wire", "#111214", 0.0, 0.45)
    simple("MAT_Insulator", "#B8A98C", 0.0, 0.25, coat=0.5)
    simple("MAT_Transformer", "#6D7379", 0.4, 0.5)
    simple("MAT_White_Panel", "#E9EAEA", 0.0, 0.4)
    simple("MAT_Vending_Blue", "#1E5FA8", 0.0, 0.35, coat=0.3)
    simple("MAT_Train_Dark", "#1B1C1E", 0.3, 0.55)
    simple("MAT_Train_Roof", "#C9C8C1", 0.2, 0.55)
    simple("MAT_Train_Metal", "#5A5D60", 0.9, 0.4)
    simple("MAT_Bellows", "#0E0F10", 0.0, 0.85)
    g = SG("MAT_Glass_Train")
    reg(g, g.principled("#16232B", 0.0, 0.04, spec=1.0, coat=0.5, coat_rough=0.02, emit="#FFD9A6", emit_strength=0.18))   # lit cabin glow
    g = SG("MAT_Cover_PVC")                             # thin vinyl cover over the PASMO gate (salt protection)
    reg(g, g.mix_shader(0.12, g.transparent(), g.principled("#DDE4E6", 0.0, 0.15)))
    g = SG("MAT_Glass_Clear")
    reg(g, g.mix_shader(0.08, g.transparent(), g.principled("#C8D8DC", 0.0, 0.03)))

    emissive("MAT_Lamp_Head", "#FFD7A0", 9.0, base="#EEEEEE")           # warm LED
    emissive("MAT_Lamp_Tail", "#FF2010", 3.0, base="#701010")
    emissive("MAT_Lamp_Warm", "#FFC98A", 6.0)
    emissive("MAT_Alarm_Lamp_On", "#8C0000", 15.0, base="#600808")     # spec 5.1: Emission 15.0, red (deep-red tint: AgX turns
                                                                       # pure-red highlights of this power pink)
    simple("MAT_Alarm_Lamp_Off", "#3A0A08", 0.0, 0.15, coat=0.6)

    # ---------------------------------------------------------------- metals
    g = SG("MAT_Steel_Galv")                               # zinc-plated guard rail with rust bleed
    col, met, r, nrm = steel_graph(g, hexc("#A9AEB0"), 0.85, 0.42, rust=0.55)
    reg(g, g.principled(col, met, r, normal=nrm))
    g = SG("MAT_Steel_Grey")
    col, met, r, nrm = steel_graph(g, hexc("#7C8286"), 0.55, 0.5, rust=0.3)
    reg(g, g.principled(col, met, r, normal=nrm))
    g = SG("MAT_Steel_Green")                              # painted station columns (Enoden green)
    col, met, r, nrm = steel_graph(g, hexc("#2C5A3E"), 0.4, 0.5, rust=0.25)
    reg(g, g.principled(col, met, r, normal=nrm))
    g = SG("MAT_Manhole")
    ring = g.math("GREATER_THAN", g.math("PINGPONG", g.math("MULTIPLY", g.math("ADD", g.sep(g.n("ShaderNodeTexCoord").outputs["Object"])[0], g.sep(g.n("ShaderNodeTexCoord").outputs["Object"])[1]), 40.0), 1.0), 0.5)
    reg(g, g.principled("#2E2C2A", 0.65, 0.55, normal=g.bump(g.math("ADD", ring, g.noise(90.0, 3.0)), 0.5, 0.004)))
    g = SG("MAT_Vending_White")
    reg(g, g.principled("#E6E9EA", 0.05, 0.35, coat=0.3))
    log("  %d materials" % len(MAT))


# =====================================================================================================================
#  PLATEAU background base: terrain height-field, buildings, trees
# =====================================================================================================================
PL = None            # loaded PLATEAU/OSM json
HF = None            # height-field dict (list-of-rows of floats)


def load_plateau():
    global PL, HF
    if ARGS.no_plateau or not os.path.exists(ARGS.plateau):
        log("PLATEAU data not available (%s) -> procedural hillside only" % ("--no-plateau" if ARGS.no_plateau else ARGS.plateau))
        return
    PL = json.load(open(ARGS.plateau, encoding="utf-8"))
    h = PL["heightfield"]
    nx, ny = h["nx"], h["ny"]
    z = [float("nan") if v is None else v for v in h["z"]]
    rows = [z[j * nx:(j + 1) * nx] for j in range(ny)]
    for r in rows:                                     # fill gaps (sea / out of tile) with the nearest valid value in the row
        last = None
        for i in range(nx):
            if r[i] == r[i]:
                last = r[i]
            elif last is not None:
                r[i] = last
        last = None
        for i in range(nx - 1, -1, -1):
            if r[i] == r[i]:
                last = r[i]
            elif last is not None:
                r[i] = last
    good = [j for j in range(ny) if rows[j][0] == rows[j][0]]
    for j in range(ny):
        if rows[j][0] != rows[j][0] and good:
            k = min(good, key=lambda q: abs(q - j))
            rows[j] = list(rows[k])
    HF = {"x0": h["x0"], "y0": h["y0"], "dx": h["dx"], "nx": nx, "ny": ny, "rows": rows}
    m = PL["meta"]
    log("PLATEAU: %d buildings, height-field %dx%d, track bearing %.2f deg, Z0(TP)=%.2f m" %
        (len(PL["buildings"]), nx, ny, m["bearing_deg"], m["z0_tp"]))


def dem(x, y):
    if HF is None:
        return 0.09 * max(y - 4.0, 0.0) + 0.6 * math.sin(x * 0.02)
    fx = clamp((x - HF["x0"]) / HF["dx"], 0.0, HF["nx"] - 1.001)
    fy = clamp((y - HF["y0"]) / HF["dx"], 0.0, HF["ny"] - 1.001)
    i, j = int(fx), int(fy)
    tx, ty = fx - i, fy - j
    r0, r1 = HF["rows"][j], HF["rows"][j + 1]
    return (r0[i] * (1 - tx) + r0[i + 1] * tx) * (1 - ty) + (r1[i] * (1 - tx) + r1[i + 1] * tx) * ty


_PROF = [(-260.0, -8.6), (-140.0, -7.6), (-70.0, -6.6), (-45.0, -5.5), (-36.0, -4.5), (-31.0, -3.9), (-26.0, -2.85), (-19.5, -0.35),
         (-16.9, -0.35), (-6.0, -0.35), (-4.0, -0.45), (-2.6, -0.55), (2.6, -0.55), (4.4, -0.5)]


def prof(y):
    """Designed cross-section (independent of x): beach -> wall -> Route 134 -> track bed."""
    if y <= _PROF[0][0]:
        return _PROF[0][1]
    for (y0, z0), (y1, z1) in zip(_PROF, _PROF[1:]):
        if y <= y1:
            return lerp(z0, z1, (y - y0) / (y1 - y0))
    return _PROF[-1][1]


def terrain_z(x, y):
    if y <= 3.95:
        return prof(y)
    d = dem(x, y)
    t = smoothstep(4.4, 10.0, y)
    z = (-0.5 + 0.02 * (y - 4.4)) * (1 - t) + d * t
    fx = smoothstep(-62.0, -56.0, x) * (1 - smoothstep(-10.0, -4.0, x))          # path behind the platform
    return z + 1.5 * fx * (1 - smoothstep(4.0, 9.0, y))


def frange(a, b, step):
    n = max(1, int(round((b - a) / step)))
    return [a + (b - a) * i / n for i in range(n)]


def axis(segs, end):
    out = []
    for a, b, s in segs:
        out += frange(a, b, s)
    out.append(end)
    return sorted(set(round(v, 3) for v in out))


def hill_road_path():
    default = [(0.54, -11.23), (0.13, -4.98), (0.0, 0.0), (-0.27, 6.69), (-0.6, 16.88), (-6.99, 45.58), (-13.41, 68.77)]
    if PL:
        best = None
        for r in PL["osm"]["roads"]:
            if r["hw"] != "tertiary":
                continue
            d = min(math.hypot(x, y) for x, y in r["pts"])
            if d < 1.0 and (best is None or len(r["pts"]) > len(best)):
                best = [tuple(p) for p in r["pts"]]
        if best:
            best = sorted(best, key=lambda p: p[1])
            pts = [p for p in best if -12.0 <= p[1] <= 75.0]
            if len(pts) >= 4:
                return pts
    return default


def build_terrain():
    log("terrain ...")
    xs = axis([(-230, -150, 4.0), (-150, 150, 1.0), (150, 420, 4.0)], 420.0)
    ys = axis([(-150, -40, 5.0), (-40, -24, 2.0), (-24, -17.5, 0.5), (-17.5, -16.9, 0.6), (-16.9, -6.0, 1.1), (-6.0, 8.0, 0.5),
               (8.0, 40.0, 1.0), (40.0, 90.0, 2.0), (90.0, 230.0, 5.0)], 230.0)
    nx, ny = len(xs), len(ys)
    verts, wsand, wgrass, wsoil = [], [], [], []
    for y in ys:
        ws = smoothstep(-16.6, -18.0, y)
        wso = smoothstep(-16.0, -15.0, y) * (1 - smoothstep(3.0, 6.5, y))          # gravel only in the track corridor
        for x in xs:
            verts.append((x, y, terrain_z(x, y)))
            wsand.append(ws)
            wso_ = wso if y < 5.0 else wso * 0.9
            wsoil.append(wso_)
            wgrass.append(smoothstep(3.5, 10.0, y) * (1 - ws))
    faces = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i
            faces.append((a, a + 1, a + nx + 1, a + nx))
    me = bpy.data.meshes.new("Terrain")
    me.from_pydata(verts, [], faces)
    me.update()
    me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    for name, arr in (("w_sand", wsand), ("w_grass", wgrass), ("w_soil", wsoil)):
        a = me.attributes.new(name, "FLOAT", "POINT")
        a.data.foreach_set("value", arr)
    me.materials.append(MAT["MAT_Terrain"])
    ob = bpy.data.objects.new("Terrain_PLATEAU_DEM", me)
    coll("P1_Terrain").objects.link(ob)
    log("  terrain %d x %d verts" % (nx, ny))
    return ob


def densify(pts, step):
    out = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        for i in range(n):
            out.append((lerp(x0, x1, i / n), lerp(y0, y1, i / n)))
    out.append(tuple(pts[-1]))
    return out


HOUSES = []          # per house / apartment: footprint + eave data (filled by build_buildings, used by build_service_drops)
HEDGES = []          # (x, y, height) evergreen shrubs along the lot fronts (consumed by build_vegetation)
FOOTPRINTS = []      # (x0, x1, y0, y1, polygon) of every kept building (lanes / drops)
WEB_TREES = []       # (kind, x, y, z, half width, height, rotation) of every tree / shrub stamp (web viewer instances them)
WEB_LAMPS = []       # (x, y, z) of every street / pole lamp head (web viewer lights them at night)


def _poly_area(pts):
    a = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def _min_rect(pts):
    """Minimum-area bounding rectangle over the polygon's edge directions -> (centre, u, v, du, dv)."""
    best = None
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 0.3:
            continue
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        vx, vy = -uy, ux
        pu = [q[0] * ux + q[1] * uy for q in pts]
        pv = [q[0] * vx + q[1] * vy for q in pts]
        du, dv = max(pu) - min(pu), max(pv) - min(pv)
        if best is None or du * dv < best[0]:
            best = (du * dv, ux, uy, vx, vy, (max(pu) + min(pu)) / 2, (max(pv) + min(pv)) / 2, du, dv)
    if best is None:
        return None
    _, ux, uy, vx, vy, cu, cv, du, dv = best
    return (ux * cu + vx * cv, uy * cu + vy * cv), (ux, uy), (vx, vy), du, dv


def _pip(x, y, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _max_rect(mask):
    """Largest all-True axis-aligned rectangle of a boolean grid -> (area, i0, i1, j0, j1) with exclusive ends (histogram method)."""
    ny, nx = len(mask), len(mask[0])
    h = [0] * nx
    best = (0, 0, 0, 0, 0)
    for j in range(ny):
        for i in range(nx):
            h[i] = h[i] + 1 if mask[j][i] else 0
        st = []
        for i in range(nx + 1):
            cur = h[i] if i < nx else 0
            start = i
            while st and st[-1][1] >= cur:
                s, hh = st.pop()
                if hh * (i - s) > best[0]:
                    best = (hh * (i - s), s, i, j - hh + 1, j + 1)
                start = s
            st.append((start, cur))
    return best


def _decompose(foot, rect, cell=0.5, max_n=3):
    """L / T / U shaped plans -> up to three rectangles (largest first) in the frame of the minimum bounding rectangle:
    [(u0, u1, v0, v1), ...] relative to its centre, or None when the plan is not (nearly) a union of rectangles."""
    c_, u_, v_, du, dv = rect
    nx, ny = int(math.ceil(du / cell)), int(math.ceil(dv / cell))
    if nx < 2 or ny < 2 or nx * ny > 8000:
        return None
    loc = [((x - c_[0]) * u_[0] + (y - c_[1]) * u_[1], (x - c_[0]) * v_[0] + (y - c_[1]) * v_[1]) for x, y in foot]
    u0, v0 = -du / 2.0, -dv / 2.0
    mask = [[_pip(u0 + (i + 0.5) * cell, v0 + (j + 0.5) * cell, loc) for i in range(nx)] for j in range(ny)]
    total = sum(sum(1 for c in row if c) for row in mask)
    if total == 0:
        return None
    rects, covered = [], 0
    for k in range(max_n):
        area, i0, i1, j0, j1 = _max_rect(mask)
        if area * cell * cell < (6.0 if k else 24.0) or min(i1 - i0, j1 - j0) * cell < (1.8 if k else 2.5):
            break
        rects.append((u0 + i0 * cell - 0.2, u0 + i1 * cell + 0.2, v0 + j0 * cell - 0.2, v0 + j1 * cell + 0.2))
        covered += area
        for j in range(j0, j1):
            for i in range(i0, i1):
                mask[j][i] = False
    if not rects or covered / total < 0.80:
        return None
    return rects


def _wall_ang(ring):
    pts = [(ring[i], ring[i + 1]) for i in range(0, len(ring), 3)]
    best, ang = -1.0, 0.0
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            d = (pts[j][0] - pts[i][0]) ** 2 + (pts[j][1] - pts[i][1]) ** 2
            if d > best:
                best, ang = d, math.atan2(pts[j][1] - pts[i][1], pts[j][0] - pts[i][0])
    return ang


def _roof_gable(mb, Pr, r0, r1, c0, c1, top, rise, e0, e1, hip, o, attrs):
    """One pitched roof: ridge along r at the cross-middle, eaves at c0 / c1 (overhang o).  Pr(r, c, z) -> world point.
    e0 / e1 = 1: the end is buried in another roof (no overhang, no gable wall)."""
    cm, B = (c0 + c1) / 2.0, (c1 - c0) / 2.0
    sl = rise / B
    ze, zr = top - sl * o, top + rise
    cA, cB = cm - (B + o), cm + (B + o)
    half, rm = (r1 - r0) / 2.0, (r0 + r1) / 2.0
    if hip and not e0 and not e1 and half > B + 0.3:
        Rl, Ae = max(half - B, 0.3), half + o
        quads = [(Pr(rm - Ae, cA, ze), Pr(rm + Ae, cA, ze), Pr(rm + Rl, cm, zr), Pr(rm - Rl, cm, zr)),
                 (Pr(rm + Ae, cB, ze), Pr(rm - Ae, cB, ze), Pr(rm - Rl, cm, zr), Pr(rm + Rl, cm, zr))]
        for t in ((Pr(rm + Ae, cA, ze), Pr(rm + Ae, cB, ze), Pr(rm + Rl, cm, zr)), (Pr(rm - Ae, cB, ze), Pr(rm - Ae, cA, ze), Pr(rm - Rl, cm, zr))):
            bt = mb.verts(t)
            mb.face((bt, bt + 1, bt + 2), 1, False, **attrs)
    else:
        s0, s1 = r0 - (0.0 if e0 else 0.25), r1 + (0.0 if e1 else 0.25)
        quads = [(Pr(s0, cA, ze), Pr(s1, cA, ze), Pr(s1, cm, zr), Pr(s0, cm, zr)),
                 (Pr(s1, cB, ze), Pr(s0, cB, ze), Pr(s0, cm, zr), Pr(s1, cm, zr))]
        pa, pb = Pr(r0, c0, 0.0), Pr(r0, c1, 0.0)
        wg = math.atan2(pb[1] - pa[1], pb[0] - pa[0])
        for r_, e_ in ((r0, e0), (r1, e1)):
            if not e_:                                                # gable end wall
                bt = mb.verts([Pr(r_, c0, top), Pr(r_, c1, top), Pr(r_, cm, zr)])
                mb.face((bt, bt + 1, bt + 2), 0, False, **dict(attrs, wang=wg, wsd=0.9))
    for q in quads:
        bq = mb.verts(q)
        mb.face((bq, bq + 1, bq + 2, bq + 3), 1, False, **attrs)
    return ze, zr


def _gutters(dm, fc, Pr, r0, r1, c0, c1, ze, o, attrs, rng):
    """Eave gutters on the long sides of one roof where the wall is exposed, each with a downpipe reaching the ground."""
    pa, pb = Pr(0.0, 0.0, 0.0), Pr(1.0, 0.0, 0.0)
    ang = math.atan2(pb[1] - pa[1], pb[0] - pa[0])
    ln = r1 - r0
    for cw, sgn in ((c0, -1.0), (c1, 1.0)):
        k = max(2, int(ln))
        good = 0
        for i in range(k + 1):
            r = r0 + ln * i / k
            xo, yo, _ = Pr(r, cw + sgn * 0.45, 0.0)
            xi, yi, _ = Pr(r, cw - sgn * 0.45, 0.0)
            if (not _pip(xo, yo, fc)) and _pip(xi, yi, fc):
                good += 1
        if good < 0.75 * (k + 1):
            continue
        ce = cw + sgn * o
        gx, gy, _ = Pr((r0 + r1) / 2.0, ce + sgn * 0.03, 0.0)
        dm.box((gx, gy, ze - 0.07), (ln + 0.3, 0.11, 0.09), 0, (0.0, 0.0, ang), False, **attrs)
        for rp in ((r0 + 0.4, r1 - 0.4) if rng.random() < 0.5 else (r1 - 0.4, r0 + 0.4)):
            xo, yo, _ = Pr(rp, cw + sgn * 0.3, 0.0)
            xi, yi, _ = Pr(rp, cw - sgn * 0.3, 0.0)
            if _pip(xo, yo, fc) or not _pip(xi, yi, fc):
                continue
            px_, py_, _ = Pr(rp, cw + sgn * 0.05, 0.0)
            ox_, oy_, _ = Pr(rp, ce + sgn * 0.03, 0.0)
            dm.cyl((ox_, oy_, ze - 0.10), (px_, py_, ze - 0.24), 0.026, 0.026, 6, 0, False, False, **attrs)
            dm.cyl((px_, py_, ze - 0.24), (px_, py_, terrain_z(px_, py_) + 0.05), 0.028, 0.028, 6, 0, False, False, **attrs)
            break


def _road_index(road_pts):
    """Grid of drivable-road samples (x, y, half width) used to orient entrances and lot fronts."""
    cell = 12.0
    grid = {}
    for sx, sy in densify(road_pts, 2.5):
        grid.setdefault((int(sx // cell), int(sy // cell)), []).append((sx, sy, road_width(sy) / 2.0))
    if PL:
        for r in PL["osm"]["roads"]:
            hw = {"residential": 2.4, "service": 1.7, "unclassified": 2.6, "tertiary": 2.6}.get(r["hw"])
            if hw is None or len(r["pts"]) < 2:
                continue
            for sx, sy in densify([tuple(p) for p in r["pts"]], 2.5):
                if sy > 3.0:
                    grid.setdefault((int(sx // cell), int(sy // cell)), []).append((sx, sy, hw))

    def nearest(x, y):
        best = None
        gx, gy = int(x // cell), int(y // cell)
        for ax in range(-3, 4):
            for ay in range(-3, 4):
                for sx, sy, hw in grid.get((gx + ax, gy + ay), ()):
                    d = (sx - x) ** 2 + (sy - y) ** 2
                    if best is None or d < best[0]:
                        best = (d, sx, sy, hw)
        return None if best is None else (math.sqrt(best[0]), best[1], best[2], best[3])

    return nearest


def _ept(e, t, off=0.0):
    return (e["a"][0] + e["d"][0] * t + e["n"][0] * off, e["a"][1] + e["d"][1] * t + e["n"][1] * off)


def _spans(lo, hi, gaps, step=1.8):
    segs = [(lo, hi)]
    for g0, g1 in gaps:
        nxt = []
        for s0, s1 in segs:
            if g1 <= s0 or g0 >= s1:
                nxt.append((s0, s1))
            else:
                if g0 > s0:
                    nxt.append((s0, g0))
                if g1 < s1:
                    nxt.append((g1, s1))
        segs = nxt
    out = []
    for s0, s1 in segs:
        if s1 - s0 < 0.2:
            continue
        k = max(1, int(math.ceil((s1 - s0) / step)))
        out += [(s0 + (s1 - s0) * i / k, s0 + (s1 - s0) * (i + 1) / k) for i in range(k)]
    return out


def _slab4(dm, pts, zt, zb, mat, **attrs):
    b = dm.verts([(p[0], p[1], z) for p, z in zip(pts, zt)] + [(p[0], p[1], z) for p, z in zip(pts, zb)])
    dm.face((b + 3, b + 2, b + 1, b), mat, False, **attrs)
    for i in range(4):
        j = (i + 1) % 4
        dm.face((b + i, b + j, b + 4 + j, b + 4 + i), mat, False, **attrs)


def _paved(dm, e, t0, t1, o0, o1, dz, mat, attrs, step=1.0):
    """Concrete slab on the ground in the wall frame (t along the wall, o outward); the top follows the terrain in ~1 m cells."""
    no = max(1, int(math.ceil((o1 - o0) / step)))
    nt = max(1, int(math.ceil((t1 - t0) / step)))
    for i in range(nt):
        ta, tb = t0 + (t1 - t0) * i / nt, t0 + (t1 - t0) * (i + 1) / nt
        for k in range(no):
            oa, ob = o0 + (o1 - o0) * k / no, o0 + (o1 - o0) * (k + 1) / no
            pts = [_ept(e, ta, oa), _ept(e, tb, oa), _ept(e, tb, ob), _ept(e, ta, ob)]
            top = [terrain_z(x, y) + dz + 0.05 for x, y in pts]
            _slab4(dm, pts, top, [z - 0.35 for z in top], mat, **attrs)


def _wall_run(dm, e, a_, b_, q, thick, dzb, dzt, mat, attrs):
    """Wall panel from t=a_ to b_ at offset q whose top / bottom follow the terrain (dzt / dzb relative to it), so it steps down slopes smoothly."""
    ta_ = [_ept(e, a_, q - thick / 2.0), _ept(e, a_, q + thick / 2.0)]
    tb_ = [_ept(e, b_, q - thick / 2.0), _ept(e, b_, q + thick / 2.0)]
    za, zb = terrain_z(*_ept(e, a_, q)), terrain_z(*_ept(e, b_, q))
    v = dm.verts([(p[0], p[1], za + dzt) for p in ta_] + [(p[0], p[1], zb + dzt) for p in tb_] +
                 [(p[0], p[1], za + dzb) for p in ta_] + [(p[0], p[1], zb + dzb) for p in tb_])
    # 0,1: A top (front, back)   2,3: B top   4,5: A bottom   6,7: B bottom
    for f in ((0, 2, 3, 1), (0, 4, 6, 2), (1, 3, 7, 5), (0, 1, 5, 4), (2, 6, 7, 3)):
        dm.face([v + i for i in f], mat, False, **attrs)


def _fence_s(dm, e, a_, b_, off, dzbase, h, kw):
    """Aluminium fence on top of a wall panel: rails + bars, following the terrain slope between the panel ends."""
    xa, ya = _ept(e, a_, off)
    xb, yb = _ept(e, b_, off)
    za, zb = terrain_z(xa, ya) + dzbase, terrain_z(xb, yb) + dzbase
    dm.cyl((xa, ya, za + h - 0.02), (xb, yb, zb + h - 0.02), 0.018, 0.018, 5, 11, False, False, **kw)
    dm.cyl((xa, ya, za + 0.06), (xb, yb, zb + 0.06), 0.018, 0.018, 5, 11, False, False, **kw)
    nb = max(1, int((b_ - a_) / 0.13))
    for k in range(nb + 1):
        f = k / nb
        dm.box((xa + (xb - xa) * f, ya + (yb - ya) * f, za + (zb - za) * f + h / 2.0), (0.016, 0.016, h - 0.06), 11, None, False, **kw)


def _house_details(dm, hs, rng, near_road, others):
    """Entrance + porch canopy + steps, garage / carport + driveway, AC outdoor units, balcony, boundary wall / retaining wall / fence /
    hedge, parking pad and bin store for one house or apartment block.  Refs: Street View sv_h01 / sv_h02 (hillside houses)."""
    top, zmin, kind, fl, fh = hs["top"], hs["zmin"], hs["kind"], hs["fl"], hs["fh"]
    A = hs["attrs"]
    edges = hs["edges"]
    if not edges:
        return

    def at(**kw):
        return dict(A, **kw)

    def free(x, y):
        for (bx0, bx1, by0, by1, poly) in others:
            if bx0 - 0.3 < x < bx1 + 0.3 and by0 - 0.3 < y < by1 + 0.3 and _pip(x, y, poly):
                return False
        r = near_road(x, y)
        return not (r is not None and r[0] < r[3] + 0.15)

    # ---- which wall faces the street
    fac, best, gap = None, -1.0, 0.0
    for ed in edges:
        if ed["L"] < 2.4:
            continue
        mx, my = _ept(ed, ed["L"] / 2.0)
        r = near_road(mx, my)
        if r is None:
            continue
        vx, vy = r[1] - mx, r[2] - my
        vl = math.hypot(vx, vy) + 1e-9
        dot = (ed["n"][0] * vx + ed["n"][1] * vy) / vl
        if dot >= 0.5 and ed["L"] * dot > best:
            best, fac, gap = ed["L"] * dot, ed, max(r[0] * dot - r[3], 0.0)
    e = fac if fac is not None else max(edges, key=lambda ed: ed["L"])
    L, ang = e["L"], e["ang"]
    R = (0.0, 0.0, ang)
    q = clamp(gap - 0.15, 0.0, 9.0) if fac is not None else 0.0
    has_lot = q >= 1.0

    def E3(t, off, z):
        x_, y_ = _ept(e, t, off)
        return (x_, y_, z)

    def fence(t0, t1, off, zbase, h, kw):
        ln = t1 - t0
        pm = _ept(e, (t0 + t1) / 2.0, off)
        dm.box((pm[0], pm[1], zbase + h - 0.02), (ln, 0.035, 0.035), 11, R, False, **kw)
        dm.box((pm[0], pm[1], zbase + 0.06), (ln, 0.035, 0.035), 11, R, False, **kw)
        nb = max(1, int(ln / 0.13))
        for k in range(nb + 1):
            x_, y_ = _ept(e, t0 + ln * k / nb, off)
            dm.box((x_, y_, zbase + h / 2.0), (0.016, 0.016, h - 0.06), 11, None, False, **kw)

    # ---- plan: boundary type, door / garage positions
    Zp = zmin + 0.05
    zc0 = terrain_z(*_ept(e, L / 2.0, q if has_lot else 1.0))
    drop = Zp - zc0
    r_ = rng.random()
    if not has_lot or kind == 2:
        btype = "open"
    elif kind == 0 and 0.55 < drop < 3.6 and r_ < 0.8:
        btype = "retain"
    elif kind == 0:
        btype = "block" if r_ < 0.36 else ("plaster" if r_ < 0.52 else ("hedge" if r_ < 0.74 else "open"))
    else:
        btype = "block" if r_ < 0.4 else ("hedge" if r_ < 0.7 else "open")
    garage = (kind == 0 and btype != "retain" and L >= 6.0 and rng.random() < 0.6 and
              abs(terrain_z(*_ept(e, L / 2.0, 0.5)) - terrain_z(*_ept(e, L / 2.0, 4.0))) < 0.8)          # driveway grade < ~23 %
    door_w = 1.7 if kind == 1 else 0.92
    if garage:
        near_start = rng.random() < 0.5
        tg, td = (1.75, L - 1.35) if near_start else (L - 1.75, 1.35)
    else:
        tg = None
        td = clamp(L * rng.uniform(0.3, 0.7), door_w / 2.0 + 0.4, L - door_w / 2.0 - 0.4)
    e["used"].append((td - door_w / 2.0 - 0.3, td + door_w / 2.0 + 0.3))
    if garage:
        e["used"].append((tg - 1.6, tg + 1.6))

    # ---- entrance: door, frame, canopy, light, landing + steps
    gz = terrain_z(*_ept(e, td, 1.1))
    if btype == "retain":
        gz = max(gz, Zp)
    fz = clamp(zmin + 0.30, gz + 0.12, gz + 2.6)
    dmat = 7 if kind == 1 else 1
    dm.box(E3(td, 0.02, fz + 1.04), (door_w + 0.12, 0.05, 2.08), 6, R, False, **at(wang=ang))
    dm.box(E3(td, 0.045, fz + 1.0), (door_w, 0.05, 2.0), dmat, R, False, **at(wang=ang))
    if kind == 0:
        dm.box(E3(td + door_w / 2.0 - 0.12, 0.085, fz + 1.0), (0.03, 0.04, 0.24), 6, R, False, **at())
        dm.box(E3(td - door_w / 2.0 - 0.32, 0.05, fz + 2.05), (0.12, 0.07, 0.14), 8, R, False, **at())          # porch light
    if rng.random() < 0.75:
        cw_ = door_w + (1.3 if kind == 1 else 0.9)
        dm.box(E3(td, 0.55, fz + 2.40), (cw_, 1.05, 0.09), 0, R, False, **at())
        if kind == 1 or rng.random() < 0.4:
            for sgn in (-1, 1):
                x_, y_ = _ept(e, td + sgn * (cw_ / 2.0 - 0.06), 1.0)
                dm.cyl((x_, y_, fz - 0.02), (x_, y_, fz + 2.36), 0.04, 0.04, 8, 6, True, False, **at())
    dm.box(E3(td, 0.45, (gz - 0.3 + fz - 0.03) / 2.0), (door_w + 0.7, 0.9, fz - 0.03 - (gz - 0.3)), 5, R, False, **at(wang=ang))
    n_st = int(math.ceil((fz - gz) / 0.19)) if fz - gz > 0.10 else 0
    if n_st > 1:
        rise = (fz - gz) / n_st
        for k in range(1, n_st):
            zt_ = fz - k * rise
            dm.box(E3(td, 0.9 + (k - 0.5) * 0.29, (gz - 0.3 + zt_) / 2.0), (door_w + 0.7, 0.29, zt_ - (gz - 0.3)), 5, R, False, **at(wang=ang))
    off_path = 0.9 + 0.29 * max(n_st - 1, 0)

    # ---- garage / carport + driveway
    gaps = []
    if garage:
        gw = 2.7
        gzg = terrain_z(*_ept(e, tg, 2.0))
        gfz = max(clamp(gzg + 0.03, fz - 3.0, fz - 0.02), terrain_z(*_ept(e, tg, 0.0)) - 0.3)
        gh = 2.15
        kg = rng.random()
        if kg < 0.72:
            dm.box(E3(tg, 0.04, gfz + (gh + 0.2) / 2.0), (gw + 0.3, 0.10, gh + 0.2), 5, R, False, **at(wang=ang))
            if kg < 0.42:
                dm.box(E3(tg, 0.10, gfz + gh / 2.0), (gw, 0.08, gh), 2, R, False, **at())               # roller shutter
            else:
                dm.box(E3(tg, 0.09, gfz + gh / 2.0), (gw, 0.12, gh), 4, R, False, **at())               # open bay (dark inside)
        else:
            dep = min(4.8, max(2.6, (q if has_lot else 5.0) - 0.4))
            zr_ = gfz + 2.45
            dm.box(E3(tg, dep / 2.0 - 0.05, zr_), (gw + 0.5, dep, 0.06), 7, R, False, **at())        # polycarbonate roof
            for sgn in (-1, 1):
                t_ = tg + sgn * (gw / 2.0 + 0.2)
                dm.box(E3(t_, dep / 2.0 - 0.05, zr_ - 0.06), (0.05, dep, 0.08), 6, R, False, **at())
                x_, y_ = _ept(e, t_, dep - 0.1)
                dm.cyl((x_, y_, terrain_z(x_, y_) - 0.1), (x_, y_, zr_ - 0.03), 0.045, 0.045, 8, 6, True, False, **at())
        _paved(dm, e, tg - gw / 2.0 - 0.1, tg + gw / 2.0 + 0.1, 0.0, max(q, 3.5), 0.03, 5, at(wang=ang))
        gaps.append((tg - 1.7, tg + 1.7))

    # ---- balcony over the entrance / garage (houses with an upper floor)
    if kind == 0 and fl >= 2 and L >= 4.2 and rng.random() < 0.6:
        tb = tg if garage else max((L * 0.3, L * 0.7), key=lambda t: abs(t - td))
        bw = min(L - 0.9, rng.uniform(2.4, 3.6))
        zf_ = zmin + 0.4 + fh
        if zf_ + 1.1 < top - 0.3:
            t0_, t1_ = tb - bw / 2.0, tb + bw / 2.0
            dm.box(E3(tb, 0.52, zf_ - 0.065), (bw, 1.04, 0.13), 14, R, False, **at())
            if rng.random() < 0.55:
                dm.box(E3(tb, 1.0, zf_ + 0.475), (bw, 0.05, 0.95), 14, R, False, **at())
                for sgn in (-1, 1):
                    dm.box(E3(tb + sgn * bw / 2.0, 0.52, zf_ + 0.475), (0.05, 1.0, 0.95), 14, R, False, **at())
                dm.box(E3(tb, 1.0, zf_ + 0.97), (bw + 0.06, 0.09, 0.04), 11, R, False, **at())
            else:
                fence(t0_, t1_, 1.0, zf_, 1.0, at())
            dm.cyl(E3(t0_ - 0.1, 0.6, zf_ + 1.55), E3(t1_ + 0.1, 0.6, zf_ + 1.55), 0.014, 0.014, 5, 6, False, False, **at())    # laundry pole

    # ---- AC outdoor units on the ground beside the walls
    n_ac = rng.choice((1, 1, 2)) if kind == 0 else 0
    for _ in range(n_ac):
        for _try in range(6):
            ed = rng.choice(edges)
            if ed["L"] < 2.2:
                continue
            t = rng.uniform(0.8, ed["L"] - 0.8)
            if any(a_ - 0.5 < t < b_ + 0.5 for a_, b_ in ed["used"]):
                continue
            cx, cy = _ept(ed, t, 0.24)
            if not (free(cx, cy) and free(*_ept(ed, t, 0.7))):
                continue
            ed["used"].append((t - 0.6, t + 0.6))
            zg_ = terrain_z(cx, cy)
            Rz = (0.0, 0.0, ed["ang"])
            dm.box((cx, cy, zg_ + 0.36), (0.80, 0.30, 0.62), 3, Rz, False, **at())
            dm.box((cx, cy, zg_ + 0.03), (0.72, 0.22, 0.06), 6, Rz, False, **at())
            gx_, gy_ = _ept(ed, t - 0.12, 0.24 + 0.148)
            gp_ = _ept(ed, t - 0.12, 0.24 + 0.162)
            dm.cyl((gx_, gy_, zg_ + 0.36), (gp_[0], gp_[1], zg_ + 0.36), 0.22, 0.22, 14, 4, True, False, **at())          # fan grille
            px_, py_ = _ept(ed, t + 0.32, 0.05)
            dm.cyl((px_, py_, zg_ + 0.6), (px_, py_, zg_ + rng.uniform(2.4, 5.2)), 0.02, 0.02, 5, 3, False, False, **at())  # refrigerant pipe
            break

    # ---- flat roofs / apartments: downpipes on the long walls
    if hs["flat"]:
        for ed in sorted(edges, key=lambda x_: -x_["L"])[:2 if kind == 1 else 1]:
            if ed["L"] < 3.0:
                continue
            t = ed["L"] * (0.12 if rng.random() < 0.5 else 0.88)
            if any(a_ - 0.2 < t < b_ + 0.2 for a_, b_ in ed["used"]):
                continue
            px_, py_ = _ept(ed, t, 0.05)
            dm.cyl((px_, py_, top - 0.1), (px_, py_, terrain_z(px_, py_) + 0.05), 0.032, 0.032, 6, 0, False, False, **at())

    # ---- lot front: boundary wall / retaining wall / fence / hedge, gate pillar, paths, parking, bin store
    if not has_lot:
        return
    lo, hi = -0.7, L + 0.7
    if btype in ("block", "plaster", "hedge"):
        gaps.append((td - 0.7, td + 0.7))
    if kind == 0 and not garage and btype != "retain" and L >= 5.2 and rng.random() < 0.4 and q >= 3.6:
        tp = clamp(L - td if abs(L - td) > L * 0.5 else L * 0.75, 1.6, L - 1.6)
        if abs(tp - td) > 2.6:
            _paved(dm, e, tp - 1.3, tp + 1.3, 0.4, min(q - 0.2, 5.5), 0.03, 5, at(wang=ang))
            gaps.append((tp - 1.7, tp + 1.7))
    if kind == 1 and q >= 4.2:
        if td < L / 2.0:
            t0_, t1_ = td + 1.6, min(L - 0.3, td + 11.6)
        else:
            t1_, t0_ = td - 1.6, max(0.3, td - 11.6)
        if t1_ - t0_ >= 4.9:
            oe = min(q - 0.3, 5.5)
            _paved(dm, e, t0_, t1_, 0.5, oe, 0.03, 5, at(wang=ang))
            for i in range(int((t1_ - t0_) / 2.5) + 1):
                tt = t0_ + i * 2.5
                x_, y_ = _ept(e, tt, (0.5 + oe) / 2.0)
                dm.box((x_, y_, terrain_z(x_, y_) + 0.045), (0.10, oe - 0.5, 0.012), 8, R, False, **at())
            gaps.append((t0_ - 0.2, t1_ + 0.2))
    if off_path + 0.3 < q and btype in ("block", "plaster", "hedge") and not garage:
        _paved(dm, e, td - 0.5, td + 0.5, off_path, q, 0.03, 5, at(wang=ang))

    if btype in ("block", "plaster"):
        Hh = rng.uniform(0.85, 1.25) if btype == "block" else rng.uniform(1.5, 1.85)
        mat = 9 if btype == "block" else 10
        fh_ = rng.uniform(0.55, 0.75) if btype == "block" and rng.random() < 0.6 else 0.0
        for (a_, b_) in _spans(lo, hi, gaps, 1.8):
            pa, pb, pm = _ept(e, a_, q), _ept(e, b_, q), _ept(e, (a_ + b_) / 2.0, q)
            if not (free(*pa) and free(*pb) and free(*pm)):
                continue
            if abs(terrain_z(*pa) - terrain_z(*pb)) > 0.8:                  # too steep for a free-standing wall
                continue
            _wall_run(dm, e, a_, b_, q, 0.16, -0.35, Hh, mat, at(wang=ang))
            _wall_run(dm, e, a_ - 0.01, b_ + 0.01, q, 0.21, Hh, Hh + 0.04, 5, at())
            if fh_ > 0.0:
                _fence_s(dm, e, a_, b_, q, Hh + 0.04, fh_, at())
        for t in (td - 0.85, td + 0.85):                                     # gate pillars with mail box
            x_, y_ = _ept(e, t, q)
            if not free(x_, y_):
                continue
            zg_ = terrain_z(x_, y_)
            dm.box((x_, y_, zg_ + 0.575), (0.34, 0.34, 1.75), 10, R, False, **at(wang=ang))
            dm.box((x_, y_, zg_ + 1.475), (0.42, 0.42, 0.05), 5, R, False, **at())
            if t < td:
                mx_, my_ = _ept(e, t, q + 0.21)
                dm.box((mx_, my_, zg_ + 1.05), (0.26, 0.10, 0.30), 6, R, False, **at())
    elif btype == "retain":
        stone = rng.random() < 0.45
        top_z = Zp
        for (a_, b_) in _spans(lo, hi, gaps, 2.0):
            pa, pb, pm = _ept(e, a_, q), _ept(e, b_, q), _ept(e, (a_ + b_) / 2.0, q)
            if not (free(*pa) and free(*pb) and free(*pm)):
                continue
            zb_ = min(terrain_z(*pa), terrain_z(*pb), terrain_z(*pm)) - 0.35
            zt_ = max(top_z, terrain_z(*pm) + 0.5)
            dm.box((pm[0], pm[1], (zt_ + zb_) / 2.0), (b_ - a_ + 0.01, 0.42, zt_ - zb_), 13 if stone else 5, R, False, **at(wang=ang))
            dm.box((pm[0], pm[1], zt_ + 0.03), (b_ - a_ + 0.02, 0.46, 0.06), 5, R, False, **at())
            if rng.random() < 0.8:
                fence(a_, b_, q, zt_ + 0.06, 0.95, at())
            pts = [_ept(e, a_, 0.0), _ept(e, b_, 0.0), _ept(e, b_, q - 0.2), _ept(e, a_, q - 0.2)]
            _slab4(dm, pts, [zt_ - 0.02] * 4, [zt_ - 0.6] * 4, 5, **at(wang=ang))                 # filled terrace behind the wall
    elif btype == "hedge":
        x_ = lo
        while x_ < hi:
            if not any(g0 - 0.3 < x_ < g1 + 0.3 for g0, g1 in gaps):
                hx, hy = _ept(e, x_, q + 0.35)
                if free(hx, hy):
                    HEDGES.append((hx, hy, rng.uniform(1.25, 2.0)))
            x_ += 0.8

    if rng.random() < (0.28 if kind == 1 else 0.12):                          # grey mesh bin store
        for off_t in (-0.2, L + 0.2):
            bx, by = _ept(e, off_t, min(q - 0.6, 1.4))
            if free(bx, by) and free(*_ept(e, off_t, min(q - 0.6, 1.4) + 0.7)):
                zg_ = terrain_z(bx, by)
                dm.box((bx, by, zg_ + 0.45), (1.4, 0.7, 0.9), 12, R, False, **at(wang=ang))
                dm.box((bx, by, zg_ + 0.92), (1.44, 0.74, 0.05), 6, R, False, **at())
                break


def build_buildings(road_pts):
    """PLATEAU footprints/heights (LOD1; LOD2 kept as is) -> houses with gable/hip tile roofs (L / T / U plans get several intersecting
    gables), apartments with parapets, rooftop equipment and balconies, other buildings with flat roofs.  Kind comes from the PLATEAU
    usage / structure / storey attributes.  Wall details (entrance, garage, gutters, AC units), lot fronts (walls, hedges, parking) and the
    service-drop data come on top of that (Street View sv_h01 / sv_h02)."""
    if not PL:
        return []
    log("buildings (PLATEAU: houses / apartments / other) ...")
    HOUSES.clear()
    HEDGES.clear()
    samples = densify(road_pts, 2.0)
    rng = random.Random(9)
    rng_d = random.Random(13)
    near_road = _road_index(road_pts)
    mb = MB()                                       # 0 wall, 1 roof, 2 balcony slab, 3 rail glass
    dm = MB()                                       # detail meshes (see the material list at the bottom)
    boxes = []
    todo, others = [], []
    kept = dropped = 0
    stat = {"house_pitched": 0, "house_complex": 0, "house_flat": 0, "apartment": 0, "other": 0}
    for b in PL["buildings"]:
        polys = b["polys"]
        xs = [v for _, r in polys for v in r[0::3]]
        ys = [v for _, r in polys for v in r[1::3]]
        zs = [v for _, r in polys for v in r[2::3]]
        x0, x1, y0, y1, zmin = min(xs), max(xs), min(ys), max(ys), min(zs)
        if y0 < 6.5 and x1 > -230:                                    # railway / road / sea-wall corridor -> spec geometry wins
            dropped += 1
            continue
        if any(x0 - 4.5 < sx < x1 + 4.5 and y0 - 4.5 < sy < y1 + 4.5 for sx, sy in samples):   # hill road
            dropped += 1
            continue
        brand = (zlib.crc32(b["id"].encode()) % 1000) / 1000.0
        roofs = [r for k, r in polys if k == "r"]
        lod2 = b.get("lod", 1) == 2
        top = max([v for r in roofs for v in r[2::3]] or [max(zs)])
        big = max(roofs, key=lambda r: _poly_area([(r[i], r[i + 1]) for i in range(0, len(r), 3)])) if roofs else None
        foot = [(big[i], big[i + 1]) for i in range(0, len(big), 3)] if big else []
        area = _poly_area(foot) if len(foot) >= 3 else 0.0
        use, st = b.get("use", ""), b.get("struct", "")
        hgt = top - zmin
        fl = b.get("fl", 0)
        if not (1 <= fl <= 12):
            fl = max(1, int(round(hgt / 3.0)))
        fh = clamp(hgt / max(fl, 1), 2.5, 3.6)
        if use in ("412", "414") or (fl >= 3 and area > 90.0) or (hgt >= 10.0 and area > 120.0):
            kind = 1                                                   # apartment / condo
        elif use in ("421", "422", "401", "402", "404", "431", "441", "452", "454") or area > 450.0:
            kind = 2
        else:
            kind = 0                                                   # house (incl. unknown small buildings)
        rect, parts, pitched = None, None, False
        if not lod2 and len(foot) >= 3 and kind == 0:
            rect = _min_rect(foot)
            if rect is not None:
                fill = area / max(rect[3] * rect[4], 1e-6)
                ok_use = st == "601" or use in ("411", "413", "415", "461") or rng.random() < 0.5
                if fill > 0.78 and min(rect[3], rect[4]) > 3.0 and ok_use:
                    pitched = True
                    parts = [(-rect[3] / 2.0, rect[3] / 2.0, -rect[4] / 2.0, rect[4] / 2.0)]
                elif area > 30.0 and ok_use:                           # L / T / U shaped plan -> several intersecting gables
                    parts = _decompose(foot, rect)
                    pitched = parts is not None
        flat = 0.0 if pitched else 1.0
        attrs = dict(brand=brand, bfloor=fh, bkind=float(kind), rflat=flat)
        fc = foot if _signed_area(foot) >= 0 else list(reversed(foot))

        for wi, (k_, ring) in enumerate(polys):                        # extruded walls (+ LOD1 flat tops when not pitched)
            if k_ == "g" or (k_ == "r" and pitched and not lod2 and len(parts) == 1):
                continue
            pts = []
            for i in range(0, len(ring), 3):                          # foundations: walls reach down to the local terrain
                px_, py_, pz_ = ring[i], ring[i + 1], ring[i + 2]
                if pz_ <= zmin + 0.06:
                    pz_ = min(pz_, terrain_z(px_, py_) - 0.4)
                pts.append((px_, py_, pz_))
            base = mb.verts(pts)
            wa = dict(attrs)
            uv_ = None
            if k_ == "w":
                wa.update(wang=_wall_ang(ring), wsd=(zlib.crc32((b["id"] + str(wi)).encode()) % 1000) / 1000.0, bz0=zmin)
                ca_, sa_ = math.cos(wa["wang"]), math.sin(wa["wang"])
                uv_ = [((q[0] - pts[0][0]) * ca_ + (q[1] - pts[0][1]) * sa_, q[2] - zmin) for q in pts]
            mb.face(range(base, base + len(pts)), 0 if k_ == "w" else 1, False, uv=uv_, **wa)

        if pitched:
            c_, u_, v_, du, dv = rect
            wattrs = dict(attrs, bz0=zmin)

            def P_uv(u, v, z):
                return (c_[0] + u_[0] * u + v_[0] * v, c_[1] + u_[1] * u + v_[1] * v, z)

            prim = parts[0]
            rise1 = 0.0
            for pi_, (a0, a1, b0, b1) in enumerate(parts):
                along_u = (a1 - a0) >= (b1 - b0)
                if along_u:
                    r0, r1, cc0, cc1 = a0, a1, b0, b1
                    Pr = P_uv
                else:
                    r0, r1, cc0, cc1 = b0, b1, a0, a1

                    def Pr(r, c, z):
                        return P_uv(c, r, z)
                B = (cc1 - cc0) / 2.0
                if pi_ == 0:
                    rise = min(0.36 * B, 3.0)
                    rise1 = rise
                else:
                    rise = max(0.4, min(0.36 * B, rise1 - 0.15))
                g0, g1 = r0, r1                                        # wall-to-wall range (for the gutters)
                e0 = e1 = 0
                if pi_ > 0:
                    pa0, pa1, pb0, pb1 = prim
                    p_along_u = (pa1 - pa0) >= (pb1 - pb0)
                    for end in (0, 1):
                        rr = r0 - 0.3 if end == 0 else r1 + 0.3
                        uu, vv = (rr, (cc0 + cc1) / 2.0) if along_u else ((cc0 + cc1) / 2.0, rr)
                        if pa0 - 0.05 <= uu <= pa1 + 0.05 and pb0 - 0.05 <= vv <= pb1 + 0.05:
                            if p_along_u != along_u:                    # the primary ridge runs across ours: run into it
                                mid = (pa0 + pa1) / 2.0 if along_u else (pb0 + pb1) / 2.0
                                if end == 0 and mid < r1 - 0.5:
                                    r0 = mid
                                elif end == 1 and mid > r0 + 0.5:
                                    r1 = mid
                            if end == 0:
                                e0 = 1
                            else:
                                e1 = 1
                hip = pi_ == 0 and len(parts) == 1 and rng.random() < 0.4 and (r1 - r0) / 2.0 > B + 0.3
                ze, zr = _roof_gable(mb, Pr, r0, r1, cc0, cc1, top, rise, e0, e1, hip, 0.35, wattrs)
                _gutters(dm, fc, Pr, g0, g1, cc0, cc1, ze, 0.35, attrs, rng_d)
            stat["house_pitched" if len(parts) == 1 else "house_complex"] += 1
        elif not lod2 and len(foot) >= 3:
            n_ = len(foot)
            for i in range(n_):                                       # parapet (0.18 m thick, 0.5 m high) around the flat roof
                (ax_, ay_), (bx_, by_) = foot[i], foot[(i + 1) % n_]
                L = math.hypot(bx_ - ax_, by_ - ay_)
                if L > 0.4:
                    mb.box(((ax_ + bx_) / 2, (ay_ + by_) / 2, top + 0.25), (L, 0.18, 0.5), 0, (0, 0, math.atan2(by_ - ay_, bx_ - ax_)), False, **attrs)
            if area > 60.0:                                           # rooftop equipment / stair head
                cx_, cy_ = sum(q[0] for q in foot) / n_, sum(q[1] for q in foot) / n_
                mb.box((cx_, cy_, top + 0.6), (min(2.6, area ** 0.5 * 0.3), min(1.7, area ** 0.5 * 0.2), 1.2), 0, (0, 0, rng.uniform(0, 3.14)), False, **attrs)
            stat["house_flat" if kind == 0 else ("apartment" if kind == 1 else "other")] += 1
            if kind == 1 and fl >= 3:                                 # balconies on the wide facades, one slab + glass rail per upper floor
                cen = (sum(q[0] for q in foot) / n_, sum(q[1] for q in foot) / n_)
                for k_, ring in polys:
                    if k_ != "w" or len(ring) != 12:
                        continue
                    vs = [(ring[i], ring[i + 1], ring[i + 2]) for i in range(0, 12, 3)]
                    lo = sorted(vs, key=lambda q: q[2])[:2]
                    dx_, dy_ = lo[1][0] - lo[0][0], lo[1][1] - lo[0][1]
                    L = math.hypot(dx_, dy_)
                    if L < 4.0:
                        continue
                    ux_, uy_ = dx_ / L, dy_ / L
                    nx_, ny_ = uy_, -ux_
                    mx_, my_ = (lo[0][0] + lo[1][0]) / 2, (lo[0][1] + lo[1][1]) / 2
                    if (mx_ - cen[0]) * nx_ + (my_ - cen[1]) * ny_ < 0:
                        nx_, ny_ = -nx_, -ny_
                    zb0 = min(q[2] for q in lo) + 0.4
                    ang = math.atan2(uy_, ux_)
                    for fk in range(1, fl):
                        zf_ = zb0 + fk * fh
                        if zf_ > top - 0.5:
                            break
                        cxb, cyb = mx_ + nx_ * 0.6, my_ + ny_ * 0.6
                        mb.box((cxb, cyb, zf_ - 0.07), (L * 0.78, 1.15, 0.14), 2, (0, 0, ang), False, **attrs)
                        mb.box((cxb + nx_ * 0.55, cyb + ny_ * 0.55, zf_ + 0.48), (L * 0.78, 0.04, 0.95), 3, (0, 0, ang), False, **attrs)
                        if rng_d.random() < 0.5:                      # AC outdoor unit standing on the balcony slab
                            sg_ = rng_d.choice((-1, 1)) * (L * 0.39 - 0.6)
                            ax2, ay2 = cxb + ux_ * sg_ - nx_ * 0.32, cyb + uy_ * sg_ - ny_ * 0.32
                            dm.box((ax2, ay2, zf_ + 0.33), (0.80, 0.30, 0.60), 3, (0, 0, ang), False, **attrs)
                            gx2, gy2 = ax2 + nx_ * 0.16, ay2 + ny_ * 0.16
                            dm.cyl((gx2 - ux_ * 0.12, gy2 - uy_ * 0.12, zf_ + 0.34), (gx2 - ux_ * 0.12 + nx_ * 0.012, gy2 - uy_ * 0.12 + ny_ * 0.012, zf_ + 0.34),
                                   0.21, 0.21, 12, 4, True, False, **attrs)
        else:
            stat["other"] += 1
        if not lod2 and len(fc) >= 3 and kind <= 1:
            edges = []
            for i in range(len(fc)):
                a_, b_ = fc[i], fc[(i + 1) % len(fc)]
                L_ = math.hypot(b_[0] - a_[0], b_[1] - a_[1])
                if L_ < 0.6:
                    continue
                d_ = ((b_[0] - a_[0]) / L_, (b_[1] - a_[1]) / L_)
                edges.append(dict(a=a_, d=d_, n=(d_[1], -d_[0]), L=L_, ang=math.atan2(d_[1], d_[0]), used=[]))
            hs = dict(fc=fc, top=top, zmin=zmin, kind=kind, fl=fl, fh=fh, attrs=dict(attrs, bz0=zmin), edges=edges, flat=(not pitched),
                      c=(sum(q[0] for q in fc) / len(fc), sum(q[1] for q in fc) / len(fc)), pitched=pitched)
            todo.append(hs)
            HOUSES.append(hs)
        if len(fc) >= 3:
            others.append((x0, x1, y0, y1, fc))
        boxes.append((x0, x1, y0, y1))
        kept += 1
    FOOTPRINTS[:] = others
    for hs in todo:
        _house_details(dm, hs, rng_d, near_road, others)
    mb.build("Buildings_PLATEAU", coll("P1_Buildings"), [MAT["MAT_Building_Wall"], MAT["MAT_Building_Roof"], MAT["MAT_Balcony"], MAT["MAT_Rail_Glass"]])
    dm.build("Buildings_Details", coll("P1_Buildings"),
             [MAT["MAT_Gutter"], MAT["MAT_Door"], MAT["MAT_Shutter"], MAT["MAT_AC_Body"], MAT["MAT_Black"], MAT["MAT_Concrete"], MAT["MAT_Steel_Grey"],
              MAT["MAT_Rail_Glass"], MAT["MAT_White_Panel"], MAT["MAT_Block_Wall"], MAT["MAT_Wall_Plaster"], MAT["MAT_Fence_Alu"],
              MAT["MAT_Garbage_Box"], MAT["MAT_Stone_House"], MAT["MAT_Balcony"]])
    log("  buildings kept %d, dropped %d;  %s;  details: %d faces, %d hedge shrubs" % (kept, dropped, stat, len(dm.f), len(HEDGES)))
    return boxes


def _signed_area(pts):
    a = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        a += x0 * y1 - x1 * y0
    return a / 2.0


def build_lanes(road_pts):
    """Narrow residential lanes / service roads (OSM) draped over the hillside so the lot fronts, walls and driveways have a street to
    face.  Ribbon 3 - 4.8 m wide following the terrain; segments that would run through a house or the drawn hill road are left out."""
    if not PL:
        return
    log("hillside lanes ...")
    hill = densify(road_pts, 2.0)
    mb = MB()
    n_seg = 0
    for r in PL["osm"]["roads"]:
        hw = {"residential": 2.2, "service": 1.5, "unclassified": 2.4, "tertiary": 2.4}.get(r["hw"])
        if hw is None or len(r["pts"]) < 2:
            continue
        pts = densify([tuple(p) for p in r["pts"]], 1.5)
        rows = []
        for k, (x, y) in enumerate(pts):
            a = pts[max(k - 1, 0)]
            b = pts[min(k + 1, len(pts) - 1)]
            tx, ty = b[0] - a[0], b[1] - a[1]
            tl = math.hypot(tx, ty)
            if tl < 1e-6:
                rows.append(None)
                continue
            nx, ny = -ty / tl, tx / tl
            if not (-225.0 < x < 415.0 and 7.0 < y < 225.0) or any((x - hx) ** 2 + (y - hy) ** 2 < (road_width(hy) / 2.0 + hw + 1.5) ** 2 for hx, hy in hill if abs(hy - y) < 12.0):
                rows.append(None)
                continue
            zl, zc, zr_ = (terrain_z(x + nx * hw, y + ny * hw) + 0.06, terrain_z(x, y) + 0.06, terrain_z(x - nx * hw, y - ny * hw) + 0.06)
            zc = max(zc, (zl + zr_) / 2.0)
            rows.append(((x + nx * hw, y + ny * hw, zl), (x, y, zc), (x - nx * hw, y - ny * hw, zr_)))
        for k in range(len(rows) - 1):
            r0, r1 = rows[k], rows[k + 1]
            if r0 is None or r1 is None:
                continue
            mx, my = (r0[1][0] + r1[1][0]) / 2.0, (r0[1][1] + r1[1][1]) / 2.0
            if any(bx0 - 0.3 < mx < bx1 + 0.3 and by0 - 0.3 < my < by1 + 0.3 and _pip(mx, my, poly) for bx0, bx1, by0, by1, poly in FOOTPRINTS):
                continue
            b0 = mb.verts(list(r0) + list(r1))
            mb.face((b0, b0 + 1, b0 + 4, b0 + 3), 0, False)
            mb.face((b0 + 1, b0 + 2, b0 + 5, b0 + 4), 0, False)
            n_seg += 1
    mb.build("Lanes_Hillside", coll("P1_Roads"), [MAT["MAT_Asphalt_Real"]])
    log("  %d lane segments" % n_seg)


def build_trackside_details():
    """Refs (Street View sv02 / sv04, Commons): black rubble-stone wall right behind the track, timber-look guard fence between the
    road and the track, kerb drain grates, weeds along the ballast, patched asphalt."""
    log("track-side details: stone wall, timber fence, grates, weeds, patches ...")
    c = coll("P1_Trackside")
    rng = random.Random(21)
    sw = MB()                                                            # 0 black stone, 1 concrete coping
    for xa, xb in ((-230.0, -63.0), (3.6, 420.0)):                        # not where the (spec) platform stands
        sw.box(((xa + xb) / 2, 3.6, 0.65), (xb - xa, 1.2, 2.5), 0)
        sw.box(((xa + xb) / 2, 3.5, 1.94), (xb - xa, 1.42, 0.10), 1)
    sw.build("Stone_Wall_Black", c, [MAT["MAT_Stone_Black"], MAT["MAT_Concrete"]])

    fp, fr = MB(), MB()                                                  # timber guard fence between Route 134 and the track
    for xa, xb in ((-230.0, -3.6), (3.6, 420.0)):
        x = xa + 1.0
        while x < xb - 0.5:
            fp.box((x, -3.85, 0.20), (0.17, 0.17, 1.30), 0)
            x += 2.4
        for zh in (0.10, 0.40, 0.70):
            fr.box(((xa + xb) / 2, -3.96, zh), (xb - xa, 0.05, 0.16), 0)
    fp.build("Fence_Posts", c, [MAT["MAT_Concrete"]])
    fr.build("Fence_Rails_Timber", c, [MAT["MAT_Wood_Fence"]])

    gr = MB()                                                            # kerb drain grates on the north kerb
    x = -222.0
    while x < 418.0:
        if abs(x) > 5.0:
            gr.box((x, -6.16, CFG["r134"]["z"] + 0.004), (0.9, 0.26, 0.02), 0)
        x += 14.0
    gr.build("Kerb_Grates", c, [MAT["MAT_Black"]])

    pt = MB()                                                            # patched asphalt: repairs + a utility trench
    zr = CFG["r134"]["z"] + 0.0028
    for (xc, ya, yb, w) in ((-30, -8.9, -7.4, 4.5), (12, -12.0, -10.6, 5.0), (55, -8.6, -7.2, 3.2), (-75, -12.4, -11.0, 6.0),
                            (95, -9.0, -7.5, 4.0), (-110, -8.5, -7.3, 3.5), (-48, -13.0, -6.5, 0.9), (72, -13.0, -6.5, 0.8)):
        paint_quad(pt, xc - w / 2, xc + w / 2, ya, yb, zr)
    pt.build("Road_Patches", c, [MAT["MAT_Asphalt_Patch"]])

    tuft = MB()                                                          # weed tuft: seven leaning blades
    for _ in range(7):
        a, h = rng.uniform(0, 6.283), rng.uniform(0.28, 0.7)
        lean = rng.uniform(0.05, 0.25) * h
        tuft.cyl((0, 0, 0), (math.cos(a) * lean, math.sin(a) * lean, h), 0.013, 0.002, 3, 0, False, False)
    wd = MB()
    bands = ((2.62, 3.0, -0.54), (-3.3, -2.65, -0.52), (-3.75, -3.55, -0.46), (-2.1, -1.95, -0.30))
    n = 0
    while n < 900:
        ya, yb, zg = rng.choice(bands)
        x = rng.uniform(-125.0, 125.0)
        if abs(x) < 3.9 or (ya > 0 and -63.0 < x < -3.6):
            continue
        y = rng.uniform(ya, yb)
        sc = rng.uniform(0.7, 1.7)
        wd.append(tuft, Matrix.Translation((x, y, zg)) @ Matrix.Rotation(rng.uniform(0, 6.28), 4, "Z") @ Matrix.Diagonal((sc, sc, sc * rng.uniform(0.8, 1.3), 1.0)))
        n += 1
    wd.build("Weeds_Trackside", c, [MAT["MAT_Weeds"]])


def blob(mb, c, r, segs, rings, mat, jit, rng, scale=(1, 1, 1), **attrs):
    """Lumpy foliage clump: a UV sphere whose vertices are pushed in/out randomly."""
    t = MB()
    t.sphere(c, r, segs, rings, mat, True, scale, **attrs)
    cv = Vector(c)
    t.v = [tuple(cv + (Vector(v) - cv) * (1.0 + rng.uniform(-jit, jit))) for v in t.v]
    mb.append(t)


def add_card(cm, p, size, normal, mat, rng, **attrs):
    """One leaf-spray card (quad with UVs; the alpha pattern is procedural, see MAT_Leaf_Card / MAT_Pine_Card)."""
    n = Vector(normal)
    if n.length < 1e-6:
        n = Vector((0, 0, 1))
    n.normalize()
    ref = Vector((0, 0, 1)) if abs(n.z) < 0.95 else Vector((1, 0, 0))
    u = n.cross(ref).normalized()
    v = n.cross(u)
    a = rng.uniform(0, 6.283)
    ca, sa = math.cos(a), math.sin(a)
    uu, vv = u * ca + v * sa, -u * sa + v * ca
    hw = size * rng.uniform(0.8, 1.25) * 0.5
    p = Vector(p)
    b = cm.verts([p - uu * hw - vv * hw, p + uu * hw - vv * hw, p + uu * hw + vv * hw, p - uu * hw + vv * hw])
    cm.face((b, b + 1, b + 2, b + 3), mat, False, uv=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)], crand=rng.random(), **attrs)


def rand_dir(rng):
    while True:
        d = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)))
        if 0.05 < d.length <= 1.0:
            return d.normalized()


def tpl_broad(rng):
    """Evergreen broadleaf (shii / tabu).  Returns (core, cards): a dark inner mass for depth/shadow + leaf-spray cards for the outline.
    Unit height.  core mats 0 leaf / 1 trunk;  card mat 0."""
    core, cards = MB(), MB()
    core.cyl((0, 0, 0), (0.03, 0.0, 0.42), 0.05, 0.03, 7, 1)
    lobes = []
    for _ in range(9):
        a, rr = rng.uniform(0, 6.283), rng.uniform(0.0, 0.22)
        cz = 0.62 + rng.uniform(-0.15, 0.24)
        r = rng.uniform(0.14, 0.23)
        c = (rr * math.cos(a), rr * math.sin(a), cz)
        lobes.append((c, r, rng.uniform(0.75, 0.95)))
        blob(core, c, r * 0.8, 8, 6, 0, 0.18, rng, (1, 1, lobes[-1][2]), tshade=clamp((cz - 0.35) / 0.6))
    lobes.append(((0, 0, 0.66), 0.27, 0.85))
    blob(core, (0, 0, 0.66), 0.22, 8, 6, 0, 0.14, rng, (1, 1, 0.85), tshade=0.6)
    for (c, r, sz) in lobes:
        for _ in range(34):
            d = rand_dir(rng)
            p = Vector(c) + Vector((d.x * r, d.y * r, d.z * r * sz)) * rng.uniform(0.82, 1.08)
            nrm = d + Vector((rng.uniform(-0.4, 0.4), rng.uniform(-0.4, 0.4), rng.uniform(-0.2, 0.5)))
            add_card(cards, p, rng.uniform(0.10, 0.17), nrm, 0, rng, tshade=clamp((p.z - 0.35) / 0.62))
    return core, cards


def tpl_pine(rng):
    """Black pine (kuromatsu): leaning trunk, flat needle pads at the branch tips.  core mats 1 trunk / 2 dark leaf;  card mat 1 (needles)."""
    core, cards = MB(), MB()
    pts = [(0, 0, 0), (0.035, 0.01, 0.28), (-0.02, 0.035, 0.56), (0.03, -0.02, 0.84)]
    for k, (a, b) in enumerate(zip(pts, pts[1:])):
        core.cyl(a, b, 0.05 - 0.012 * k, 0.05 - 0.012 * (k + 1), 6, 1)
    for (cz, ox, oy, r) in ((0.50, 0.17, 0.06, 0.20), (0.60, -0.15, -0.05, 0.22), (0.72, 0.08, -0.15, 0.20), (0.82, -0.07, 0.11, 0.19),
                            (0.92, 0.0, 0.0, 0.16)):
        ox += rng.uniform(-0.05, 0.05)
        oy += rng.uniform(-0.05, 0.05)
        core.cyl((0.01, 0.0, cz - 0.14), (ox, oy, cz - 0.03), 0.012, 0.008, 4, 1)
        blob(core, (ox, oy, cz), r * 0.42, 8, 5, 2, 0.25, rng, (1.0, 1.0, 0.4), tshade=clamp((cz - 0.4) / 0.6))
        for _k in range(46):
            a = rng.uniform(0, 6.283)
            d = math.sqrt(rng.random()) * r * 1.05
            p = Vector((ox + d * math.cos(a), oy + d * math.sin(a), cz + rng.uniform(-0.025, 0.045) - 0.05 * (d / r) ** 2))
            nrm = Vector((rng.uniform(-0.55, 0.55), rng.uniform(-0.55, 0.55), rng.uniform(0.6, 1.2)))
            add_card(cards, p, rng.uniform(0.11, 0.18), nrm, 1, rng, tshade=clamp((cz - 0.4) / 0.6))
    return core, cards


def tpl_cedar(rng):
    """Cedar / cypress: tall narrow tiers of drooping needle sprays.  core mats 1 trunk / 2 dark leaf;  card mat 1."""
    core, cards = MB(), MB()
    core.cyl((0, 0, 0), (0, 0, 0.2), 0.035, 0.025, 6, 1)
    z = 0.10
    for k in range(7):
        r = max(0.25 - 0.03 * k + rng.uniform(-0.015, 0.015), 0.05)
        core.cyl((0, 0, z), (0, 0, z + 0.24), r * 0.7, 0.01, 8, 2, True, True, tshade=clamp(z))
        for _ in range(32):
            a = rng.uniform(0, 6.283)
            rr = r * rng.uniform(0.35, 1.0)
            zz = z + rng.uniform(0.0, 0.2) * (1.0 - rr / (r + 1e-6)) + 0.02
            p = Vector((rr * math.cos(a), rr * math.sin(a), zz))
            nrm = Vector((math.cos(a), math.sin(a), rng.uniform(-0.5, 0.2)))
            add_card(cards, p, rng.uniform(0.085, 0.14), nrm, 1, rng, tshade=clamp(z + 0.1))
        z += 0.115
    return core, cards


def tpl_shrub(rng):
    """Evergreen shrub / hedge plant.  Unit height ~1.  core mat 0;  card mat 0."""
    core, cards = MB(), MB()
    lobes = []
    for (ox, oy, cz, r) in ((0, 0, 0.42, 0.42), (0.28, 0.1, 0.36, 0.32), (-0.26, -0.08, 0.34, 0.3), (0.05, -0.28, 0.32, 0.28), (-0.05, 0.25, 0.38, 0.3)):
        c = (ox + rng.uniform(-0.05, 0.05), oy + rng.uniform(-0.05, 0.05), cz)
        lobes.append((c, r))
        blob(core, c, r * 0.78, 8, 5, 0, 0.14, rng, (1, 1, 0.9), tshade=clamp(cz / 0.8))
    for (c, r) in lobes:
        for _ in range(26):
            d = rand_dir(rng)
            if d.z < -0.35:
                continue
            p = Vector(c) + Vector((d.x * r, d.y * r, d.z * r * 0.9)) * rng.uniform(0.85, 1.05)
            add_card(cards, p, rng.uniform(0.09, 0.15), d + Vector((0, 0, 0.2)), 0, rng, tshade=clamp(p.z / 0.8))
    return core, cards


def tpl_grass(rng, tall=False):
    m = MB()
    for _ in range(17 if not tall else 14):
        a, h = rng.uniform(0, 6.283), rng.uniform(0.45, 0.9) * (1.35 if tall else 1.0)
        lean = rng.uniform(0.10, 0.45) * h
        m.cyl((0, 0, 0), (math.cos(a) * lean, math.sin(a) * lean, h), 0.008, 0.0015, 3, 0, False, False)
    return m


def make_blocker(boxes, road_pts):
    obs = list(road_pts)
    if PL:
        for r in PL["osm"]["roads"]:
            obs += densify(r["pts"], 4.0)
    cell = 8.0
    grid, bgrid = {}, {}
    for sx, sy in obs:
        grid.setdefault((int(sx // cell), int(sy // cell)), []).append((sx, sy))
    for (x0, x1, y0, y1) in boxes:
        for gx in range(int((x0 - 4) // cell), int((x1 + 4) // cell) + 1):
            for gy in range(int((y0 - 4) // cell), int((y1 + 4) // cell) + 1):
                bgrid.setdefault((gx, gy), []).append((x0 - 3, x1 + 3, y0 - 3, y1 + 3))

    def blocked(x, y, road_r=5.0):
        gx, gy = int(x // cell), int(y // cell)
        if any(bx0 < x < bx1 and by0 < y < by1 for bx0, bx1, by0, by1 in bgrid.get((gx, gy), ())):
            return True
        if road_r > 0.0:
            for ax in (-1, 0, 1):
                for ay in (-1, 0, 1):
                    for sx, sy in grid.get((gx + ax, gy + ay), ()):
                        if (sx - x) ** 2 + (sy - y) ** 2 < road_r * road_r:
                            return True
        return False

    return blocked


def build_vegetation(boxes, road_pts):
    """Trees (broadleaf / black pine / cedar), hedges + shrubs, dry grass & pampas on the banks, leaf litter.
    Refs: Commons crossing photos (pines and evergreen hedge beside the crossing, dry-grass bank), station photos (tall dry grass on top of
    the stone wall), Street View (ivy-green slopes)."""
    n_trees = CFG["trees"]
    if n_trees <= 0:
        return
    log("vegetation (%d trees, shrubs, grass, litter) ..." % n_trees)
    rng = random.Random(7)
    T = {"broad": [tpl_broad(random.Random(10 + k)) for k in range(3)], "pine": [tpl_pine(random.Random(20 + k)) for k in range(3)],
         "cedar": [tpl_cedar(random.Random(30 + k)) for k in range(2)], "shrub": [tpl_shrub(random.Random(40 + k)) for k in range(3)]}
    blocked = make_blocker(boxes, road_pts)
    c = coll("P1_Trees")
    mats3 = [MAT["MAT_Tree_Leaf"], MAT["MAT_Tree_Trunk"], MAT["MAT_Pine_Leaf"]]

    def stamp(mb, cm, kind, x, y, hh, wsc=1.0, rot=None):
        z = terrain_z(x, y) - 0.15
        sx = hh * wsc * rng.uniform(0.85, 1.12)
        rr_ = rot if rot is not None else rng.uniform(0, 6.283)
        M = Matrix.Translation((x, y, z)) @ Matrix.Rotation(rr_, 4, "Z") @ Matrix.Diagonal((sx, sx * rng.uniform(0.9, 1.1), hh, 1.0))
        WEB_TREES.append((["broad", "pine", "cedar", "shrub"].index(kind), x, y, z, sx, hh, rr_))
        core, cards = rng.choice(T[kind])
        tr_ = rng.random()
        mb.append(core, M, None, trand=tr_)
        cm.append(cards, M, None, trand=tr_)

    # ---- trees on the hillside
    mb, cm = MB(), MB()
    placed, tries = 0, 0
    while placed < n_trees and tries < n_trees * 14:
        tries += 1
        x, y = rng.uniform(-225, 415), rng.uniform(6.5, 215)
        if rng.random() > 0.25 + 0.75 * smoothstep(10, 60, y):
            continue
        if -68 < x < -2 and y < 13:                                    # path behind the platform / station access
            continue
        if blocked(x, y, 5.0):
            continue
        h = rng.uniform(7.0, 15.0) * (0.55 + 0.45 * smoothstep(7, 30, y))
        r = rng.random()
        if y < 30 and r < 0.42:
            stamp(mb, cm, "pine", x, y, h * 0.85, 0.62)                     # pines on the sea-facing lower slope
        elif r < 0.78:
            stamp(mb, cm, "broad", x, y, h, 0.62)
        else:
            stamp(mb, cm, "cedar", x, y, h * 1.15, 0.42)
        placed += 1
    for (x, y, hh) in ((-8.6, 9.6, 9.5), (9.4, 8.4, 10.5), (-12.0, 12.5, 8.0)):        # the pines flanking the crossing (refs)
        if not blocked(x, y, 0.0):
            stamp(mb, cm, "pine", x, y, hh, 0.7)
    mb.build("Trees_Hillside", c, mats3)
    cm.build("Trees_LeafCards", c, [MAT["MAT_Leaf_Card"], MAT["MAT_Pine_Card"]])

    # ---- hedges and shrubs: along the hill road, behind the crossing, on top of the stone wall
    sm, smc = MB(), MB()
    path = densify(road_pts, 3.0)
    k = 0
    for (x, y) in path:
        if y < 6.5 or y > 62.0:
            continue
        k += 1
        if k % 2:
            continue
        nrm = Vector((1.0, 0.0, 0.0))
        for side in (-1, 1):
            off = road_width(y) / 2.0 + rng.uniform(1.4, 2.6)
            sx_, sy_ = x + side * off, y + rng.uniform(-1.0, 1.0)
            if blocked(sx_, sy_, 0.0):
                continue
            hh = rng.uniform(1.1, 2.4)
            stamp(sm, smc, "shrub", sx_, sy_, hh, 1.0)
    for xa, xb in ((-230.0, -66.0), (4.0, 420.0)):                     # low shrubs along the top of the stone wall
        x = xa
        while x < xb:
            stamp(sm, smc, "shrub", x + rng.uniform(-0.6, 0.6), rng.uniform(4.3, 5.4), rng.uniform(0.7, 1.5), 1.0)
            x += rng.uniform(1.6, 3.4)
    for (hx, hy, hh) in HEDGES:                                       # clipped evergreen hedges along the lot fronts
        stamp(sm, smc, "shrub", hx, hy, hh, 0.5)
    sm.build("Shrubs_Hedges", c, mats3)
    smc.build("Shrubs_LeafCards", c, [MAT["MAT_Leaf_Card"], MAT["MAT_Pine_Card"]])

    # ---- dry grass + pampas on the banks
    gm = MB()
    tg = [tpl_grass(random.Random(50 + k)) for k in range(3)] + [tpl_grass(random.Random(60 + k), True) for k in range(2)]
    n = 0
    while n < CFG["grass_clumps"]:
        x, y = rng.uniform(-225, 415), (rng.uniform(4.3, 9.0) if rng.random() < 0.7 else rng.uniform(9.0, 16.0))
        if (-68 < x < -2 and y < 13) or blocked(x, y, 3.2):
            continue
        tall = y < 6.5 or rng.random() < 0.12
        sc = rng.uniform(0.7, 1.25)
        gm.append(tg[3 + rng.randint(0, 1)] if tall else rng.choice(tg[:3]),
                  Matrix.Translation((x, y, terrain_z(x, y) - 0.03)) @ Matrix.Rotation(rng.uniform(0, 6.28), 4, "Z") @ Matrix.Diagonal((sc, sc, sc, 1.0)))
        n += 1
    gm.build("Grass_Dry_Banks", c, [MAT["MAT_Grass_Dry"]])

    # ---- leaf litter along kerbs, gutters and the hill-road margins
    lm = MB()
    zr, zw = CFG["r134"]["z"], CFG["r134"]["walk_z"]

    def leaf(x, y, z):
        s_ = rng.uniform(0.04, 0.09)
        a = rng.uniform(0, 6.283)
        ca, sa = math.cos(a), math.sin(a)
        pts = [(x + ca * s_, y + sa * s_, z), (x - sa * s_ * 0.45, y + ca * s_ * 0.45, z), (x - ca * s_, y - sa * s_, z), (x + sa * s_ * 0.45, y - ca * s_ * 0.45, z)]
        b = lm.verts(pts)
        lm.face((b, b + 1, b + 2, b + 3), 0, False, lrand=rng.random())

    for _ in range(CFG["litter"]):
        u = rng.random()
        x = rng.uniform(-200.0, 300.0)
        if abs(x) < 3.6 and u < 0.7:
            continue
        if u < 0.35:
            leaf(x, rng.uniform(-6.4, -6.02), zr + 0.004)               # north gutter
        elif u < 0.55:
            leaf(x, rng.uniform(-13.55, -13.15), zr + 0.004)
        elif u < 0.7:
            leaf(x, rng.uniform(-17.4, -16.6), zw + 0.004)              # sidewalk verge
        else:
            (px, py) = rng.choice(path)
            if py < 6.0:
                continue
            side = rng.choice((-1, 1))
            xx = px + side * (road_width(py) / 2.0 - rng.uniform(0.0, 0.7))
            leaf(xx, py + rng.uniform(-1, 1), hill_road_z(xx, py) + 0.004)
    lm.build("Leaf_Litter", c, [MAT["MAT_Leaf_Litter"]])
    log("  %d trees placed, %d grass clumps" % (placed, n))


# =====================================================================================================================
#  Phase 1  --  Infrastructure: ocean, sea wall, tetrapods, Route 134, hill road, track, ballast
# =====================================================================================================================
def sock(node, name, typ=None):
    """Enabled input socket by name (+ type) -- needed for nodes with several same-named sockets (Random Value)."""
    for s in node.inputs:
        if s.name == name and s.enabled and (typ is None or s.type == typ):
            return s
    return node.inputs[name]


def flat_quad_mesh(name, x0, x1, y0, y1, z, mat, collection, nx=1, ny=1):
    mb = MB()
    xs = [lerp(x0, x1, i / nx) for i in range(nx + 1)]
    ys = [lerp(y0, y1, j / ny) for j in range(ny + 1)]
    base = mb.verts([(x, y, z) for y in ys for x in xs])
    for j in range(ny):
        for i in range(nx):
            a = base + j * (nx + 1) + i
            mb.face((a, a + 1, a + nx + 2, a + nx + 1), 0, False)
    return mb.build(name, collection, [mat])


# ---------------------------------------------------------------------------------------------------- ocean
def build_ocean():
    log("ocean ...")
    sea, c = CFG["sea"], coll("P1_Ocean")
    sx, sy, ye, zs = sea["sx"], sea["sy"], sea["y_edge"], sea["z"]
    nx, ny = int(sx), int(sy)                               # 1 m grid
    mb = MB()
    xs = [-sx / 2 + i for i in range(nx + 1)]
    ys = [ye - sy + j for j in range(ny + 1)]
    base = mb.verts([(x, y, 0.0) for y in ys for x in xs])
    for j in range(ny):
        for i in range(nx):
            a = base + j * (nx + 1) + i
            mb.face((a, a + 1, a + nx + 2, a + nx + 1), 0, True)
    ob = mb.build("Ocean_Sagami", c, [MAT["MAT_Sea_Water"]])
    ob.location = (0, 0, zs)
    om = ob.modifiers.new("Ocean", "OCEAN")
    om.geometry_mode = "DISPLACE"
    om.spatial_size = 200                                   # spec 3.1
    om.wave_scale = 1.5                                     # spec 3.1  ("Wave Size")
    om.resolution = 14
    om.depth = 200.0
    om.choppiness = 1.1
    om.wave_alignment = 0.35
    om.wave_direction = math.radians(90.0)                  # swell running toward the beach (+Y)
    om.damping = 0.5
    om.use_normals = True
    om.use_foam = True
    om.foam_layer_name = "foam"
    om.foam_coverage = 0.05
    om.time = 6.0
    om.random_seed = 3
    om.wind_velocity = 12.0

    # damp the displacement toward the borders (seamless join with the far ocean) and toward the beach (shoaling)
    ng = bpy.data.node_groups.new("GN_OceanEdgeDamp", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = ng.nodes, ng.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    pos = N.new("GeometryNodeInputPosition")
    sp = N.new("ShaderNodeSeparateXYZ")
    L.new(pos.outputs["Position"], sp.inputs["Vector"])

    def m(op, a=None, b=None, clamp=False):
        n = N.new("ShaderNodeMath")
        n.operation, n.use_clamp = op, clamp
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, bpy.types.NodeSocket):
                L.new(v, n.inputs[i])
            else:
                n.inputs[i].default_value = v
        return n.outputs[0]

    def mr(v, a, b, c, d):
        n = N.new("ShaderNodeMapRange")
        n.data_type, n.clamp = "FLOAT", True
        L.new(v, n.inputs[0])
        n.inputs[1].default_value, n.inputs[2].default_value = a, b
        n.inputs[3].default_value, n.inputs[4].default_value = c, d
        return n.outputs[0]

    ax = m("ABSOLUTE", sp.outputs["X"])
    mx = mr(m("SUBTRACT", sx / 2, ax), 0.0, 45.0, 0.0, 1.0)
    my = mr(m("SUBTRACT", sp.outputs["Y"], ye - sy), 0.0, 45.0, 0.0, 1.0)
    shoal = mr(m("SUBTRACT", sea["shore_y"], sp.outputs["Y"]), 0.0, 30.0, 0.30, 1.0)
    amp = N.new("ShaderNodeValue")
    amp.outputs[0].default_value = 1.0
    fac = m("MULTIPLY", m("MULTIPLY", m("MINIMUM", mx, my), shoal), amp.outputs[0])
    cz = N.new("ShaderNodeCombineXYZ")
    L.new(sp.outputs["X"], cz.inputs["X"])
    L.new(sp.outputs["Y"], cz.inputs["Y"])
    L.new(m("MULTIPLY", sp.outputs["Z"], fac), cz.inputs["Z"])
    setp = N.new("GeometryNodeSetPosition")
    L.new(gi.outputs[0], setp.inputs["Geometry"])
    L.new(cz.outputs["Vector"], setp.inputs["Position"])
    L.new(setp.outputs["Geometry"], go.inputs[0])
    gn = ob.modifiers.new("EdgeDamp", "NODES")
    gn.node_group = ng

    # spec fixes Spatial Size 200 / Wave Size 1.5, which alone gives a ~2 m peak-to-peak swell; a believable bay swell at
    # sunset is ~0.1 m std, so the amplitude is scaled (measured) in the damping node.
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    zz = [v.co.z for v in me.vertices]
    ev.to_mesh_clear()
    mean = sum(zz) / len(zz)
    sd = math.sqrt(sum((z - mean) ** 2 for z in zz) / len(zz))
    amp.outputs[0].default_value = clamp(0.10 / max(sd, 1e-6), 0.02, 1.0)
    log("  ocean swell std %.3f m -> amplitude scale %.2f (peak-peak %.2f m before scaling)" % (sd, amp.outputs[0].default_value, max(zz) - min(zz)))

    # far ocean: same shader, 3 cm lower so the displaced near ocean always wins; wave height is damped to 0 at its borders
    flat_quad_mesh("Ocean_Far", -100000, 100000, -100000, ye, zs - 0.03, MAT["MAT_Sea_Water"], c)
    flat_quad_mesh("Seabed", -100000, 100000, -100000, 2.0, -11.0, simple("MAT_Seabed", "#2D4A50", 0.0, 0.95), c)
    return ob


# ---------------------------------------------------------------------------------------------------- sea wall
def build_seawall():
    log("sloped concrete revetment + cable guard fence ...")
    w = CFG["wall"]
    x0, x1 = -230.0, 420.0
    c = coll("P1_SeaWall")
    zw = CFG["r134"]["walk_z"]
    y0, y_ap, y_sl = w["y"], w["apron_end"], w["slope_end"]
    z_top, z_toe = zw - 0.01, w["toe_z"]
    mb = MB()                                                    # slab cross-section: flat apron, then the slope, thick enough to hide the terrain
    mb.prism_x([(y0, z_top), (y_ap, z_top), (y_sl, z_toe), (y_sl - 0.10, z_toe - 0.60), (y_ap, z_top - 0.70), (y0, z_top - 0.70)], x0, x1, 0)
    slab = mb.build("Revetment_Slope_Concrete", c, [MAT["MAT_Revetment"]])

    rl = MB()          # low guard-cable fence (Street View): square posts every 3 m, three horizontal cables. 0 posts, 1 cables
    yf = y0 + 0.30
    xr = x0 + 1.0
    while xr < x1:
        rl.box((xr, yf, zw + 0.42), (0.15, 0.15, 0.84), 0)
        rl.box((xr, yf, zw + 0.86), (0.19, 0.19, 0.05), 0)                                               # post cap
        xr += 3.0
    for hz in (0.32, 0.58, 0.80):
        rl.cyl((x0, yf - 0.09, zw + hz), (x1, yf - 0.09, zw + hz), 0.013, 0.013, 6, 1, False, True)
    rl.build("SeaWall_Railing", c, [MAT["MAT_Concrete"], MAT["MAT_Steel_Galv"]])
    return slab


def build_tetrapods():
    if not CFG["tetrapods"]:
        return
    log("tetrapods ...")
    g = SG("MAT_Tetrapod")                                   # spec 3.1: wet Roughness 0.05 / dry 0.7 by world Z
    col, r, nrm = concrete_graph(g, "#8B8D8C", (0.7, 0.8), wet_z=(-4.6, -3.1), salt=True)
    z = g.sep(g.world_pos())[2]
    wet = g.mapr(z, -3.15, -4.05, 0.0, 1.0)
    reg(g, g.principled(col, 0.0, g.mapr(wet, 0.0, 1.0, 0.7, 0.05), normal=nrm))

    leg = 1.05
    dirs = [Vector(v).normalized() for v in ((1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1))]
    tpl = MB()
    for d in dirs:
        tpl.cyl((0, 0, 0), tuple(d * leg), 0.33, 0.20, 9, 0, True, True)
    tpl.sphere((0, 0, 0), 0.34, 8, 5, 0, True)
    mb = MB()
    rng = random.Random(11)
    x = -228.0
    rows = ((-26.6, 0.0), (-28.2, 1.3))
    while x < 418.0:
        for y_, off in rows:
            xx = x + off + rng.uniform(-0.25, 0.25)
            yy = y_ + rng.uniform(-0.25, 0.25)
            zz = terrain_z(xx, yy) + 0.28
            R = Matrix.Rotation(rng.uniform(0, 6.28), 4, "Z") @ Matrix.Rotation(rng.uniform(0, 6.28), 4, "X") @ Matrix.Rotation(rng.uniform(0, 6.28), 4, "Y")
            mb.append(tpl, Matrix.Translation((xx, yy, zz)) @ R)
        x += 2.7
    mb.build("Tetrapods_WaveBreak", coll("P1_SeaWall"), [MAT["MAT_Tetrapod"]])


# ---------------------------------------------------------------------------------------------------- roads
def strip_x(mb, x0, x1, y0, y1, z, mat=0, ndiv=1):
    xs = [lerp(x0, x1, i / ndiv) for i in range(ndiv + 1)]
    for a, b in zip(xs, xs[1:]):
        mb.quad((a, y0, z), (b, y0, z), (b, y1, z), (a, y1, z), mat)


def paint_quad(mb, x0, x1, y0, y1, z, mat=0):
    mb.quad((x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z), mat)


def hill_road_z(x, y):
    if y <= -6.0:
        return -0.30
    if y < -2.6:
        return lerp(-0.30, -0.03, smoothstep(-6.0, -2.6, y))
    if y <= 2.6:
        return -0.03
    if y <= 8.0:
        return lerp(-0.03, terrain_z(x, y) + 0.05, smoothstep(2.6, 8.0, y))
    return terrain_z(x, y) + 0.05


def road_width(y):
    return lerp(6.5, 5.0, smoothstep(6.0, 26.0, abs(y)))


def build_roads(path):
    log("Route 134, sidewalk, hill road ...")
    c = coll("P1_Roads")
    r = CFG["r134"]
    x0, x1 = -230.0, 420.0
    zr, zw = r["z"], r["walk_z"]
    asph = MB()
    strip_x(asph, x0, x1, -13.5, -6.0, zr, 0, 130)                              # carriageway 7.5 m (0.5 + 3.25 + 3.25 + 0.5)
    strip_x(asph, x0, -3.4, -5.9, -4.1, zw, 0, 40)                              # track-side footway (OSM: footway y~-5)
    strip_x(asph, 3.4, x1, -5.9, -4.1, zw, 0, 80)
    concrete = MB()
    strip_x(concrete, x0, x1, -17.5, -13.5, zw, 0, 130)                          # sea-side sidewalk (2.5 m walk + verge to the edge)
    concrete.box(((x0 + x1) / 2, -13.56, (zr + zw) / 2), (x1 - x0, 0.12, zw - zr), 0)             # curb risers
    concrete.box(((x0 + x1) / 2, -5.95, (zr + zw) / 2), (x1 - x0, 0.12, zw - zr), 0)
    concrete.build("Sidewalk_Concrete", c, [MAT["MAT_Platform_Top"]])

    # hill road: draped strip with skirts, width tapering 6.5 -> 5.0 m
    samples = [p for p in densify(path, 1.0) if -6.0 <= p[1] <= 72.0]
    samples = [(0.54, -6.0)] + samples if samples[0][1] > -6.0 else samples
    rows = []
    for k, (x, y) in enumerate(samples):
        a = samples[max(k - 1, 0)]
        b = samples[min(k + 1, len(samples) - 1)]
        t = Vector((b[0] - a[0], b[1] - a[1], 0.0))
        t.normalize()
        n = Vector((-t.y, t.x, 0.0))
        hw = road_width(y) / 2.0
        z = hill_road_z(x, y)
        rows.append(((x + n.x * hw, y + n.y * hw, z), (x - n.x * hw, y - n.y * hw, z)))
    b0 = asph.verts([p for row in rows for p in row])
    for k in range(len(rows) - 1):
        a = b0 + 2 * k
        asph.face((a, a + 1, a + 3, a + 2), 0, False)
    for side in (0, 1):                                                          # skirts
        s0 = asph.verts([(row[side][0], row[side][1], row[side][2] - 0.45) for row in rows])
        for k in range(len(rows) - 1):
            i0 = b0 + 2 * k + side
            i1 = b0 + 2 * (k + 1) + side
            if side == 0:
                asph.face((i0, s0 + k, s0 + k + 1, i1), 0, False)
            else:
                asph.face((i0, i1, s0 + k + 1, s0 + k), 0, False)
    asph.build("Roads_Asphalt", c, [MAT["MAT_Asphalt_Real"]])

    # ---- road paint (faded white): edge lines, dashed centre line, zebra, stop lines
    pt = MB()
    zp = zr + 0.004
    strip_x(pt, x0, x1, -6.62, -6.47, zp, 0, 130)
    strip_x(pt, x0, x1, -13.03, -12.88, zp, 0, 130)
    for k in range(8):                                                           # zebra crossing (pedestrians over Route 134)
        ya = -13.05 + 0.45 * 2 * k
        paint_quad(pt, 6.2, 9.2, ya, ya + 0.45, zp)
    for x_ in (-20.0, 42.0):                                                     # two arrows (right of centre = travel lane)
        for lane_y, d in ((-8.15, 1.0), (-11.45, -1.0)):
            xa = x_ if d > 0 else x_ + 12.0
            paint_quad(pt, xa - d * 0.0, xa + d * 2.4, lane_y - 0.08, lane_y + 0.08, zp)
            pt.quad((xa + d * 2.4, lane_y - 0.35, zp), (xa + d * 3.4, lane_y, zp), (xa + d * 3.4, lane_y, zp), (xa + d * 2.4, lane_y + 0.35, zp))
    zs = hill_road_z(1.7, -5.35) + 0.01
    paint_quad(pt, 0.15, 3.15, -5.55, -5.10, zs)                                 # stop line at the T-junction (southbound lane)
    for (xa, xb, yy) in ((-3.15, -0.15, -3.65), (0.15, 3.15, 3.65)):            # railway-crossing stop lines
        paint_quad(pt, xa, xb, yy - 0.2, yy + 0.2, hill_road_z(0, yy) + 0.008)
    pt.build("Road_Paint", c, [MAT["MAT_Paint_White"]])
    po = MB()                                                                    # orange no-overtaking centre line (interrupted at the junction)
    for xa, xb in ((x0, -4.6), (4.6, x1)):
        strip_x(po, xa, xb, -9.83, -9.68, zp + 0.001, 0, 100)
    po.build("Road_CentreLine_Orange", c, [MAT["MAT_Paint_Orange"]])

    # painted characters: "40" speed limit, "止まれ" (stop)
    tm = MAT["MAT_Paint_White"]
    for x_, ln_y, rot in ((-42.0, -8.15, -math.pi / 2), (60.0, -11.45, math.pi / 2)):
        text_obj("Paint_40_%d" % x_, "40", (x_, ln_y, zp + 0.003), (0, 0, rot), 0.95, tm, c, 0.0, "CENTER", (1.0, 2.6, 1.0), cjk=False)
    text_obj("Paint_Tomare", "止まれ", (1.65, -3.2, hill_road_z(1.65, -3.2) + 0.012), (0, 0, math.pi), 0.55, tm, c, 0.0, "CENTER", (1.0, 2.4, 1.0))

    # manholes (cast iron, d = 0.6 m)
    mh = MB()
    for (x_, y_, z_) in ((-18.0, -11.4, zr), (31.0, -8.1, zr), (-64.0, -8.2, zr), (0.9, -3.4, hill_road_z(0.9, -3.4))):
        mh.cyl((x_, y_, z_ + 0.001), (x_, y_, z_ + 0.016), 0.30, 0.30, 24, 0, True, False)
    mh.build("Manholes", c, [MAT["MAT_Manhole"]])
    return path


# ---------------------------------------------------------------------------------------------------- railway
RAIL_PROFILE = [(-0.0635, -0.153), (0.0635, -0.153), (0.0635, -0.140), (0.0075, -0.118), (0.0075, -0.045), (0.0325, -0.036),
                (0.0325, -0.012), (0.0250, 0.0), (-0.0250, 0.0), (-0.0325, -0.012), (-0.0325, -0.036), (-0.0075, -0.045),
                (-0.0075, -0.118), (-0.0635, -0.140)]
RAIL_MATS = [0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 0]          # edges 5..9 = polished head (MAT_Rail_Shiny), rest rusty side
RAIL_Y = CFG["gauge"] / 2 + 0.0325


def build_track():
    log("track: rails, sleepers, ballast ...")
    c = coll("P1_Track")
    x0, x1 = CFG["rail_x"]
    rails = MB()
    for sgn in (-1, 1):
        prof_ = [(y + sgn * RAIL_Y, z) for y, z in RAIL_PROFILE]
        rails.prism_x(prof_, x0, x1, RAIL_MATS)
    rails.build("Rails", c, [MAT["MAT_Rail_Rust"], MAT["MAT_Rail_Shiny"]], smooth_angle=math.radians(40))

    rng = random.Random(5)
    pc, wood, plates = MB(), MB(), MB()
    x = x0 + 0.3
    kind, run = "pc", 4
    while x < x1:
        if abs(x) < 3.6:
            x += 0.6
            continue
        run -= 1
        if run <= 0:
            kind = "wood" if rng.random() < 0.42 else "pc"
            run = rng.randint(2, 9)
        xx = x + rng.uniform(-0.012, 0.012)
        yaw = rng.uniform(-0.013, 0.013)
        dz = rng.uniform(-0.006, 0.004)
        top = -0.165 + dz
        R = Euler((0, 0, yaw), "XYZ")
        if kind == "pc":
            pc.box((xx, 0, top - 0.055), (0.20, 0.72, 0.11), 0, R)
            for sgn in (-1, 1):
                pc.box((xx, sgn * 0.58, top - 0.08), (0.24, 0.62, 0.16), 0, R)
                pc.box((xx, sgn * 1.02, top - 0.075), (0.21, 0.46, 0.15), 0, R)
        else:
            wood.box((xx, 0, top - 0.07), (0.22, 2.10 + rng.uniform(-0.03, 0.03), 0.14 + rng.uniform(-0.01, 0.01)), 0, R)
        for sgn in (-1, 1):
            plates.box((xx, sgn * RAIL_Y, top + 0.006), (0.18, 0.15, 0.012), 0, R)
        x += 0.6 + (rng.uniform(0.02, 0.06) if rng.random() < 0.06 else 0.0)
    pc.build("Sleepers_PC", c, [MAT["MAT_Sleeper_PC"]])
    wood.build("Sleepers_Wood", c, [MAT["MAT_Sleeper_Wood"]])
    plates.build("Rail_Plates", c, [MAT["MAT_Steel_Galv"]])

    # cable troughs beside the track (signal cables), broken at the crossing
    tr = MB()
    for sgn in (-1, 1):
        for a, b in ((x0, -4.2), (4.2, x1)):
            tr.box(((a + b) / 2, sgn * 2.05, -0.30), (b - a, 0.28, 0.24), 0)
    tr.build("Cable_Troughs", c, [MAT["MAT_Concrete"]])

    # ---- ballast bed (trapezoid, subdivided top for scattering)
    ycs = [(-2.55, -0.55), (-1.60, -0.20)] + [(-1.55 + 3.1 * k / 20.0, -0.20) for k in range(21)] + [(1.60, -0.20), (2.55, -0.55)]
    nxs = 100
    bed = MB()
    xs = [lerp(x0, x1, i / nxs) for i in range(nxs + 1)]
    base = bed.verts([(xv, y, z) for xv in xs for (y, z) in ycs])
    nc = len(ycs)
    for i in range(nxs):
        for j in range(nc - 1):
            a = base + i * nc + j
            bed.face((a, a + nc, a + nc + 1, a + 1), 0, False)
    ob = bed.build("Ballast_Bed", c, [MAT["MAT_Ballast_Bed"]])
    add_ballast_scatter(ob)
    return ob


def rock_templates(n=3):
    rocks = coll("Ballast_RockSources")
    rng = random.Random(3)
    out = []
    for k in range(n):
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=1, radius=0.5)
        for v in bm.verts:
            v.co.x *= rng.uniform(0.75, 1.15)
            v.co.y *= rng.uniform(0.75, 1.15)
            v.co.z *= rng.uniform(0.6, 1.0)
            v.co += Vector((rng.uniform(-0.06, 0.06), rng.uniform(-0.06, 0.06), rng.uniform(-0.05, 0.05)))
        me = bpy.data.meshes.new("Rock%d" % k)
        bm.to_mesh(me)
        bm.free()
        for p in me.polygons:
            p.use_smooth = False
        me.materials.append(MAT["MAT_Ballast_Rock"])
        ob = bpy.data.objects.new("Rock%d" % k, me)
        rocks.objects.link(ob)
        out.append(ob)
    return rocks


def add_ballast_scatter(bed):
    """Geometry Nodes: irregular 3-5 cm rocks instanced on the bed (dense near the crossing, thinning to +-70 m)."""
    rocks = rock_templates()
    ng = bpy.data.node_groups.new("GN_BallastScatter", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = ng.nodes, ng.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")

    def math_(op, a, b=None, clamp=False):
        n = N.new("ShaderNodeMath")
        n.operation, n.use_clamp = op, clamp
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, bpy.types.NodeSocket):
                L.new(v, n.inputs[i])
            else:
                n.inputs[i].default_value = v
        return n.outputs[0]

    pos = N.new("GeometryNodeInputPosition")
    sp = N.new("ShaderNodeSeparateXYZ")
    L.new(pos.outputs["Position"], sp.inputs["Vector"])
    ax = math_("ABSOLUTE", sp.outputs["X"])
    fall = N.new("ShaderNodeMapRange")
    fall.data_type, fall.clamp = "FLOAT", True
    L.new(ax, fall.inputs[0])
    fall.inputs[1].default_value, fall.inputs[2].default_value = 24.0, 70.0
    fall.inputs[3].default_value, fall.inputs[4].default_value = 1.0, 0.0
    dens = math_("MULTIPLY", math_("MULTIPLY", fall.outputs[0], math_("GREATER_THAN", ax, 3.6)),   # none on the crossing panels
                 CFG["ballast_density"])
    nrm = N.new("GeometryNodeInputNormal")
    spn = N.new("ShaderNodeSeparateXYZ")
    L.new(nrm.outputs["Normal"], spn.inputs["Vector"])
    up = math_("GREATER_THAN", spn.outputs["Z"], 0.9)

    dist = N.new("GeometryNodeDistributePointsOnFaces")
    dist.distribute_method = "RANDOM"
    L.new(gi.outputs[0], dist.inputs["Mesh"])
    L.new(up, dist.inputs["Selection"])
    L.new(dens, dist.inputs["Density"])                                            # RANDOM mode: Density is a field (points/m2)
    dist.inputs["Seed"].default_value = 4

    ci = N.new("GeometryNodeCollectionInfo")
    ci.transform_space = "RELATIVE"
    ci.inputs["Collection"].default_value = rocks
    ci.inputs["Separate Children"].default_value = True
    ci.inputs["Reset Children"].default_value = True

    iop = N.new("GeometryNodeInstanceOnPoints")
    L.new(dist.outputs["Points"], iop.inputs["Points"])
    L.new(ci.outputs["Instances"], iop.inputs["Instance"])
    iop.inputs["Pick Instance"].default_value = True

    ridx = N.new("FunctionNodeRandomValue")
    ridx.data_type = "INT"
    sock(ridx, "Min", "INT").default_value = 0
    sock(ridx, "Max", "INT").default_value = 2
    sock(ridx, "Seed").default_value = 1
    L.new(ridx.outputs["Value"] if "Value" in ridx.outputs else [o for o in ridx.outputs if o.enabled][0], iop.inputs["Instance Index"])
    rrot = N.new("FunctionNodeRandomValue")
    rrot.data_type = "FLOAT_VECTOR"
    sock(rrot, "Min", "VECTOR").default_value = (0.0, 0.0, 0.0)
    sock(rrot, "Max", "VECTOR").default_value = (6.283, 6.283, 6.283)
    sock(rrot, "Seed").default_value = 2
    L.new([o for o in rrot.outputs if o.enabled and o.type == "VECTOR"][0], iop.inputs["Rotation"])
    rscl = N.new("FunctionNodeRandomValue")
    rscl.data_type = "FLOAT_VECTOR"
    sock(rscl, "Min", "VECTOR").default_value = (0.030, 0.028, 0.020)             # 3-5 cm rocks (template diameter = 1)
    sock(rscl, "Max", "VECTOR").default_value = (0.050, 0.048, 0.034)
    sock(rscl, "Seed").default_value = 3
    L.new([o for o in rscl.outputs if o.enabled and o.type == "VECTOR"][0], iop.inputs["Scale"])

    join = N.new("GeometryNodeJoinGeometry")
    L.new(gi.outputs[0], join.inputs["Geometry"])
    L.new(iop.outputs["Instances"], join.inputs["Geometry"])
    L.new(join.outputs["Geometry"], go.inputs[0])
    md = bed.modifiers.new("BallastScatter", "NODES")
    md.node_group = ng
    lc = bpy.context.view_layer.layer_collection.children.get(rocks.name)
    if lc:
        lc.exclude = True                                                          # sources stay out of the render


# =====================================================================================================================
#  Phase 2  --  Architecture & props: station platform, level crossing, poles, wires
# =====================================================================================================================
_SHARED = {}


def shared_object(key, name, build, loc, rot, collection, mats):
    """Objects that share one mesh datablock (striped boards / arms keep their own local axes for the stripe shader)."""
    me = _SHARED.get(key)
    if me is None:
        ob0 = build().build(name, collection, mats)
        me = _SHARED[key] = ob0.data
        bpy.data.objects.remove(ob0)
    ob = bpy.data.objects.new(name, me)
    ob.location, ob.rotation_euler = loc, rot
    collection.objects.link(ob)
    return ob


def wedge(mb, xh, xl, ya, yb, zh, zl, zb, mt=1, ms=0):
    v = mb.verts([(xh, ya, zh), (xh, yb, zh), (xl, yb, zl), (xl, ya, zl), (xh, ya, zb), (xh, yb, zb), (xl, yb, zb), (xl, ya, zb)])
    mb.face((v, v + 1, v + 2, v + 3), mt)
    mb.face((v, v + 4, v + 7, v + 3), ms)
    mb.face((v + 1, v + 2, v + 6, v + 5), ms)
    mb.face((v + 3, v + 2, v + 6, v + 7), ms)


def facing(dir_y):
    """Euler that makes a Text object (normal +Z, up +Y) face -Y (dir_y=-1) or +Y (dir_y=+1) with up=+Z."""
    return (math.pi / 2, 0, 0) if dir_y < 0 else (math.pi / 2, 0, math.pi)


# ---------------------------------------------------------------------------------------------------- platform
def build_platform():
    log("station platform ...")
    P = CFG["platform"]
    x0, x1, y0, H = P["x0"], P["x1"], P["y0"], P["height"]
    y1 = y0 + P["width"]
    c = coll("P2_Station")
    # NOTE: the spec gives Y = 1.8 m (centre) for a 2.6 m wide platform -> near edge at 0.5 m, which lies inside the 1.067 m
    # gauge / the 2.4 m car body.  The platform is therefore placed with its near edge at y0 = 1.35 m (car half-width 1.2 m +
    # 0.15 m clearance); width (2.6 m), length (45 m) and height (1.1 m) follow the spec.
    mb = MB()                                       # mats: 0 wall, 1 top, 2 coping, 3 tactile, 4 black, 5 galv steel
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    mb.box((xm, ym, (H - 0.55) / 2), (x1 - x0, y1 - y0, H + 0.55), 0)
    paint_quad(mb, x0, x1, y0, y1, H + 0.002, 1)
    mb.box((xm, y0 + 0.10, H - 0.035), (x1 - x0, 0.26, 0.07), 2)
    paint_quad(mb, x0, x1, y0 + 0.30, y0 + 0.60, H + 0.006, 3)
    xj = x0 + 5.0
    while xj < x1 - 1.0:                            # vertical expansion joints
        mb.box((xj, y0 - 0.006, (H - 0.55) / 2 - 0.05), (0.03, 0.02, H + 0.45), 4)
        xj += 5.0
    xw = x0 + 2.0
    while xw < x1 - 1.0:                            # drain / weep holes
        mb.cyl((xw, y0 + 0.01, 0.30), (xw, y0 - 0.07, 0.30), 0.04, 0.04, 8, 4, True, False)
        xw += 3.0
    xf = x0 + 1.5                                   # back fence
    while xf < x1 - 1.4:
        mb.box((xf, y1 - 0.08, H + 0.5), (0.05, 0.05, 1.0), 5)
        xf += 3.0
    mb.cyl((x0 + 1.5, y1 - 0.08, H + 0.97), (x1 - 1.5, y1 - 0.08, H + 0.97), 0.02, 0.02, 6, 5, False, True)
    mb.cyl((x0 + 1.5, y1 - 0.08, H + 0.50), (x1 - 1.5, y1 - 0.08, H + 0.50), 0.018, 0.018, 6, 5, False, True)
    # west end ramp (towards 江ノ島/藤沢) and east end steps (towards the crossing)
    wedge(mb, x0, x0 - 6.5, y0 + 0.35, y0 + 2.25, H, -0.12, -0.55, 1, 0)
    mb.cyl((x0, y0 + 0.35, H + 0.95), (x0 - 6.5, y0 + 0.35, -0.12 + 0.95), 0.022, 0.022, 6, 5, False, True)
    for i in range(7):
        top = H - 0.18 * (i + 1)
        mb.box((x1 + 0.15 + 0.30 * i, y0 + 1.3, (top - 0.55) / 2), (0.30, 1.9, top + 0.55), 1)
    mb.box((x1 + 3.2, y0 + 1.3, -0.30), (2.6, 1.9, 0.5), 1)
    plat = mb.build("Platform", c, [MAT["MAT_Platform_Wall"], MAT["MAT_Platform_Top"], MAT["MAT_Concrete"], MAT["MAT_Tactile_Yellow"],
                                    MAT["MAT_Black"], MAT["MAT_Steel_Galv"]], bevel=0.008)

    # ---- canopy (refs: Street View + Commons): one lean-to roof over the whole platform on weathered timber posts, dark fascia board,
    #      gutter + down-pipes, fluorescent tubes and advertisement boards on the back
    xa, xb = x0 - 0.6, x1 + 0.6
    yc, yf = y1 - 0.35, y0 + 0.55
    zb, zf = H + 2.85, H + 2.45
    slope = (zf - zb) / (yf - yc)
    st = MB()                                       # 0 timber, 1 dark fascia, 2 galvanised (gutter / pipes / plates)
    for k in range(11):
        xc = x0 + 4.5 * k
        st.box((xc, yc, H + 1.42), (0.14, 0.14, 2.84), 0)                                    # back post
        st.box((xc, yf + 0.05, H + 1.22), (0.13, 0.13, 2.44), 0)                              # front post
        for yy, zz in ((yc, H + 0.02), (yf + 0.05, H + 0.02)):
            st.box((xc, yy, zz), (0.28, 0.28, 0.04), 2)                                      # base plates
        st.cyl((xc, yc, zb - 0.70), (xc, yc - 0.50, zb - 0.06), 0.03, 0.03, 4, 0, True, False)  # knee brace
    st.box(((xa + xb) / 2, yc, zb - 0.09), (xb - xa, 0.12, 0.16), 0)                          # back beam
    st.box(((xa + xb) / 2, yf + 0.05, zf - 0.09), (xb - xa, 0.12, 0.16), 0)                   # front beam
    st.box(((xa + xb) / 2, yf - 0.20, zf - 0.13), (xb - xa + 0.1, 0.05, 0.46), 1)             # dark fascia board
    xr = xa
    while xr <= xb + 0.01:
        st.cyl((xr, yc, zb - 0.02), (xr, yf, zf - 0.02), 0.032, 0.032, 4, 0, True, False)     # rafters
        xr += 1.5
    st.cyl((xa, yf - 0.28, zf - 0.40), (xb, yf - 0.28, zf - 0.40), 0.05, 0.05, 8, 2, False, True)   # gutter
    for xd in (x0 + 4.5, x0 + 22.5, x1 - 4.5):
        st.cyl((xd, yf - 0.28, zf - 0.42), (xd, yf - 0.28, H + 0.05), 0.035, 0.035, 8, 2, False, True)   # down-pipes
    st.build("Canopy_Timber", c, [MAT["MAT_Wood_Post"], MAT["MAT_Wood_Dark"], MAT["MAT_Steel_Galv"]], bevel=0.004)

    roof = MB()
    n = int((xb - xa + 0.6) / 0.0325)
    xs = [xa - 0.3 + (xb - xa + 0.6) * i / n for i in range(n + 1)]
    ya_, yb_ = yc + 0.30, yf - 0.20
    base = roof.verts([(x, y, zb + (y - yc) * slope + 0.07 + 0.022 * math.sin(2 * math.pi * (x - xa) / 0.13))
                       for y in (ya_, yb_) for x in xs])
    for i in range(n):
        roof.face((base + i, base + i + 1, base + n + 1 + i + 1, base + n + 1 + i), 0, True)
    roof.build("Canopy_Roof_Slate", c, [MAT["MAT_Slate_Roof"]])

    lamps = MB()                                    # fluorescent tubes hanging under the rafters
    for k in range(10):
        xc = x0 + 2.25 + 4.5 * k
        ym = (yc + yf) / 2
        zl = zb + (ym - yc) * slope - 0.28
        lamps.box((xc, ym, zl), (1.0, 0.13, 0.06), 0)
        for dx in (-0.4, 0.4):
            lamps.cyl((xc + dx, ym, zl), (xc + dx, ym, zl + 0.26), 0.006, 0.006, 4, 0, False, False)
    lamps.build("Platform_Lamps", c, [MAT["MAT_Lamp_Fluor"]])

    ads = MB()                                      # advertisement boards on the back (0 frame, 1 poster)
    rng_ad = random.Random(17)
    for k in range(10):
        xc = x0 + 2.25 + 4.5 * k
        ads.box((xc, y1 - 0.02, H + 1.62), (2.0, 0.04, 0.90), 0)
        ads.box((xc, y1 - 0.045, H + 1.62), (1.86, 0.012, 0.76), 1, adrand=rng_ad.random())
    ads.build("Platform_Ad_Boards", c, [MAT["MAT_Wood_Dark"], MAT["MAT_Ad_Poster"]])

    # ---- benches (wood, facing the sea)
    bn = MB()                                       # 0 wood, 1 steel
    for xb_ in (-40.5, -30.0):
        bn.box((xb_, y1 - 0.62, H + 0.44), (1.8, 0.42, 0.045), 0)
        bn.box((xb_, y1 - 0.42, H + 0.72), (1.8, 0.04, 0.34), 0)
        for dx in (-0.8, 0.8):
            bn.box((xb_ + dx, y1 - 0.62, H + 0.21), (0.05, 0.36, 0.42), 1)
    bn.build("Benches", c, [MAT["MAT_Wood_Bench"], MAT["MAT_Steel_Grey"]], bevel=0.004)

    # ---- station name boards (駅名標) hung from the canopy
    sb = MB()                                       # 0 white, 1 blue, 2 galv
    signs = []
    for xs_ in (-36.5, -23.5):
        yb0, zc = 2.55, H + 1.95
        sb.box((xs_, yb0, zc), (1.6, 0.04, 0.56), 0)
        sb.box((xs_, yb0 - 0.003, zc + 0.215), (1.6, 0.046, 0.13), 1)
        for dx in (-0.6, 0.6):
            sb.cyl((xs_ + dx, yb0, zc + 0.28), (xs_ + dx, yb0, zb + (yb0 - yc) * slope + 0.02), 0.012, 0.012, 5, 2, False, True)
        signs.append((xs_, yb0, zc))
    sb.build("Station_Name_Boards", c, [MAT["MAT_Sign_White"], MAT["MAT_Sign_Blue"], MAT["MAT_Steel_Galv"]])
    for xs_, yb0, zc in signs:
        yt = yb0 - 0.027
        text_obj("Sign_Name", "鎌倉高校前", (xs_, yt, zc - 0.02), facing(-1), 0.20, MAT["MAT_Sign_Black"], c)
        text_obj("Sign_Name_En", "Kamakura-Kokomae", (xs_, yt, zc - 0.17), facing(-1), 0.062, MAT["MAT_Sign_Black"], c, cjk=False)
        text_obj("Sign_No", "EN08", (xs_ - 0.62, yt - 0.003, zc + 0.215), facing(-1), 0.09, MAT["MAT_Sign_White"], c, cjk=False)
        text_obj("Sign_W", "< 腰越", (xs_ - 0.55, yt, zc - 0.20), facing(-1), 0.075, MAT["MAT_Sign_Black"], c)
        text_obj("Sign_E", "七里ヶ浜 >", (xs_ + 0.52, yt, zc - 0.20), facing(-1), 0.075, MAT["MAT_Sign_Black"], c)

    # ---- one-man-operation confirmation mirror, security cameras, IC gates (Passage), vending machine
    mm = MB()                                       # 0 grey steel, 1 orange frame, 2 mirror, 3 black, 4 white, 5 blue, 6 pvc
    px, py = x1 - 1.6, y0 + 0.45
    mm.cyl((px, py, H), (px, py, H + 2.35), 0.032, 0.03, 8, 0)
    d = Vector((-0.55, -0.83, -0.15)).normalized()                                     # mirror faces the cab approaching from west
    Rm = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
    ring, dome = MB(), MB()
    ring.cyl((0, 0, -0.03), (0, 0, 0.03), 0.28, 0.28, 24, 1)
    dome.sphere((0, 0, 0), 0.25, 20, 10, 2, True, (1, 1, 0.22))
    mm.append(ring, Matrix.Translation((px, py, H + 2.45)) @ Rm)
    mm.append(dome, Matrix.Translation((px, py, H + 2.45)) @ Rm @ Matrix.Translation((0, 0, 0.02)))
    for xc in (-50.5, -14.5):                                                           # security cameras on the posts
        mm.box((xc, yc + 0.18, H + 2.55), (0.10, 0.24, 0.10), 4)
        mm.sphere((xc, yc + 0.32, H + 2.50), 0.055, 8, 5, 3)
    # vending machine (glass door against salt) + Passage simple IC gates with PVC cover
    vx, vy = -13.2, y1 - 0.38
    v = RESEARCH["station"]["vending"]
    mm.box((vx, vy, H + v[2] / 2), (v[0], v[1], v[2]), 4)
    mm.box((vx, vy - v[1] / 2 - 0.004, H + 1.0), (v[0] - 0.08, 0.02, 1.1), 3)
    mm.box((vx, vy - v[1] / 2 - 0.006, H + 1.68), (v[0] - 0.08, 0.02, 0.22), 5)
    g = RESEARCH["station"]["passage_gate"]
    for gx in (x0 + 1.4, x1 - 1.2):
        gy = y0 + 1.7
        mm.box((gx, gy, H + 0.35), (0.16, 0.16, 0.7), 0)
        mm.box((gx, gy, H + 0.78), (g[0], g[1], 0.18), 0, (0.35, 0, 0))
        mm.box((gx, gy - 0.02, H + 0.84), (g[0] - 0.05, g[1] - 0.05, 0.06), 5, (0.35, 0, 0))
        mm.box((gx, gy, H + 0.62), (g[0] + 0.05, g[1] + 0.05, 0.62), 6)
    mm.build("Station_Furniture", c, [MAT["MAT_Steel_Grey"], MAT["MAT_Orange_Frame"], MAT["MAT_Mirror_Curve"], MAT["MAT_Black"],
                                      MAT["MAT_Vending_White"], MAT["MAT_Vending_Blue"], MAT["MAT_Cover_PVC"]], bevel=0.004)
    return plat


def build_station_extras():
    """Refs: Street View (canopy end walls, vending machines, cemetery behind), Commons entrance photo (corrugated gable + mint sign board,
    cream timber hut, rubble-stone wall with weep holes)."""
    log("station extras: gable ends + signs, vending machines, stone wall, hut, cemetery ...")
    P = CFG["platform"]
    x0, x1, y0, H = P["x0"], P["x1"], P["y0"], P["height"]
    y1 = y0 + P["width"]
    c = coll("P2_Station")
    rng = random.Random(33)
    xa, xb = x0 - 0.6, x1 + 0.6
    yc, yf = y1 - 0.35, y0 + 0.55
    zb, zf = H + 2.85, H + 2.45

    gp, sg_ = MB(), MB()                                                  # gable end panels (corrugated) + mint sign boards
    for x_, d_ in ((xa + 0.02, -1), (xb - 0.02, 1)):
        gp.box((x_, (yc + yf) / 2, (zb + zf) / 2 + 0.05), (0.05, yc - yf + 0.3, 0.75), 0)
        sg_.box((x_ + d_ * 0.045, (yc + yf) / 2, (zb + zf) / 2 + 0.05), (0.03, 1.95, 0.58), 0)
    gp.build("Canopy_Gable_Panels", c, [MAT["MAT_Siding_Corr"]])
    sg_.build("Station_Sign_Boards_Mint", c, [MAT["MAT_Sign_Mint"]])
    for x_, d_, rot in ((xa + 0.02, -1, (math.pi / 2, 0, -math.pi / 2)), (xb - 0.02, 1, (math.pi / 2, 0, math.pi / 2))):
        xt = x_ + d_ * 0.065
        ym, zm_ = (yc + yf) / 2, (zb + zf) / 2 + 0.05
        text_obj("Gable_Name", "鎌倉高校前駅", (xt, ym, zm_ - 0.02), rot, 0.21, MAT["MAT_Sign_Black"], c)
        text_obj("Gable_Op", "江ノ島電鉄", (xt, ym - d_ * 0.0, zm_ + 0.20), rot, 0.09, MAT["MAT_Sign_Black"], c)
        text_obj("Gable_En", "KAMAKURAKOKOMAE-STATION", (xt, ym, zm_ - 0.22), rot, 0.06, MAT["MAT_Sign_Black"], c, cjk=False)

    vm = MB()                                                             # two more vending machines beside the existing white one (0 red, 1 blue, 2 glass, 3 lamp)
    for vx, mat in ((-14.05, 1), (-12.35, 0)):
        vy = y1 - 0.38
        vm.box((vx, vy, H + 0.925), (0.78, 0.65, 1.85), mat)
        vm.box((vx, vy - 0.331, H + 0.95), (0.70, 0.02, 1.15), 2)
        vm.box((vx, vy - 0.335, H + 1.68), (0.70, 0.02, 0.22), 3)
    vm.build("Station_Vending_Extra", c, [MAT["MAT_Vending_Red"], MAT["MAT_Vending_Blue"], MAT["MAT_Black"], MAT["MAT_Lamp_Warm"]], bevel=0.004)

    # ---- rubble-stone wall behind the platform (with weep holes) -- only where no other structure stands
    wx0, wx1 = x0 - 1.5, -10.6
    wm = MB()                                                             # 0 stone, 1 concrete coping, 2 pipe
    wm.box(((wx0 + wx1) / 2, 4.45, 0.95), (wx1 - wx0, 0.85, 3.1), 0)
    wm.box(((wx0 + wx1) / 2, 4.42, 2.53), (wx1 - wx0, 1.02, 0.10), 1)
    x = wx0 + 2.0
    while x < wx1 - 1.0:
        wm.cyl((x, 4.04, H + 0.55), (x, 3.95, H + 0.55), 0.035, 0.035, 8, 2, True, False)
        x += 3.0
    wm.build("Station_Stone_Wall", c, [MAT["MAT_Stone_Light"], MAT["MAT_Concrete"], MAT["MAT_White_Panel"]])

    # ---- cream timber hut (office / toilet) behind the platform
    hx, hy, hw, hd = -23.0, 6.0, 4.0, 2.4
    hz = terrain_z(hx, hy) - 0.05
    hb = MB()                                                             # 0 wall, 1 roof, 2 door (dark wood), 3 window glass, 4 concrete base
    hb.box((hx, hy, hz + 1.3), (hw, hd, 2.6), 0)
    hb.box((hx, hy, hz - 0.15), (hw + 0.2, hd + 0.2, 0.5), 4)
    hb.box((hx, hy - 0.05, hz + 2.7), (hw + 0.5, hd + 0.5, 0.08), 1, (0.09, 0, 0))               # lean-to roof, low pitch
    hb.box((hx - 1.2, hy - hd / 2 - 0.02, hz + 1.05), (0.85, 0.05, 2.0), 2)                     # door
    hb.box((hx + 0.7, hy - hd / 2 - 0.02, hz + 1.5), (1.1, 0.05, 0.85), 3)                      # window
    hb.box((hx + 0.7, hy - hd / 2 - 0.045, hz + 1.5), (1.24, 0.02, 0.98), 4)                    # sill / frame
    hb.cyl((hx + hw / 2 + 0.05, hy - hd / 2 + 0.05, hz + 2.6), (hx + hw / 2 + 0.05, hy - hd / 2 + 0.05, hz), 0.035, 0.035, 8, 4, False, True)   # down-pipe
    hb.build("Station_Hut", c, [MAT["MAT_Hut_Wall"], MAT["MAT_Roof_Hut"], MAT["MAT_Wood_Dark"], MAT["MAT_Glass_Clear"], MAT["MAT_Concrete"]], bevel=0.006)

    # ---- cemetery on the slope behind the station (seen from the road in the Street View photos)
    gs, sk = MB(), MB()                                                   # 0 granite, 1 wooden sotoba
    for row_y in (7.6, 9.2, 10.8, 12.4, 14.0):
        x = -54.0 + rng.uniform(0, 1.2)
        while x < -13.0:
            if abs(x - hx) < 3.0 and row_y < 8.6:
                x += 2.0
                continue
            y = row_y + rng.uniform(-0.25, 0.25)
            z = terrain_z(x, y)
            tilt = (rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05), rng.uniform(-0.3, 0.3))
            gs.box((x, y, z + 0.07), (0.46, 0.36, 0.14), 0, tilt)
            gs.box((x, y, z + 0.14 + 0.24 + rng.uniform(0.0, 0.08)), (0.22, 0.17, 0.48 + rng.uniform(0.0, 0.14)), 0, tilt)
            if rng.random() < 0.34:
                sk.box((x + 0.40, y, z + 0.55), (0.04, 0.01, 1.05), 1, (0, rng.uniform(-0.1, 0.1), 0))
            x += rng.uniform(0.75, 1.3)
    gs.build("Cemetery_Gravestones", c, [MAT["MAT_Granite"]], bevel=0.004)
    sk.build("Cemetery_Sotoba", c, [MAT["MAT_Wood_Bench"]])


# ---------------------------------------------------------------------------------------------------- level crossing
def tactile_rows(base, dome, x0, x1, y, z):
    """Yellow warning tactile blocks (300 mm, 5x5 domes) in a row along X."""
    n = int(round((x1 - x0) / 0.30))
    for i in range(n):
        cx = x0 + 0.15 + 0.30 * i
        base.box((cx, y, z + 0.008), (0.298, 0.298, 0.016), 0)
        for a in range(5):
            for b in range(5):
                px, py = cx - 0.108 + a * 0.054, y - 0.108 + b * 0.054
                dome.cyl((px, py, z + 0.016), (px, py, z + 0.024), 0.0115, 0.008, 6, 0, True, False)


def build_crossing():
    log("level crossing equipment ...")
    c = coll("P3_Crossing")
    R = RESEARCH["crossing"]
    ch = CFG["crossing_half"]
    active = CFG["crossing_active"]
    # ---- rubber boards with ribs (between and outside the rails)
    pan = MB()
    zt = -0.006

    def slab(xa, xb, ya, yb):
        pan.box(((xa + xb) / 2, (ya + yb) / 2, zt - 0.07), (xb - xa, yb - ya, 0.14), 0)
        n = int((xb - xa) / 0.06)
        for k in range(n):
            pan.box((xa + 0.03 + 0.06 * k, (ya + yb) / 2, zt + 0.004), (0.022, yb - ya - 0.04, 0.008), 0)

    slab(-ch, ch, -0.4685, 0.4685)
    slab(-ch, ch, 0.6635, 1.5135)
    slab(-ch, ch, -1.5135, -0.6635)
    pan.build("Crossing_Rubber_Boards", c, [MAT["MAT_Rubber_Crossing"]])

    # ---- yellow tactile blocks on the road approaches
    tb, td = MB(), MB()
    for sy in (-1, 1):
        for yy in (2.0, 2.3):
            tactile_rows(tb, td, -ch, ch, sy * yy, hill_road_z(0, sy * yy) + 0.002)
    tb.build("Tactile_Base", c, [MAT["MAT_Tactile_Yellow"]])
    td.build("Tactile_Domes", c, [MAT["MAT_Tactile_Yellow"]])

    # ---- alarm masts.  Reference photos (Wikimedia Commons, "Level crossing near the Kamakura-Koko-Mae Station" / Enoden 1000
    # series at the crossing): yellow-black banded pole, cross mark on top, TWO RED LAMPS STACKED VERTICALLY (each with a hood,
    # facing both road directions), speaker/control boxes, striped gate machine box next to the pole, thin striped arm.
    fix, pole, gate, lon, loff = MB(), MB(), MB(), MB(), MB()          # fix: 0 grey, 1 concrete, 2 black, 3 white
    for (sx, sy) in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        px, py = sx * 3.6, sy * 2.75
        pole.cyl((px, py, -0.10), (px, py, 3.30), 0.062, 0.052, 14, 0)
        fix.box((px, py, 0.02), (0.34, 0.34, 0.24), 1)                                  # concrete collar
        for f in (1, -1):                                                               # lamps face both road directions
            for zl, on in ((2.88, active), (2.48, False)):                               # upper lamp lit, lower dark (alternate flash)
                fix.cyl((px, py + f * 0.05, zl), (px, py + f * 0.20, zl), 0.135, 0.135, 22, 2)
                (lon if on else loff).cyl((px, py + f * 0.20, zl), (px, py + f * 0.212, zl), 0.112, 0.112, 22, 0)
                fix.box((px, py + f * 0.16, zl + 0.155), (0.31, 0.22, 0.012), 2, (-0.30 * f, 0, 0))     # hood
        fix.box((px, py, 2.05), (0.32, 0.22, 0.26), 0)                                  # speaker box (kan-kan)
        fix.box((px, py + sy * 0.116, 2.05), (0.24, 0.012, 0.18), 2)
        fix.box((px, py - sy * 0.17, 1.45), (0.28, 0.16, 0.34), 3)                       # small white relay case
        gy = sy * 2.22                                                                   # gate machine: striped box beside the mast
        gate.box((px, gy, 0.52), (0.36, 0.46, 1.04), 0)
        fix.box((px, gy, 1.075), (0.38, 0.48, 0.05), 2)
        fix.box((px, gy + sy * 0.235, 0.62), (0.22, 0.012, 0.20), 2)
    cx, cy = 4.55, 3.55
    cb = R["cabinet"]
    fix.box((cx, cy, cb[2] / 2), (cb[0], cb[1], cb[2]), 0)                                # signal control cabinet (unit not published)
    fix.box((cx, cy - 0.178, cb[2] / 2), (cb[0] - 0.06, 0.006, cb[2] - 0.08), 2)
    fix.build("Crossing_Masts_Fittings", c, [MAT["MAT_Signal_Grey"], MAT["MAT_Concrete"], MAT["MAT_Black"], MAT["MAT_Pole_White"]],
              bevel=0.004)
    pole.build("Crossing_Alarm_Poles", c, [MAT["MAT_Striped_Z"]])
    gate.build("Crossing_Gate_Boxes", c, [MAT["MAT_Striped_Z"]], bevel=0.005)
    lon.build("Alarm_Lamps_ON", c, [MAT["MAT_Alarm_Lamp_On"]])
    loff.build("Alarm_Lamps_OFF", c, [MAT["MAT_Alarm_Lamp_Off"]])

    # ---- striped cross marks and barrier arms (own objects, so the stripe shader follows the local X axis)
    yel = MAT["MAT_Yellow_Striped"]
    for (sx, sy) in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        px, py = sx * 3.6, sy * 2.75
        for k, ang in enumerate((math.pi / 4, -math.pi / 4)):
            def mk():
                m = MB()
                m.box((0, 0, 0), (0.98, 0.028, 0.15), 0)
                return m
            shared_object("cross", "CrossMark", mk, (px, py + sy * 0.028 * (k * 2 - 1) * 0.5, 3.47), (0, ang, 0), c, [yel])
        cm = MB()
        cm.box((px, py, 3.47), (0.19, 0.05, 0.19), 0, (0, math.pi / 4, 0))
        cm.build("CrossMark_Center", c, [MAT["MAT_Black"]])

        L_ = R["arm_length"]

        def mk_arm():
            m = MB()
            m.box((L_ / 2, 0, 0), (L_, 0.030, 0.052), 0)                                # thin striped bar (refs)
            return m

        gx = px - sx * 0.19
        gy = sy * 2.22
        rz = 0.0 if sx < 0 else math.pi
        ry = 0.0 if active else -1.40
        arm = shared_object("arm", "Barrier_Arm", mk_arm, (gx, gy, R["arm_height"]), (0, ry, rz), c, [yel])
        tip = MB()
        tip.box((L_ - 0.09, 0, 0), (0.18, 0.034, 0.056), 0)
        tip_ob = tip.build("Barrier_Reflector", c, [MAT["MAT_Reflector_Red"]])
        tip_ob.parent = arm

    # ---- road signs: railway-crossing warning + caution plate; white pole with pedestrian-crossing (blue triangle) and
    #      no-stopping (blue disc, red X) signs as in the reference photos
    sg = MB()                                        # 0 yellow, 1 black, 2 white, 3 grey, 4 blue, 5 red
    for (x_, y_, d_) in ((-4.0, -4.0, -1), (4.0, 9.5, 1)):
        sg.cyl((x_, y_, -0.1), (x_, y_, 2.85), 0.04, 0.04, 8, 3)
        sg.box((x_, y_ + d_ * 0.035, 2.35), (1.0, 0.02, 1.0), 1, (0, math.pi / 4, 0))
        sg.box((x_, y_ + d_ * 0.048, 2.35), (0.88, 0.02, 0.88), 0, (0, math.pi / 4, 0))
        sg.box((x_, y_ + d_ * 0.064, 2.32), (0.52, 0.02, 0.20), 1)                       # train symbol: body + wheels
        sg.box((x_, y_ + d_ * 0.064, 2.52), (0.32, 0.02, 0.14), 1)
        for dx in (-0.16, 0.16):
            sg.cyl((x_ + dx, y_ + d_ * 0.05, 2.19), (x_ + dx, y_ + d_ * 0.075, 2.19), 0.055, 0.055, 10, 1)
        sg.box((x_, y_ + d_ * 0.03, 1.76), (0.66, 0.02, 0.22), 2)
    px_, py_, d_ = -4.1, 5.6, 1                       # white pole beside the road (mounts face the traffic coming down the hill)
    sg.cyl((px_, py_, -0.1), (px_, py_, 3.05), 0.038, 0.038, 10, 2)
    cz, s_ = 2.55, 0.90                               # pedestrian-crossing sign: white rim, blue field, white figure
    for sz, m_, off in ((s_, 2, 0.030), (s_ * 0.84, 4, 0.036)):
        h_ = sz * 0.866
        v = sg.verts([(px_, py_ + d_ * off, cz + h_ * 2 / 3), (px_ - sz / 2, py_ + d_ * off, cz - h_ / 3), (px_ + sz / 2, py_ + d_ * off, cz - h_ / 3)])
        sg.face((v, v + 1, v + 2), m_)
    v2 = sg.verts([(px_, py_ + d_ * 0.024, cz + s_ * 0.866 * 2 / 3), (px_ - s_ / 2, py_ + d_ * 0.024, cz - s_ * 0.866 / 3), (px_ + s_ / 2, py_ + d_ * 0.024, cz - s_ * 0.866 / 3)])
    sg.face((v2, v2 + 2, v2 + 1), 3)
    fy = py_ + d_ * 0.040
    sg.sphere((px_ + 0.02, fy, cz + 0.16), 0.045, 8, 5, 2)                               # white figure
    sg.box((px_ + 0.02, fy, cz + 0.03), (0.07, 0.008, 0.20), 2, (0, -0.15, 0))
    sg.box((px_ - 0.02, fy, cz - 0.17), (0.05, 0.008, 0.20), 2, (0, 0.35, 0))
    sg.box((px_ + 0.08, fy, cz - 0.17), (0.05, 0.008, 0.20), 2, (0, -0.25, 0))
    sg.box((px_ - 0.06, fy, cz + 0.05), (0.14, 0.008, 0.04), 2, (0, 0.5, 0))
    sg.box((px_ + 0.10, fy, cz + 0.05), (0.14, 0.008, 0.04), 2, (0, -0.6, 0))
    zc_ = 1.72                                        # no stopping: red rim, blue disc, red X
    sg.cyl((px_, py_ + d_ * 0.030, zc_), (px_, py_ + d_ * 0.042, zc_), 0.30, 0.30, 32, 5)
    sg.cyl((px_, py_ + d_ * 0.042, zc_), (px_, py_ + d_ * 0.048, zc_), 0.255, 0.255, 32, 4)
    for ang in (math.pi / 4, -math.pi / 4):
        sg.box((px_, py_ + d_ * 0.052, zc_), (0.46, 0.008, 0.055), 5, (0, ang, 0))
    sg.build("Signs_Crossing_Warning", c, [MAT["MAT_Sign_Yellow"], MAT["MAT_Sign_Black"], MAT["MAT_Sign_White"], MAT["MAT_Steel_Grey"],
                                           MAT["MAT_Sign_Blue"], MAT["MAT_Sign_Red"]])
    text_obj("Sign_Caution1", "注意", (-4.0, -4.0 - 0.043, 1.76), facing(-1), 0.14, MAT["MAT_Sign_Black"], c)
    text_obj("Sign_Caution2", "注意", (4.0, 9.5 + 0.043, 1.76), facing(1), 0.14, MAT["MAT_Sign_Black"], c)

    cmx, cmy, cmz = 4.4, -4.6, 3.2                   # round curve mirror (wide-angle mirror), orange pole as in the reference
    mr = MB()                                        # 0 orange pole/rim, 1 mirror, 2 white plate
    mr.cyl((cmx, cmy, -0.1), (cmx, cmy, cmz + 0.5), 0.045, 0.04, 8, 0)
    mr.cyl((cmx, cmy - 0.03, cmz), (cmx, cmy + 0.05, cmz), 0.44, 0.44, 28, 0)
    mr.sphere((cmx, cmy + 0.05, cmz), 0.40, 24, 12, 1, True, (1, 0.16, 1))
    mr.box((cmx, cmy + 0.02, cmz - 0.62), (0.16, 0.02, 0.32), 2)
    mr.build("Curve_Mirror", c, [MAT["MAT_Orange_Frame"], MAT["MAT_Mirror_Curve"], MAT["MAT_White_Panel"]])
    return c


def build_guardrails(path):
    """Zinc-plated W-beam guard rails (rust bleed) along the hill road."""
    gr = MB()
    samples = [p for p in densify(path, 2.0) if 7.0 <= p[1] <= 34.0]
    for side in (1, -1):
        prev = None
        for k, (x, y) in enumerate(samples):
            a = samples[max(k - 1, 0)]
            b = samples[min(k + 1, len(samples) - 1)]
            t = Vector((b[0] - a[0], b[1] - a[1], 0.0)).normalized()
            n = Vector((-t.y, t.x, 0.0))
            hw = road_width(y) / 2.0 + 0.55
            p = (x + n.x * side * hw, y + n.y * side * hw, terrain_z(x + n.x * side * hw, y + n.y * side * hw) + 0.03)
            gr.box((p[0], p[1], p[2] + 0.35), (0.10, 0.10, 0.70), 0)
            if prev is not None:
                gr.cyl((prev[0], prev[1], prev[2] + 0.62), (p[0], p[1], p[2] + 0.62), 0.09, 0.09, 4, 0, False, False)
            prev = p
    gr.build("Guardrails_Hill_Road", coll("P3_Crossing"), [MAT["MAT_Steel_Galv"]])


# ---------------------------------------------------------------------------------------------------- poles + wires
def path_at_y(path, y):
    pts = densify(path, 1.0)
    best = min(range(len(pts)), key=lambda i: abs(pts[i][1] - y))
    a, b = pts[max(best - 1, 0)], pts[min(best + 1, len(pts) - 1)]
    t = Vector((b[0] - a[0], b[1] - a[1], 0.0)).normalized()
    return pts[best], t


def build_poles(path):
    """Utility poles (concrete, ~10.6 m) laid out as in the Street View photos: a big pole at the north-west corner of the crossing with
    three signal cabinets at its base and a thick feeder cable across the hill road; poles every ~35 m on the north side of the track
    (against the stone wall) and every ~25-30 m along the hill road.  8 conductors per span: 3 HV + 3 LV + 2 telecom."""
    log("utility poles + wires ...")
    c = coll("P2_Poles")
    mb = MB()      # 0 concrete, 1 galv steel, 2 insulator, 3 transformer, 4 warm lamp, 5 white, 6 brown cabinet, 7 beige cabinet, 8 black
    UP = Vector((0, 0, 1))

    def pole(px, py, n, H=10.6, lamp=False, xfmr=False):
        z0 = terrain_z(px, py) - 0.35
        zt = z0 + H
        R = Euler((0, 0, math.atan2(n.y, n.x)), "XYZ")
        mb.cyl((px, py, z0), (px, py, zt), 0.165, 0.105, 12, 0)
        mb.box((px, py, zt - 0.55), (1.9, 0.07, 0.08), 1, R)                              # HV cross arm
        mb.box((px, py, zt - 2.0), (1.4, 0.06, 0.07), 1, R)                               # LV cross arm
        for off_, zi in ((-0.8, zt - 0.55), (0.0, zt - 0.55), (0.8, zt - 0.55), (-0.55, zt - 2.0), (0.0, zt - 2.0), (0.55, zt - 2.0)):
            q = Vector((px, py, zi)) + Vector((n.x, n.y, 0)) * off_
            mb.cyl((q.x, q.y, q.z), (q.x, q.y, q.z + 0.17), 0.045, 0.03, 8, 2)            # pin insulators
        for off_ in (-0.05, 0.05):                                                          # telecom clamps
            q = Vector((px, py, zt - 3.3)) + Vector((n.x, n.y, 0)) * off_
            mb.cyl((q.x - 0.03, q.y, q.z), (q.x + 0.03, q.y, q.z), 0.02, 0.02, 6, 2)
        perp = Vector((-n.y, n.x, 0.0))
        for k in range(11):                                                                  # step bolts
            d = n if k % 2 else perp
            zz = z0 + 2.6 + 0.42 * k
            mb.cyl((px - d.x * 0.24, py - d.y * 0.24, zz), (px + d.x * 0.24, py + d.y * 0.24, zz), 0.011, 0.011, 4, 1)
        mb.box((px, py - 0.17, z0 + 3.2), (0.16, 0.02, 0.10), 5, R)                       # ID plate
        mb.cyl((px + 0.19, py, z0), (px + 0.19, py, z0 + 8.4), 0.028, 0.028, 6, 1)        # cable riser conduit
        if xfmr:
            q = Vector((px, py, 0)) - Vector((n.x, n.y, 0)) * 0.36
            mb.cyl((q.x, q.y, zt - 3.9), (q.x, q.y, zt - 3.1), 0.22, 0.22, 14, 3)
            for dx in (-0.09, 0.0, 0.09):
                mb.cyl((q.x + dx, q.y, zt - 3.1), (q.x + dx, q.y, zt - 2.85), 0.03, 0.02, 6, 2)
        if lamp:
            d = Vector((-n.x, -n.y, 0)) * 1.9
            p1 = Vector((px, py, zt - 4.6)) + d + Vector((0, 0, 0.5))
            mb.cyl((px, py, zt - 4.6), (p1.x, p1.y, p1.z), 0.03, 0.03, 6, 1)
            mb.box((p1.x, p1.y, p1.z - 0.07), (0.50, 0.22, 0.09), 4, R)
            WEB_LAMPS.append((p1.x, p1.y, p1.z - 0.2))
            mb.box((p1.x, p1.y, p1.z), (0.54, 0.26, 0.05), 5, R)
        return {"pos": Vector((px, py, zt)), "n": Vector((n.x, n.y, 0.0)), "z0": z0}

    n_track = Vector((0.0, 1.0, 0.0))
    # ---- the big pole at the NW corner of the crossing (+ hill-road cross arm, meter/terminal boxes, cabinets)
    P0 = pole(-4.6, 3.6, n_track, 11.0, xfmr=True)
    z0, zt = P0["z0"], P0["pos"].z
    mb.box((-4.6, 3.6, zt - 1.5), (1.7, 0.07, 0.08), 1, Euler((0, 0, 0), "XYZ"))                   # cross arm for the hill-road branch
    for off_ in (-0.7, 0.0, 0.7):
        mb.cyl((-4.6 + off_, 3.6, zt - 1.5), (-4.6 + off_, 3.6, zt - 1.33), 0.045, 0.03, 8, 2)
    mb.box((-4.6, 3.42, z0 + 2.5), (0.34, 0.16, 0.46), 0)                                          # meter box (grey)
    mb.box((-4.6, 3.42, z0 + 5.0), (0.26, 0.14, 0.36), 5)                                          # telecom terminal box
    for (cx, cy, sx_, sy_, sz_, mat) in ((-6.9, 4.15, 0.95, 0.55, 1.25, 6), (-8.0, 4.2, 0.85, 0.50, 1.15, 7), (-9.05, 4.05, 0.45, 0.35, 0.70, 6)):
        zc_ = terrain_z(cx, cy) - 0.05
        mb.box((cx, cy, zc_ + sz_ / 2), (sx_, sy_, sz_), mat)                                       # signal control cabinets
        mb.box((cx, cy - sy_ / 2 - 0.006, zc_ + sz_ / 2), (sx_ - 0.12, 0.012, sz_ - 0.14), 8)      # door seam / vent
        mb.box((cx, cy, zc_ + sz_ + 0.03), (sx_ + 0.06, sy_ + 0.06, 0.06), 1)                       # hood

    # ---- poles along the hill road
    hill = []
    for (py, side, kw) in ((30.0, -1, dict(xfmr=True)), (54.0, 1, dict(lamp=True)), (70.0, -1, {})):
        (x, y), t = path_at_y(path, py)
        n = Vector((-t.y, t.x, 0.0))
        off = road_width(y) / 2 + 1.15
        hill.append(pole(x + n.x * side * off, y + n.y * side * off, n, **kw))
    # ---- poles on the north side of the track, in front of the stone wall (east / west of the crossing)
    east = [pole(x, 2.8, n_track, lamp=(x == 84.0)) for x in (8.5, 46.0, 84.0, 122.0, 160.0, 198.0)]
    west = [pole(-36.0, 4.6, n_track)] + [pole(x, 2.8, n_track) for x in (-68.0, -106.0, -144.0, -182.0)]
    mb.build("Utility_Poles", c, [MAT["MAT_Concrete_Pole"], MAT["MAT_Steel_Galv"], MAT["MAT_Insulator"], MAT["MAT_Transformer"],
                                  MAT["MAT_Lamp_Warm"], MAT["MAT_White_Panel"], MAT["MAT_Cabinet_Brown"], MAT["MAT_Cabinet_Beige"],
                                  MAT["MAT_Black"]], bevel=0.004)

    wm = MAT["MAT_Wire"]
    layout = [(-0.8, -0.55 + 0.17, 0.012), (0.0, -0.55 + 0.17, 0.012), (0.8, -0.55 + 0.17, 0.012),
              (-0.55, -2.0 + 0.17, 0.010), (0.0, -2.0 + 0.17, 0.010), (0.55, -2.0 + 0.17, 0.010),
              (-0.05, -3.3, 0.008), (0.05, -3.3, 0.008)]

    def chain(poles, first_n=None, first_dz=0.0, name="Wire"):
        for i in range(len(poles) - 1):
            a_, b_ = poles[i], poles[i + 1]
            na = first_n if (i == 0 and first_n is not None) else a_["n"]
            dza = first_dz if i == 0 else 0.0
            span = (b_["pos"] - a_["pos"]).length
            for off, dz, rad in layout:
                a = Vector((a_["pos"].x + na.x * off, a_["pos"].y + na.y * off, a_["pos"].z + dz + dza))
                b = Vector((b_["pos"].x + b_["n"].x * off, b_["pos"].y + b_["n"].y * off, b_["pos"].z + dz))
                wire("%s_%d" % (name, i), catenary(a, b, span * 0.022, 16), rad, wm, c)

    chain([P0] + hill, first_n=Vector((1.0, 0.0, 0.0)), first_dz=-0.95, name="WireHill")
    chain([P0] + east, name="WireEast")
    chain(list(reversed(west)) + [P0], name="WireWest")
    # thick black feeder cable across the hill road (seen in the Street View shot at the crossing)
    a = Vector((-4.6, 3.6, zt - 2.9))
    b = Vector((6.6, 3.9, zt - 3.2))
    wire("Feeder_Across_Road", catenary(a, b, 0.42, 24), 0.024, MAT["MAT_Wire_Feeder"], c)
    return [P0] + hill + east + west


def build_service_drops(poles):
    """Service wires from the LV cross arm / telecom clamp of the nearest pole to a bracket under the eaves of each house, with the wall
    bracket, conduit and meter box (Street View sv_h01 / sv_h02: every house hangs on the pole wires)."""
    if not HOUSES or not poles:
        return
    log("service drops ...")
    c = coll("P2_Poles")
    rng = random.Random(21)
    wm = MAT["MAT_Wire"]
    dr = MB()                                   # 0 insulator, 1 white box, 2 steel
    cand = []
    for h in HOUSES:
        cx, cy = h["c"]
        best = None
        for p in poles:
            d = math.hypot(p["pos"].x - cx, p["pos"].y - cy)
            if best is None or d < best[0]:
                best = (d, p)
        if best is not None and best[0] <= 44.0:
            cand.append((best[0], h, best[1]))
    cand.sort(key=lambda t: t[0])
    per, n = {}, 0
    for d, h, p in cand:
        if per.get(id(p), 0) >= 9:
            continue
        px, py = p["pos"].x, p["pos"].y
        pick = None
        for ed in h["edges"]:
            if ed["L"] < 1.6:
                continue
            t = clamp((px - ed["a"][0]) * ed["d"][0] + (py - ed["a"][1]) * ed["d"][1], 0.3, ed["L"] - 0.3)
            wx, wy = _ept(ed, t, 0.0)
            if (px - wx) * ed["n"][0] + (py - wy) * ed["n"][1] <= 0.0:                 # wall faces away from the pole
                continue
            dd = math.hypot(wx - px, wy - py)
            if pick is None or dd < pick[0]:
                pick = (dd, ed, t, wx, wy)
        if pick is None:
            continue
        per[id(p)] = per.get(id(p), 0) + 1
        _, ed, t, wx, wy = pick
        nx, ny = ed["n"]
        z_att = h["top"] - (0.5 if h["pitched"] else 0.45)
        tip = Vector((wx + nx * 0.30, wy + ny * 0.30, z_att))
        dr.cyl((wx + nx * 0.02, wy + ny * 0.02, z_att + 0.02), (tip.x, tip.y, z_att + 0.02), 0.02, 0.02, 6, 2, True, False)      # bracket
        dr.cyl((tip.x, tip.y, z_att + 0.06), (tip.x, tip.y, z_att - 0.06), 0.03, 0.03, 8, 0, True, False)                    # insulator
        zg = max(terrain_z(wx, wy), h["zmin"])
        zm = zg + 1.5
        dr.cyl((wx + nx * 0.045, wy + ny * 0.045, z_att), (wx + nx * 0.045, wy + ny * 0.045, zm + 0.36), 0.018, 0.018, 6, 2, False, False)   # conduit
        dr.box((wx + nx * 0.07, wy + ny * 0.07, zm), (0.26, 0.12, 0.36), 1, (0.0, 0.0, ed["ang"]))                              # meter box
        n_p = p["n"]
        side = (tip.x - px) * n_p.x + (tip.y - py) * n_p.y
        off = 0.55 if side > 1.5 else (-0.55 if side < -1.5 else 0.0)
        a = Vector((px + n_p.x * off, py + n_p.y * off, p["pos"].z - 2.0 + 0.27))
        span = (tip - a).length
        wire("Drop_%d" % n, catenary(a, tip, 0.02 * span + 0.08, 12), 0.011, wm, c)
        if rng.random() < 0.7:
            a2 = Vector((px + n_p.x * 0.05, py + n_p.y * 0.05, p["pos"].z - 3.3))
            wire("DropTel_%d" % n, catenary(a2, tip + Vector((0.0, 0.0, -0.32)), 0.02 * span + 0.06, 10), 0.006, wm, c)
        n += 1
    dr.build("Service_Drop_Fittings", c, [MAT["MAT_Insulator"], MAT["MAT_White_Panel"], MAT["MAT_Steel_Grey"]])
    log("  %d service drops" % n)


def build_catenary():
    """DC 600 V overhead line.  Supports: slim steel masts with a cantilever arm on the road side (south) and, near the crossing, brackets
    on the concrete utility poles of the north side (Street View)."""
    log("overhead line (DC 600 V catenary) ...")
    c = coll("P2_Catenary")
    zc, zm = RESEARCH["train_1000"]["pantograph_working_height"], 5.6
    supports = [(-105.0, None), (-73.0, None), (-41.0, None), (-4.6, 3.6), (8.5, 2.8), (41.0, None), (73.0, None), (105.0, None)]
    mb = MB()                                        # 0 grey steel, 1 concrete, 2 insulator
    for x, yp in supports:
        if yp is None:                               # slim steel mast on the road side
            mb.box((x, -2.75, 3.25), (0.20, 0.20, 6.7), 0)
            mb.box((x, -2.75, -0.05), (0.60, 0.60, 0.40), 1)
            mb.box((x, -1.2, 5.95), (0.10, 3.1, 0.10), 0)                                  # cantilever arm
            mb.cyl((x, -2.75, 4.7), (x, -0.1, 5.9), 0.022, 0.022, 6, 0)                    # diagonal brace
        else:                                        # bracket on the north-side utility pole
            L = yp + 0.1
            mb.box((x, (yp - 0.1) / 2 + 0.0, 5.95), (0.10, L, 0.10), 0)
            mb.cyl((x, yp - 0.1, 4.75), (x, 0.3, 5.9), 0.022, 0.022, 6, 0)
            mb.box((x, yp - 0.12, 5.95), (0.34, 0.16, 0.16), 0)                            # clamp on the pole
        for yy in (-0.2, 0.0):
            mb.cyl((x, yy, 5.9), (x, yy, 5.66), 0.045, 0.03, 8, 2)
    mb.build("Catenary_Supports", c, [MAT["MAT_Steel_Grey"], MAT["MAT_Concrete"], MAT["MAT_Insulator"]])
    wm = MAT["MAT_Wire"]
    xs = [-125.0] + [x for x, _ in supports] + [125.0]
    cw = []
    for i, x in enumerate(xs):
        zig = 0.15 if i % 2 == 0 else -0.15                                                # stagger of the trolley wire
        cw.append((x, zig, zc))
    for a, b in zip(cw, cw[1:]):
        wire("TrolleyWire", catenary(a, b, 0.05, 10), 0.0065, wm, c)
        m0 = (a[0], 0.0, zm)
        m1 = (b[0], 0.0, zm)
        wire("MessengerWire", catenary(m0, m1, 0.6, 24), 0.0055, wm, c)
        n_d = int((b[0] - a[0]) / 4.5)
        for k in range(1, n_d):
            t = k / n_d
            x = lerp(a[0], b[0], t)
            zt_ = zm - 0.6 * 4 * t * (1 - t)
            wire("Dropper", [(x, 0.0, zt_), (x, lerp(a[1], b[1], t), zc - 0.05 * 4 * t * (1 - t))], 0.0025, wm, c)


def build_streetlights():
    mb = MB()
    for x in (-84.0, -46.0, 27.0, 66.0):
        z0 = CFG["r134"]["walk_z"] - 0.05
        mb.cyl((x, -15.6, z0), (x, -15.6, z0 + 7.6), 0.085, 0.055, 10, 0)
        mb.cyl((x, -15.6, z0 + 7.5), (x, -13.9, z0 + 8.05), 0.03, 0.03, 6, 0)
        mb.box((x, -13.9, z0 + 7.98), (0.62, 0.26, 0.07), 1)
        WEB_LAMPS.append((x, -13.9, z0 + 7.85))
        mb.box((x, -13.9, z0 + 7.93), (0.56, 0.22, 0.03), 2)
    mb.build("Streetlights_R134", coll("P2_Poles"), [MAT["MAT_Steel_Grey"], MAT["MAT_White_Panel"], MAT["MAT_Lamp_Warm"]])


# =====================================================================================================================
#  Phase 3  --  Enoden 1000 series, 2-car set (dimensions: RESEARCH["train_1000"])
# =====================================================================================================================
M_GREEN, M_CREAM, M_DARK, M_GLASS, M_METAL, M_ROOF, M_BELLOWS, M_HEAD, M_TAIL, M_BLACK, M_INSUL, M_SAFETY = range(12)


def car_mb(pan_raised):
    """One car in local coordinates: centre at x=0, cab end at +x, floor 1.07 m above the rail head.
    Livery from the reference photos: dark-green roof and upper rail, cream window band, dark-green skirt with a thin cream line.
    Returns (mb, wheels_mb): the wheel *discs* are built into a separate MB (own object once exported) so
    src/train.js can spin them independently of the body — the bogie frame/axles stay in `mb` since a thin rod or
    a plain box is rotationally symmetric at this scale anyway, not worth the extra object for zero visible change."""
    T = RESEARCH["train_1000"]
    Lc, W = T["car_length"], T["body_width"]
    hl = Lc / 2.0
    NOSE = 0.45                                                                     # cab nose: plan-view taper + raked windshield
    mb = MB()
    wh = MB()
    prof_ = [(-1.20, 0.95), (1.20, 0.95), (1.20, 1.85), (1.182, 2.95), (1.17, 3.02), (0.98, 3.26), (0.55, 3.37), (0.0, T["roof_height"]),
             (-0.55, 3.37), (-0.98, 3.26), (-1.17, 3.02), (-1.182, 2.95), (-1.20, 1.85)]
    seg = [M_DARK, M_GREEN, M_CREAM] + [M_GREEN] * 8 + [M_CREAM, M_GREEN]              # 13 edges
    mb.prism_x(prof_, -hl, hl - NOSE, seg, cap_mat=M_GREEN, smooth=True)
    RAKE = [0.0, 0.0, 0.0, 0.20, 0.21, 0.25, 0.27, 0.28, 0.27, 0.25, 0.21, 0.20, 0.0]   # x setback of the front ring (raked face)
    nose = [(y * 0.82, z - (0.07 if z > 3.0 else 0.0) + (0.04 if z < 1.0 else 0.0)) for y, z in prof_]
    b0, b1 = mb.loft_x(prof_, hl - NOSE, nose, [hl - r for r in RAKE], seg, cap=False, smooth=True)
    for quad, m_ in (((0, 1, 2, 12), M_GREEN), ((12, 2, 3, 11), M_CREAM), ((11, 3, 4, 10), M_GREEN), ((10, 4, 5, 9), M_GREEN),
                     ((9, 5, 6, 8), M_GREEN), ((8, 6, 7), M_GREEN)):                          # front face as planar strips
        mb.face([b1 + i for i in quad], m_, False)

    # ---- side windows: two-pane units with a mid rail (cream sash), doors (3 per side), thin cream pin-stripe
    wins = [(-6.05, -5.0), (-4.62, -3.78), (-3.5, -2.12), (-2.03, -0.72), (-0.42, 0.42), (0.72, 2.03), (2.12, 3.5), (3.78, 4.62), (5.0, 6.05)]
    for sy in (-1, 1):
        for a, b in wins:
            xm = (a + b) / 2
            mb.box((xm, sy * 1.19, 2.47), (b - a, 0.03, 0.82), M_GLASS)
            mb.box((xm, sy * 1.203, 2.44), (b - a + 0.05, 0.012, 0.035), M_CREAM)                 # mid rail
            if b - a > 1.1:                                                                       # two panes -> centre mullion
                mb.box((xm, sy * 1.203, 2.47), (0.05, 0.012, 0.86), M_CREAM)
            for xe in (a, b):                                                                     # window surround
                mb.box((xe, sy * 1.203, 2.47), (0.035, 0.012, 0.88), M_CREAM)
            mb.box((xm, sy * 1.203, 2.905), (b - a + 0.05, 0.012, 0.035), M_CREAM)
            mb.box((xm, sy * 1.203, 2.035), (b - a + 0.05, 0.012, 0.035), M_CREAM)
        for xd in (-4.2, 0.0, 4.2):
            for dx in (-0.55, 0.0, 0.55):
                mb.box((xd + dx, sy * 1.205, 1.90), (0.010, 0.012, 1.90), M_BLACK)
            mb.box((xd, sy * 1.207, 1.40), (1.06, 0.006, 0.05), M_BLACK)                    # door hem
            mb.box((xd, sy * 1.212, 0.80), (0.9, 0.3, 0.03), M_SAFETY)                       # step (yellow-black edge)
            for dx in (-0.28, 0.28):                                                        # door handles (grab bars)
                mb.box((xd + dx, sy * 1.225, 1.50), (0.02, 0.03, 0.70), M_METAL)
        mb.box((0, sy * 1.207, 1.13), (Lc - 0.1, 0.004, 0.022), M_CREAM)                    # pin-stripe on the skirt
        mb.box((0, sy * 1.209, 0.99), (Lc - 0.1, 0.004, 0.012), M_CREAM)

    # ---- cab end (+x): raked V-shaped windshield (two panes + sash), wipers (arm + blade), destination sign, round lamps
    fx = hl + 0.004
    th = math.atan(0.20 / 1.10)                                                     # rake of the cream band (10 deg)

    def face_x(z):                                                                  # x of the raked front face at height z
        if z <= 1.85:
            return hl
        if z <= 2.95:
            return hl - 0.20 * (z - 1.85) / 1.10
        if z <= 3.02:
            return hl - lerp(0.20, 0.21, (z - 2.95) / 0.07)
        return hl - lerp(0.21, 0.25, min((z - 3.02) / 0.24, 1.0))

    zw = 2.48
    for sy in (-1, 1):
        Rm = Euler((0, -th, sy * 0.16), "XYZ").to_matrix()                            # tilt back + yaw each pane (V-shaped screen)
        c0 = Vector((face_x(zw) + 0.012, sy * 0.47, zw))

        def pw(n, u, w, c0=c0, Rm=Rm):
            return tuple(c0 + Rm @ Vector((n, u, w)))

        mb.box(c0, (0.024, 0.86, 0.90), M_GLASS, Rm)
        for (n_, u_, w_, sz) in ((0.016, 0.0, -0.465, (0.03, 0.90, 0.035)), (0.016, 0.0, 0.465, (0.03, 0.90, 0.035)),
                                 (0.016, -0.44, 0.0, (0.03, 0.035, 0.96)), (0.016, 0.44, 0.0, (0.03, 0.035, 0.96))):
            mb.box(pw(n_, u_, w_), sz, M_CREAM, Rm)                                   # sash around the pane
        # wiper: pivot low at the inner corner, arm swept 40 deg up and outward, black blade along the arm
        up_, wp_ = -sy * 0.30, -0.41
        ue_, we_ = up_ + sy * 0.78 * math.cos(math.radians(40)), wp_ + 0.78 * math.sin(math.radians(40))
        mb.cyl(pw(0.034, up_, wp_), pw(0.034, ue_, we_), 0.009, 0.007, 6, M_BLACK)
        mb.cyl(pw(0.040, up_ + (ue_ - up_) * 0.18, wp_ + (we_ - wp_) * 0.18), pw(0.040, up_ + (ue_ - up_) * 0.98, wp_ + (we_ - wp_) * 0.98),
               0.013, 0.013, 4, M_BLACK)
        mb.sphere(pw(0.034, up_, wp_), 0.022, 8, 5, M_METAL)                             # wiper pivot
        mb.cyl((fx + 0.01, sy * 0.80, 1.25), (fx + 0.07, sy * 0.80, 1.25), 0.085, 0.085, 20, M_HEAD)           # warm LED head lamp
        mb.cyl((fx + 0.01, sy * 0.80, 1.55), (fx + 0.055, sy * 0.80, 1.55), 0.055, 0.055, 16, M_TAIL)          # red tail lamp
        mb.cyl((fx + 0.005, sy * 0.80, 1.25), (fx + 0.03, sy * 0.80, 1.25), 0.115, 0.115, 20, M_DARK)          # lamp bezel
    mb.box((face_x(zw) + 0.075, 0, zw), (0.05, 0.07, 0.94), M_CREAM, Euler((0, -th, 0), "XYZ"))               # centre pillar
    th2 = math.atan(0.04 / 0.24)
    mb.box((face_x(3.12) + 0.014, 0, 3.12), (0.024, 0.86, 0.15), M_GLASS, Euler((0, -th2, 0), "XYZ"))         # destination sign
    mb.cyl((fx + 0.005, 0, 1.48), (fx + 0.03, 0, 1.48), 0.15, 0.15, 24, M_CREAM)          # Enoden emblem disc
    mb.cyl((fx + 0.03, 0, 1.48), (fx + 0.036, 0, 1.48), 0.115, 0.115, 24, M_GREEN)
    mb.box((hl + 0.10, 0, 0.78), (0.24, 1.90, 0.20), M_SAFETY)                             # front skirt / plough with safety stripes
    mb.box((hl + 0.28, 0, 0.90), (0.40, 0.26, 0.22), M_METAL)                              # coupler
    for sy in (-1, 1):
        mb.cyl((hl + 0.15, sy * 0.30, 0.68), (hl + 0.15, sy * 0.30, 0.90), 0.018, 0.018, 6, M_BLACK)         # air hoses
    # rear end (-x): plain end wall + draw-bar stub
    mb.box((-hl - 0.012, 0, 2.3), (0.024, 2.10, 2.05), M_DARK)
    mb.box((-hl - 0.25, 0, 0.90), (0.50, 0.24, 0.20), M_METAL)

    # ---- roof: A/C units (kise), vents, cable duct, pantograph
    for x in (-1.9, 2.3):
        mb.box((x, 0, 3.50), (1.75, 0.95, 0.28), M_ROOF)
        mb.box((x, 0, 3.66), (1.55, 0.75, 0.05), M_ROOF)
        for k in range(5):                                                                 # louvres
            mb.box((x - 0.6 + 0.3 * k, 0.48, 3.50), (0.16, 0.012, 0.12), M_BLACK)
    for x in (-5.4, 5.0):
        mb.box((x, 0, 3.47), (0.55, 0.45, 0.16), M_ROOF)
    mb.box((0.2, 0.70, 3.38), (3.2, 0.10, 0.06), M_BLACK)
    x0 = -3.5
    for sy in (-1, 1):
        mb.cyl((x0, sy * 0.36, 3.40), (x0, sy * 0.36, 3.56), 0.065, 0.055, 10, M_INSUL)
    mb.box((x0, 0, 3.585), (0.85, 0.85, 0.05), M_METAL)
    if pan_raised:
        knee, head = (x0 - 1.10, 0, 4.16), (x0 - 0.12, 0, T["pantograph_working_height"] - 0.02)
    else:
        knee, head = (x0 - 0.78, 0, 3.72), (x0 - 0.02, 0, T["pantograph_folded_height"] - 0.06)
    mb.cyl((x0, 0, 3.62), knee, 0.038, 0.034, 8, M_METAL)
    mb.cyl(knee, head, 0.032, 0.030, 8, M_METAL)
    mb.cyl((x0 + 0.12, 0, 3.62), (knee[0] + 0.45, 0, knee[2] + (head[2] - knee[2]) * 0.45), 0.016, 0.016, 6, M_METAL)
    mb.box((head[0], 0, head[2] + 0.03), (0.07, 1.06, 0.05), M_BLACK)
    for sy in (-1, 1):
        mb.cyl((head[0], sy * 0.53, head[2] + 0.03), (head[0] + 0.14, sy * 0.60, head[2] + 0.08), 0.014, 0.014, 5, M_METAL)

    # ---- underfloor + 2 bogies (wheels d=860, axle base 1600, bogie centres 9500)
    mb.box((-1.0, 0, 0.78), (2.4, 1.6, 0.34), M_DARK)
    mb.box((2.0, 0, 0.78), (1.6, 1.4, 0.30), M_DARK)
    mb.box((-3.6, 0, 0.80), (1.4, 1.3, 0.26), M_DARK)
    ab = T["axle_base"] / 2.0
    for xb in (-T["bogie_center"] / 2.0, T["bogie_center"] / 2.0):
        for sy in (-1, 1):
            mb.box((xb, sy * 0.86, 0.60), (2.2, 0.10, 0.22), M_DARK)
        mb.box((xb, 0, 0.64), (0.34, 1.7, 0.20), M_DARK)
        for dx in (-ab, ab):
            mb.cyl((xb + dx, -0.78, 0.43), (xb + dx, 0.78, 0.43), 0.065, 0.065, 10, M_METAL)
            for sy in (-1, 1):
                yc = sy * 0.55
                wr = T["wheel_dia"] / 2.0
                wh.cyl((xb + dx, yc - 0.065, 0.43), (xb + dx, yc + 0.065, 0.43), wr, wr, 28, 0)
                wh.cyl((xb + dx, yc - sy * 0.085, 0.43), (xb + dx, yc - sy * 0.055, 0.43), 0.458, 0.458, 28, 0)
                for k in range(5):                                                        # small lug bolts: the disc is otherwise
                    ang = 2 * math.pi * k / 5                                             # perfectly round, so spinning it would be invisible
                    bx, bz = 0.62 * wr * math.cos(ang), 0.43 + 0.62 * wr * math.sin(ang)
                    wh.cyl((xb + dx + bx, yc + sy * 0.066, bz), (xb + dx + bx, yc + sy * 0.078, bz), 0.018, 0.018, 6, 0)
        for sy in (-1, 1):                                                                 # yellow-black safety guards around the bogie
            mb.box((xb, sy * 0.95, 0.62), (2.30, 0.022, 0.30), M_SAFETY)
            mb.box((xb - 1.16, sy * 0.60, 0.62), (0.022, 0.70, 0.30), M_SAFETY)
            mb.box((xb + 1.16, sy * 0.60, 0.62), (0.022, 0.70, 0.30), M_SAFETY)
        mb.box((xb - ab, 0, 0.48), (0.52, 0.46, 0.40), M_BLACK)

    # ---- interior: longitudinal bench seats under each window bay (real Enoden 1000 seating), floor, standing
    # poles + grab bars at each door, ceiling light strips. Previously a handful of JS box primitives in
    # train.js's _interior() — modelled here instead so it travels through the same glTF export as the rest of
    # the car and needs no separate runtime geometry.
    floor_z = 1.07
    mb.box((0, 0, floor_z - 0.02), (Lc - 0.3, 2.10, 0.04), M_DARK)
    seat_h = 0.43
    for sy in (-1, 1):
        for a, b in wins:
            mb.box(((a + b) / 2, sy * 0.95, floor_z + seat_h / 2), (b - a - 0.06, 0.42, seat_h), M_GREEN)  # moquette, same livery green as the body
    for xd in (-4.2, 0.0, 4.2):
        mb.cyl((xd, 0, floor_z), (xd, 0, T["roof_height"] - 0.05), 0.025, 0.025, 8, M_METAL)
        mb.box((xd, 0, T["roof_height"] - 0.25), (0.03, 0.9, 0.03), M_METAL)
    for x in (-4.5, -1.5, 1.5, 4.5):
        mb.box((x, 0, T["roof_height"] - 0.08), (1.6, 0.5, 0.04), M_CREAM)
    return mb, wh


def build_train():
    log("Enoden 1000 series (2 cars) ...")
    T = RESEARCH["train_1000"]
    gap = 0.90
    xa = CFG["train_front_x"] - T["car_length"] / 2.0                  # centre of the leading car
    xb = xa - (T["car_length"] + gap)                                   # centre of the trailing car
    xc = (xa + xb) / 2.0
    tr = MB()
    wheels = MB()
    car_a, wheels_a = car_mb(True)
    car_b, wheels_b = car_mb(False)
    tr.append(car_a, Matrix.Translation((xa, 0, 0)))
    tr.append(car_b, Matrix.Translation((xb, 0, 0)) @ Matrix.Rotation(math.pi, 4, "Z"))
    wheels.append(wheels_a, Matrix.Translation((xa, 0, 0)))
    wheels.append(wheels_b, Matrix.Translation((xb, 0, 0)) @ Matrix.Rotation(math.pi, 4, "Z"))
    # gangway bellows (ジャバラ) between the cars + coupler bar
    for i in range(7):
        s = 2.20 if i % 2 == 0 else 2.12
        tr.box((xc - gap / 2 + gap * (i + 0.5) / 7, 0, 2.15), (0.06, s, 2.35 if i % 2 == 0 else 2.27), M_BELLOWS)
    tr.box((xc, 0, 2.15 + 1.15), (gap, 2.0, 0.06), M_BELLOWS)
    tr.cyl((xc - gap / 2 - 0.3, 0, 0.90), (xc + gap / 2 + 0.3, 0, 0.90), 0.10, 0.10, 10, M_METAL)
    mats = [MAT["MAT_Enoden_Green"], MAT["MAT_Enoden_Cream"], MAT["MAT_Train_Dark"], MAT["MAT_Glass_Train"], MAT["MAT_Train_Metal"],
            MAT["MAT_Train_Roof"], MAT["MAT_Bellows"], MAT["MAT_Lamp_Head"], MAT["MAT_Lamp_Tail"], MAT["MAT_Black"], MAT["MAT_Insulator"], MAT["MAT_Safety_Stripe"]]
    ob = tr.build("Enoden_1000_TwoCar", coll("P3_Train"), mats, smooth_angle=math.radians(38), bevel=0.006)
    wheels_ob = wheels.build("Enoden_1000_Wheels", coll("P3_Train"), [MAT["MAT_Train_Metal"]], smooth_angle=math.radians(38))
    wheels_ob.parent = ob  # so place_train()'s single ob.location.x move carries the wheels along; train.js spins this node about its own local Y (axle) per speed
    TRAIN["wheels"] = wheels_ob

    # 45 deg warm-white spot (head lamp) on the leading car
    sp = bpy.data.lights.new("Headlight_Spot", "SPOT")
    sp.spot_size = math.radians(45.0)
    sp.spot_blend = 0.35
    sp.energy = 600.0
    sp.color = (1.0, 0.85, 0.62)
    sp.shadow_soft_size = 0.08
    lo = bpy.data.objects.new("Headlight_Spot", sp)
    lo.location = (xa + T["car_length"] / 2 + 0.25, 0.0, 1.25)
    lo.rotation_euler = (0.0, -math.pi / 2, 0.0)                     # points along +X
    coll("P3_Train").objects.link(lo)
    lo.parent = ob                                                   # move the whole set (incl. head lamp) with one location
    TRAIN["ob"] = ob
    return ob


TRAIN = {}


def place_train(front_x):
    """Slide the finished set along the track so that its cab end is at front_x."""
    TRAIN["ob"].location.x = front_x - CFG["train_front_x"]


# =====================================================================================================================
#  Phase 4  --  Lighting (Sky), cameras, render settings
# =====================================================================================================================
class _WG(SG):
    """SG helper bound to an existing node tree (world shader)."""

    def __init__(self, nt):
        self.mat, self.nt, self.out, self._tc = None, nt, None, None


def _wob(t, seed, oct_=5):
    """Deterministic 1-D ridge noise in about [-1, 1] (sum of sines)."""
    r, a, f = 0.0, 0.5, 3.0
    rng = random.Random(seed)
    for _ in range(oct_):
        r += a * math.sin(2 * math.pi * (f * t + rng.random()))
        a *= 0.55
        f *= 2.1
    return r


def build_far_land():
    """Distant silhouettes seen across the bay (refs: Wikimedia Commons dusk photo + Street View): Enoshima with the Sea Candle,
    Inamuragasaki, the Hayama hills, Hakone/Izu and Mt. Fuji.  Vertical cut-out sheets on arcs around the crossing; scene azimuth
    = true bearing - 7.3 deg (the scene +Y is 7.3 deg east of north)."""
    if not CFG["far_land"]:
        return
    log("far land: Enoshima, headlands, Fuji ...")
    c = coll("P4_FarLand")
    g = SG("MAT_Far_Land")
    dist = g.n("ShaderNodeCameraData").outputs["View Distance"]
    haze = g.mapr(dist, 1500.0, 14000.0, 0.10, 0.96)                               # forest green -> horizon colour with distance;
    diff = g.principled("#1F2B1E", 0.0, 1.0, spec=0.0)                             # the haze part is emissive so that far layers
    reg(g, g.mix_shader(haze, diff, g.emission("#D3C4D0", 2.0)))                  # converge to the sky colour whatever the lighting
    mat = MAT["MAT_Far_Land"]
    zb = CFG["sea"]["z"]

    def sheet(name, az0, az1, R, hfun, n=260):
        mb = MB()
        pts = []
        for i in range(n + 1):
            t = i / n
            a = math.radians(lerp(az0, az1, t))
            x, y = R * math.sin(a), R * math.cos(a)
            pts += [(x, y, zb + max(hfun(t), 0.0)), (x, y, zb - 40.0)]
        b = mb.verts(pts)
        for i in range(n):
            mb.face((b + 2 * i, b + 2 * i + 1, b + 2 * i + 3, b + 2 * i + 2), 0, False)
        mb.build(name, c, [mat])

    def bump(t, p=1.0):
        return max(0.0, 1.0 - ((t - 0.5) / 0.5) ** 2) ** p

    az_ens = 248.3 - 7.3                                                            # Enoshima: true bearing ~248 deg, ~2.2 km
    sheet("FarLand_Enoshima", az_ens - 13.0, az_ens + 13.0, 2200.0,
          lambda t: 62.0 * bump(t, 0.75) * (1.0 + 0.10 * _wob(t, 1)) + 50.0 * max(0.0, 1.0 - abs(t - 0.60) / 0.008) * bump(t, 0.4))
    sheet("FarLand_Enoshima_Islet", az_ens - 20.0, az_ens - 11.0, 2350.0, lambda t: 14.0 * bump(t, 0.6) * (1.0 + 0.2 * _wob(t, 2)))
    sheet("FarLand_Inamuragasaki", 88.0, 106.0, 2400.0, lambda t: 30.0 * bump(t, 0.6) * (1.0 + 0.15 * _wob(t, 3)))
    sheet("FarLand_Hayama_Hills", 96.0, 138.0, 9500.0, lambda t: (70.0 + 55.0 * _wob(t, 4)) * (1.0 - 0.75 * t ** 2) + 30.0 * bump(t, 0.5))
    sheet("FarLand_Hakone_Izu", 214.0, 282.0, 42000.0, lambda t: (760.0 + 380.0 * _wob(t, 5, 6)) * (0.35 + 0.65 * bump(t, 0.3)))
    az_fuji = 275.0 - 7.3                                                           # Mt. Fuji: bearing ~275 deg, ~70 km
    sheet("FarLand_Fuji", az_fuji - 18.0, az_fuji + 18.0, 68000.0, lambda t: 3776.0 * max(0.0, 1.0 - abs((t - 0.5) / 0.5)) ** 1.7, n=200)


def build_world():
    """Spec 5.1.  NOTE: Blender 5.x removed the 'Nishita' sky type; its successors are SINGLE/MULTIPLE_SCATTERING
    (same physical model).  'Dust' became aerosol_density.  sun_rotation: 0 = +Y (north), 90 = +X, clockwise
    (calibrated by rendering) -> 225 deg = south-west, i.e. the light comes from the Sagami Bay / Enoshima side."""
    S = CFG["sun"]
    w = bpy.data.worlds.new("World_GoldenHour")
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    sky = nt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_elevation = math.radians(S["elevation"])
    sky.sun_rotation = math.radians(S["rotation"])
    sky.aerosol_density = ARGS.aerosol if ARGS.aerosol is not None else S["dust"]
    sky.ozone_density = ARGS.ozone if ARGS.ozone is not None else S["ozone"]
    sky.air_density = 1.0
    sky.sun_disc = True
    sky.sun_size = math.radians(0.545)
    sky.sun_intensity = 1.0
    bg = nt.nodes.new("ShaderNodeBackground")
    out = nt.nodes.new("ShaderNodeOutputWorld")
    sky_col = sky.outputs["Color"]
    if CFG["clouds"]:
        g = _WG(nt)
        d = g.n("ShaderNodeTexCoord").outputs["Generated"]                      # world: unit view direction
        dx, dy, dz = g.sep(d)
        # (a) colour grading with elevation: warm pink haze at the horizon -> deeper blue-violet overhead
        grade = g.ramp(dz, [(0.0, (1.0, 0.93, 0.90, 1)), (0.20, (1.0, 1.0, 1.0, 1)), (0.75, (0.68, 0.76, 1.0, 1))])
        graded = g.n("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY", clamp_factor=True)
        graded.inputs[0].default_value = 1.0
        g.put(g.sk(graded, "in", "A", "RGBA"), sky_col)
        g.put(g.sk(graded, "in", "B", "RGBA"), grade)
        graded_c = g.sk(graded, "out", "Result", "RGBA")
        # (b) stratus / stratocumulus: noise on a plane projected from the view direction
        inv = g.math("ADD", dz, 0.16)
        comb = g.n("ShaderNodeCombineXYZ")
        g.put(comb.inputs["X"], g.math("DIVIDE", dx, inv))
        g.put(comb.inputs["Y"], g.math("MULTIPLY", g.math("DIVIDE", dy, inv), 0.55))
        pos = comb.outputs["Vector"]
        n_fine = g.noise(2.4, 7.0, 0.62, vec=pos, distortion=0.9)
        n_cov = g.noise(0.5, 3.0, 0.5, vec=pos)
        cover = g.math("ADD", g.math("MULTIPLY", n_fine, 0.8), g.math("MULTIPLY", n_cov, 0.55))
        mask = g.ramp(cover, [(0.52, (0, 0, 0, 1)), (0.80, (1, 1, 1, 1))])
        S_az, S_el = math.radians(CFG["sun"]["rotation"]), math.radians(CFG["sun"]["elevation"])
        sun_dir = (math.sin(S_az) * math.cos(S_el), math.cos(S_az) * math.cos(S_el), math.sin(S_el))
        dot = g.n("ShaderNodeVectorMath", operation="DOT_PRODUCT")
        g.put(dot.inputs[0], d)
        dot.inputs[1].default_value = sun_dir
        sdot = dot.outputs["Value"]
        sun_window = g.mapr(sdot, 0.955, 0.992, 0.0, 1.0)                        # keep +-15 deg around the sun cloud-free
        horizon = g.mapr(dz, 0.0, 0.16, 0.0, 1.0)
        mask = g.math("MULTIPLY", g.math("MULTIPLY", mask, horizon), g.math("SUBTRACT", 1.0, sun_window))
        shade = g.mapr(n_fine, 0.35, 0.75, 0.38, 1.10)                            # shaded bellies / lit tops
        warm = g.mapr(sdot, 0.45, 0.97, 0.0, 1.0)                                 # sun-side clouds catch orange light
        c1 = g.n("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY", clamp_factor=True)
        c1.inputs[0].default_value = 1.0
        g.put(g.sk(c1, "in", "A", "RGBA"), graded_c)
        g.put(g.sk(c1, "in", "B", "RGBA"), g.mix(shade, (0.34, 0.38, 0.52, 1), (1.0, 0.97, 0.94, 1)))
        c2 = g.n("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY", clamp_factor=True)
        g.put(c2.inputs[0], warm)
        g.put(g.sk(c2, "in", "A", "RGBA"), g.sk(c1, "out", "Result", "RGBA"))
        g.put(g.sk(c2, "in", "B", "RGBA"), (1.0, 0.62, 0.42, 1))
        sky_col = g.mix(mask, graded_c, g.sk(c2, "out", "Result", "RGBA"))
    nt.links.new(sky_col, bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    # thin warm sea-side haze (aerial perspective, "air feel"); ~1 km visibility
    haze = ARGS.haze if ARGS.haze is not None else CFG["haze_density"]
    if haze > 0.0:
        vs = nt.nodes.new("ShaderNodeVolumeScatter")
        vs.inputs["Color"].default_value = hexc("#F4E4D2")
        vs.inputs["Density"].default_value = haze
        vs.inputs["Anisotropy"].default_value = 0.55
        nt.links.new(vs.outputs["Volume"], out.inputs["Volume"])
    SCENE.world = w
    return w


def make_camera(name, loc, target, lens, dof_target=None, fstop=None):
    cam = bpy.data.cameras.new(name)
    cam.lens = lens
    cam.sensor_width = 36.0
    cam.clip_start, cam.clip_end = 0.1, 300000.0
    ob = bpy.data.objects.new(name, cam)
    coll("P4_Cameras").objects.link(ob)
    ob.location = loc
    d = Vector(target) - Vector(loc)
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    if dof_target is not None:
        cam.dof.use_dof = True
        cam.dof.focus_object = dof_target
        cam.dof.aperture_fstop = fstop
    return ob


def build_cameras():
    # Camera 1: level-crossing viewpoint, 50 mm, focus on the alarm, f/2.8 (spec 5.2)
    focus = make_empty("Focus_Alarm", (3.6, 2.75, 2.95), coll("P4_Cameras"), "SPHERE", 0.25)
    c1 = make_camera("Cam1_Crossing", (1.2, 7.5, 2.3), (0.0, -15.0, 1.0), 50.0, focus, 2.8)
    # Camera 2: platform / track / bay from the road side, 35 mm.  The spec gives only the position; the target is chosen so
    # that it looks east along the coast (platform on the left, sea on the right, sun behind the camera).
    c2 = make_camera("Cam2_PlatformAerial", (-40.0, -15.0, 12.0), CFG["cam2_target"], 35.0)
    return c1, c2


def apply_grade(exposure, look):
    """Exposure + AgX look (CLI --exposure / --look override the per-camera values)."""
    sc = SCENE
    for lk in ([ARGS.look] if ARGS.look else [look]) + ["None"]:
        try:
            sc.view_settings.look = lk
            break
        except TypeError:
            continue
    sc.view_settings.exposure = ARGS.exposure if ARGS.exposure is not None else exposure


def configure_render():
    sc = SCENE
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.scale_length = 1.0
    sc.render.resolution_x, sc.render.resolution_y = ARGS.res_x, ARGS.res_y
    sc.render.resolution_percentage = ARGS.percent
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_depth = "16"
    if ARGS.engine == "CYCLES":
        sc.render.engine = "CYCLES"
        cy = sc.cycles
        cy.device = "CPU"
        cy.samples = ARGS.samples
        cy.use_adaptive_sampling = True
        cy.adaptive_threshold = 0.02
        cy.use_denoising = True
        try:
            cy.denoiser = "OPENIMAGEDENOISE"
        except TypeError:
            pass
        cy.max_bounces = 8
        cy.transmission_bounces = 8
        cy.sample_clamp_indirect = 6.0
        cy.caustics_reflective = False
        cy.caustics_refractive = False
    else:
        sc.render.engine = "BLENDER_EEVEE"
        sc.eevee.taa_render_samples = ARGS.samples
        try:
            sc.eevee.use_raytracing = True
        except Exception:
            pass
    for vt in ([ARGS.view] if ARGS.view else []) + ["AgX"]:
        try:
            sc.view_settings.view_transform = vt
            break
        except TypeError:
            continue
    apply_grade(CFG["exposure"], CFG["look"][0])
    try:                                                                      # gentle warm grade (R up / B down in the mids)
        vs = sc.view_settings
        vs.use_curve_mapping = True
        cm = vs.curve_mapping
        for idx, dy in ((1, CFG["warm_grade"][0]), (3, CFG["warm_grade"][1])):
            cm.curves[idx].points.new(0.5, 0.5 + dy)
        cm.update()
    except Exception as e:
        log("warm grade skipped:", e)


def cleanup_scene():
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for attr in ("meshes", "curves", "materials", "lights", "cameras", "node_groups", "worlds", "fonts"):
        for d in list(getattr(bpy.data, attr)):
            getattr(bpy.data, attr).remove(d)


def build_character():
    """Append the rigged Japanese man in his 20s (output/character/character_male20s.blend), freeze a 'waiting at the crossing' pose
    (idle stance, head turned toward the approaching train) and stand him on the footway.  Skipped with --no-character or when the file
    is missing."""
    if ARGS.no_character:
        return None
    cfg = CFG["character"]
    path = os.path.join(HERE, "output", "character", "character_male20s.blend")
    if not os.path.exists(path):
        log("character blend not found -> skipped:", path)
        return None
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import char_anim as CA
    want = ["Rig_Male20s", "Body", "Head", "Lips", "Eyelids", "Brows", "Eyeball_L", "Eyeball_R", "Cornea_L", "Cornea_R", "Hair", "HairRoots",
            "Shirt", "Trousers", "Sneakers", "Watch"]
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = [n for n in want if n in src.objects]
    c = coll("P5_Character")
    arm = None
    for ob in dst.objects:
        if ob is None:
            continue
        c.objects.link(ob)
        if ob.type == "ARMATURE":
            arm = ob
    if arm is None:
        log("character: armature missing")
        return None
    arm.animation_data_clear()
    rig = CA.RigData(arm)
    D, t = CA.idle_pose(rig, cfg["idle_frame"])
    hl = D["Neck"].inverted() @ D["Head"]
    D["Neck"] = D["Neck"] @ CA.Rz(math.radians(cfg["neck_yaw_deg"]))
    D["Head"] = D["Neck"] @ CA.Rz(math.radians(cfg["head_yaw_deg"])) @ hl
    for n in ("Jaw", "LeftEye", "RightEye"):
        D[n] = D["Head"]
    CA.set_pose(arm, rig, rig.to_keys(D, t))
    x, y = cfg["pos"]
    arm.location = (x, y, CFG["r134"]["walk_z"])
    arm.rotation_euler = (0.0, 0.0, math.radians(cfg["yaw_deg"]))
    log("character placed at (%.1f, %.1f), %d objects" % (x, y, len([o for o in dst.objects if o])))
    return arm


def main():
    cleanup_scene()
    configure_render()
    load_plateau()
    build_materials()

    # ---- Phase 1: infrastructure + background base
    path = hill_road_path()
    build_terrain()
    boxes = build_buildings(path)
    build_lanes(path)
    build_vegetation(boxes, path)
    build_ocean()
    build_seawall()
    build_tetrapods()
    build_roads(path)
    build_track()
    build_trackside_details()

    # ---- Phase 2: architecture & props
    build_platform()
    build_station_extras()
    build_crossing()
    build_guardrails(path)
    poles = build_poles(path)
    build_service_drops(poles)
    build_catenary()
    build_streetlights()

    # ---- Phase 3: train
    build_train()

    # ---- Phase 4: far land, world, cameras
    build_far_land()
    build_world()
    c1, c2 = build_cameras()
    build_character()
    SCENE.camera = c1
    if ARGS.web_export:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import enoden_web_export as WE
        WE.run(ARGS.web_export, FOOTPRINTS, WEB_TREES, CFG, log, WEB_LAMPS)
        return
    log("scene built: %d objects, %d materials" % (len(bpy.data.objects), len(bpy.data.materials)))

    os.makedirs(ARGS.out, exist_ok=True)
    if not ARGS.no_blend and bpy.app.background:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(ARGS.out, "enoden_kamakurakokomae.blend"))
        log("saved .blend")
    jobs = [(c1, "cam1", ("cam1", "both"), CFG["train_front_x"]), (c2, "cam2", ("cam2", "both"), CFG["train_front_cam2"])]
    for spec in ARGS.custom:                                        # --custom name=px,py,pz>tx,ty,tz@lens
        nm, rest = spec.split("=", 1)
        pos, rest = rest.split(">", 1)
        tgt, lens = rest.split("@", 1)
        tf = CFG["train_front_x"]
        if "!" in lens:                                              # optional  ...@lens!train_front_x
            lens, tf = lens.split("!")
            tf = float(tf)
        cc = make_camera("Custom_" + nm, tuple(float(v) for v in pos.split(",")), tuple(float(v) for v in tgt.split(",")), float(lens))
        jobs.append((cc, nm, ("custom",), tf))
    for cam, tag, want, tfront in jobs:
        if ARGS.render in want or (want == ("custom",) and ARGS.custom):
            SCENE.camera = cam
            place_train(tfront)
            apply_grade(*CFG["grade"].get(tag, (CFG["exposure"], CFG["look"][0])))
            SCENE.render.filepath = os.path.join(ARGS.out, "enoden_%s.png" % tag)
            log("rendering %s ..." % tag)
            bpy.ops.render.render(write_still=True)
            log("wrote", SCENE.render.filepath)
    SCENE.camera = c1


if __name__ == "__main__":
    main()
