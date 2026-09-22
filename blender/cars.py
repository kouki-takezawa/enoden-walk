# -*- coding: utf-8 -*-
"""
cars.py — standalone Blender scene generator for background road traffic (B2 of the Blender-real-textures plan).

Builds one detailed compact-car body (loft_x'd cross-section: rocker -> door -> beltline -> tumblehome greenhouse
-> roof, front/rear bumpers, headlight/taillight lenses, B-pillars, mirrors, door handles) plus one wheel+hubcap,
bakes the body paint to a real diffuse/roughness/normal texture via bake_tex.py (paint is left a neutral tintable
grey so src/traffic.js can still recolour each instance via vertex colour, matching the pre-B2 per-car variety),
and exports "cars.glb" with the body and a single wheel as separate top-level objects — src/traffic.js instances
the wheel 4x per car itself (as it already did for the old primitive geometry) rather than baking 4 copies in.

Kept deliberately self-contained (does NOT import enoden_kamakurakokomae.py): that module runs parse_args() and
builds its RESEARCH/CFG dicts at import time (module-level side effects tied to ITS OWN sys.argv), which would
fight with this script's own CLI. The MB mesh builder is small and dependency-free, so it is duplicated here
rather than risking that coupling.

Run (headless):
  blender -b --python blender/cars.py -- --out public/models --samples 24
"""
import argparse
import math
import os
import sys
import time

import bpy
from mathutils import Euler, Matrix, Vector

T0 = time.time()


def log(*a):
    print("[cars %6.1fs]" % (time.time() - T0), *a, flush=True)


try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    HERE = os.path.dirname(bpy.data.filepath) or os.getcwd()
sys.path.insert(0, HERE)
import bake_tex


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="cars.py")
    ap.add_argument("--out", default=os.path.join(HERE, "output", "cars"))
    ap.add_argument("--glb", default="", help="glTF output path (default: <out>/cars.glb)")
    ap.add_argument("--samples", type=int, default=24)
    ap.add_argument("--bake-res", type=int, default=1024)
    return ap.parse_args(argv)


ARGS = parse_args()


# ===================================================================================================== MB mesh builder
# (copied from enoden_kamakurakokomae.py: box / cyl / loft_x / face / build — see that file for the fuller original
# with prism_x / sphere / append also present. Kept identical in spirit so patterns read the same across scripts.)
def rot_mat(rot):
    if rot is None:
        return None
    if isinstance(rot, Matrix):
        return rot.to_3x3()
    return Euler(rot, "XYZ").to_matrix()


class MB:
    def __init__(self):
        self.v, self.f, self.mi, self.sm = [], [], [], []

    def nv(self):
        return len(self.v)

    def face(self, idx, mat=0, smooth=False):
        self.f.append(tuple(idx))
        self.mi.append(mat)
        self.sm.append(smooth)

    def verts(self, pts):
        b = len(self.v)
        self.v.extend((float(p[0]), float(p[1]), float(p[2])) for p in pts)
        return b

    def box(self, c, s, mat=0, rot=None, smooth=False):
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
            self.face([b + i for i in q], mat, smooth)

    def cyl(self, p0, p1, r0, r1=None, segs=12, mat=0, caps=True, smooth=True):
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
            self.face((b0 + i, b0 + j, b1 + j, b1 + i), mat, smooth)
        if caps:
            t = self.verts([p1 + r * r1 for r in ring])
            self.face([t + i for i in range(segs)], mat, False)
            bt = self.verts([p0 + r * r0 for r in ring])
            self.face([bt + i for i in reversed(range(segs))], mat, False)

    def loft_x(self, prof0, x0, prof1, x1, seg_mats=0, cap_mat=None, smooth=False, cap=True):
        """Skin between two (y, z) rings with the same vertex count (both CCW seen from +X)."""
        n = len(prof0)
        mats = [seg_mats] * n if isinstance(seg_mats, int) else list(seg_mats)
        b0 = self.verts([(x0, y, z) for y, z in prof0])
        b1 = self.verts([(x1, y, z) for y, z in prof1])
        for i in range(n):
            j = (i + 1) % n
            self.face((b0 + i, b0 + j, b1 + j, b1 + i), mats[i % len(mats)], smooth)
        if cap:
            e1 = self.verts([(x1, y, z) for y, z in prof1])
            self.face([e1 + i for i in range(n)], mats[0] if cap_mat is None else cap_mat, False)
        return b0, b1

    def cap(self, prof, x, mat, reversed_winding, smooth=False):
        """A flat n-gon face closing a ring at fixed x (own duplicated verts, for a crisp normal)."""
        b = self.verts([(x, y, z) for y, z in prof])
        idx = list(reversed(range(len(prof)))) if reversed_winding else list(range(len(prof)))
        self.face([b + i for i in idx], mat, smooth)

    def build(self, name, collection, mats=()):
        me = bpy.data.meshes.new(name)
        me.from_pydata(self.v, [], self.f)
        me.update()
        n = len(me.polygons)
        me.polygons.foreach_set("material_index", self.mi[:n])
        me.polygons.foreach_set("use_smooth", self.sm[:n])
        for m in mats:
            me.materials.append(m)
        ob = bpy.data.objects.new(name, me)
        collection.objects.link(ob)
        return ob


# ===================================================================================================== materials
def _principled(name, base=(0.5, 0.5, 0.5), rough=0.5, metal=0.0, emit=None, emit_strength=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf is None:
        nt.nodes.clear()
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Base Color"].default_value = (*base, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if emit is not None and "Emission Color" in bsdf.inputs:
        bsdf.inputs["Emission Color"].default_value = (*emit, 1.0)
        bsdf.inputs["Emission Strength"].default_value = emit_strength
    return mat, nt, bsdf


def build_materials():
    M = {}
    # PAINT: kept a neutral tintable mid-grey (src/traffic.js multiplies it by a per-instance vertex colour, same
    # scheme as the old box-primitive car) — subtle noise-driven roughness variation + a light bump give it a real
    # (baked) clearcoat micro-texture instead of a perfectly flat plastic look.
    mat, nt, bsdf = _principled("MAT_CarPaint", base=(0.62, 0.61, 0.59), rough=0.28, metal=0.12)
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 60.0
    noise.inputs["Detail"].default_value = 4.0
    ramp = nt.nodes.new("ShaderNodeMapRange")
    ramp.inputs["To Min"].default_value = 0.20
    ramp.inputs["To Max"].default_value = 0.38
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Value"])
    nt.links.new(ramp.outputs["Result"], bsdf.inputs["Roughness"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.06
    noise2 = nt.nodes.new("ShaderNodeTexNoise")
    noise2.inputs["Scale"].default_value = 220.0
    nt.links.new(noise2.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    M["paint"] = mat

    M["glass"], _, _ = _principled("MAT_CarGlass", base=(0.05, 0.08, 0.11), rough=0.08, metal=0.35)
    M["trim"], _, _ = _principled("MAT_CarTrim", base=(0.015, 0.015, 0.017), rough=0.5, metal=0.0)
    M["bumper"], _, _ = _principled("MAT_CarBumper", base=(0.045, 0.045, 0.05), rough=0.42, metal=0.0)
    M["chrome"], _, _ = _principled("MAT_CarChrome", base=(0.85, 0.85, 0.86), rough=0.12, metal=1.0)
    M["head"], _, _ = _principled("MAT_CarHead", base=(0.05, 0.05, 0.05), rough=0.3, metal=0.0,
                                   emit=(1.0, 0.93, 0.78), emit_strength=3.0)
    M["tail"], _, _ = _principled("MAT_CarTail", base=(0.05, 0.01, 0.01), rough=0.3, metal=0.0,
                                   emit=(1.0, 0.08, 0.05), emit_strength=2.2)
    M["tire"], _, _ = _principled("MAT_CarTire", base=(0.018, 0.018, 0.018), rough=0.75, metal=0.0)
    M["hub"], _, _ = _principled("MAT_CarHub", base=(0.72, 0.72, 0.74), rough=0.25, metal=0.85)
    return M


# ===================================================================================================== body
PAINT, GLASS, TRIM, BUMPER, HEAD, TAIL, CHROME = range(7)
MAT_ORDER = ("paint", "glass", "trim", "bumper", "head", "tail", "chrome")

# stations: (x, half_width_body, z_floor, z_shoulder, half_width_roof, z_roof)
STATIONS = [
    (-2.05, 0.55, 0.42, 0.60, 0.40, 0.72),   # S0 rear cap
    (-1.90, 0.87, 0.40, 0.68, 0.55, 0.90),   # S1 rear bumper
    (-1.50, 0.87, 0.40, 0.80, 0.55, 1.00),   # S2 trunk
    (-0.90, 0.87, 0.40, 0.95, 0.62, 1.42),   # S3 C-pillar / rear glass base
    (-0.50, 0.87, 0.40, 0.95, 0.60, 1.45),   # S4 roof rear
    (0.55, 0.87, 0.40, 0.95, 0.60, 1.45),    # S5 roof front
    (0.95, 0.85, 0.40, 0.92, 0.62, 1.12),    # S6 windshield base
    (1.55, 0.83, 0.40, 0.80, 0.55, 0.78),    # S7 hood
    (1.90, 0.85, 0.42, 0.65, 0.50, 0.66),    # S8 front bumper
    (2.05, 0.55, 0.44, 0.55, 0.38, 0.60),    # S9 front cap
]
GREENHOUSE = {(3, 4), (4, 5), (5, 6)}   # station-pair indices whose upper side edges are glass, not paint


def ring(hw, zf, zs, hwr, zr):
    return [(-hw, zf), (hw, zf), (hw, zs), (hwr, zr), (-hwr, zr), (-hw, zs)]


def car_body_mb():
    mb = MB()
    profs = [ring(*st[1:]) for st in STATIONS]
    xs = [st[0] for st in STATIONS]
    BODY_MATS = [TRIM, PAINT, PAINT, PAINT, PAINT, PAINT]
    GLASS_MATS = [TRIM, PAINT, GLASS, PAINT, GLASS, PAINT]
    BUMPER_MATS = [BUMPER, PAINT, PAINT, PAINT, PAINT, PAINT]
    for i in range(len(STATIONS) - 1):
        seg = GLASS_MATS if (i, i + 1) in GREENHOUSE else (BUMPER_MATS if i in (0, len(STATIONS) - 2) else BODY_MATS)
        mb.loft_x(profs[i], xs[i], profs[i + 1], xs[i + 1], seg, cap=False)
    mb.cap(profs[0], xs[0], BUMPER, reversed_winding=True)
    mb.cap(profs[-1], xs[-1], BUMPER, reversed_winding=False)

    # B-pillar (breaks the glass band at the roof mid-point into front/rear windows)
    for sy in (-1, 1):
        mb.box((0.0, sy * 0.63, 1.18), (0.09, 0.11, 0.56), TRIM)

    # headlights (round lens + chrome bezel) / taillights (box lens)
    for sy in (-1, 1):
        mb.cyl((1.97, sy * 0.62, 0.60), (2.03, sy * 0.62, 0.60), 0.145, 0.145, 16, CHROME)
        mb.cyl((1.99, sy * 0.62, 0.60), (2.05, sy * 0.62, 0.60), 0.115, 0.115, 16, HEAD)
        mb.box((-1.98, sy * 0.66, 0.68), (0.10, 0.24, 0.30), TAIL)
        mb.box((-1.94, sy * 0.66, 0.68), (0.03, 0.28, 0.34), CHROME)

    # grille (dark recess between the headlights) + front/rear plate recesses
    mb.box((2.02, 0.0, 0.55), (0.03, 0.55, 0.28), TRIM)
    for k in range(5):
        mb.box((2.03, -0.24 + 0.12 * k, 0.55), (0.02, 0.03, 0.26), CHROME)

    # door mirrors
    for sy in (-1, 1):
        mb.box((0.80, sy * 0.94, 1.05), (0.20, 0.10, 0.12), TRIM)
        mb.box((0.80, sy * 1.00, 1.05), (0.16, 0.04, 0.09), GLASS)

    # door handles (2 per side, roughly at the front/rear door positions)
    for sy in (-1, 1):
        for xh in (0.15, -1.05):
            mb.box((xh, sy * 0.885, 0.80), (0.16, 0.025, 0.045), CHROME)

    return mb


def wheel_mb():
    """Axle along local Y (this project's Blender->glTF export is Y-up, so Blender Y is the car's *width* axis in
    both Blender and the exported object — same convention CarBody uses). traffic.js relies on that: it spins each
    wheel instance around its own local Z (glTF space) to roll, with no extra alignment rotation needed."""
    mb = MB()
    r, w = 0.33, 0.22
    mb.cyl((0, -w / 2, 0), (0, w / 2, 0), r, r, 20, 0)   # tire
    mb.cyl((0, -w / 2 - 0.002, 0), (0, -w / 2 + 0.03, 0), r * 0.62, r * 0.62, 14, 1)   # hubcaps (both faces)
    mb.cyl((0, w / 2 - 0.03, 0), (0, w / 2 + 0.002, 0), r * 0.62, r * 0.62, 14, 1)
    return mb


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    coll = scene.collection

    M = build_materials()
    body_mb = car_body_mb()
    body_ob = body_mb.build("CarBody", coll, [M[k] for k in MAT_ORDER])
    log("body built:", len(body_mb.v), "verts", len(body_mb.f), "faces")

    wmb = wheel_mb()
    wheel_ob = wmb.build("CarWheel", coll, [M["tire"], M["hub"]])
    log("wheel built:", len(wmb.v), "verts")

    os.makedirs(ARGS.out, exist_ok=True)
    outdir = os.path.join(ARGS.out, "textures")
    orig_mat = body_ob.material_slots[0].material   # PAINT — the only slot worth baking (see module docstring)
    try:
        bake_tex.smart_unwrap(body_ob)
        paths = bake_tex.bake_to_uv(body_ob, orig_mat, outdir, "car_paint", resolution=ARGS.bake_res)
        log("car paint bake ->", ", ".join(os.path.basename(p) for p in paths.values()))
        bake_tex.wire_baked_textures(orig_mat, paths)
    except Exception as e:
        log("car paint bake failed:", e)

    glb_path = ARGS.glb or os.path.join(ARGS.out, "cars.glb")
    bpy.ops.object.select_all(action="DESELECT")
    body_ob.select_set(True)
    wheel_ob.select_set(True)
    bpy.context.view_layer.objects.active = body_ob
    valid = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    want = {"filepath": glb_path, "export_format": "GLB", "use_selection": True, "export_apply": False,
            "export_yup": True, "export_texcoords": True, "export_normals": True, "export_image_format": "AUTO",
            "export_materials": "EXPORT", "export_draco_mesh_compression_enable": True,
            "export_draco_mesh_compression_level": 7, "export_draco_position_quantization": 14,
            "export_draco_normal_quantization": 8, "export_draco_generic_quantization": 12,
            "export_draco_texcoord_quantization": 11}
    kw = {k: v for k, v in want.items() if k in valid}
    bpy.ops.export_scene.gltf(**kw)
    log("cars glb: %s (%.2f MB)" % (glb_path, os.path.getsize(glb_path) / 1e6))


if __name__ == "__main__":
    main()
