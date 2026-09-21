"""Japanese man in his 20s (171 cm) - procedural, rigged, animated character for Blender 5.2.

  blender -b --python character_male20s.py -- --stage rest            # model + rest-pose test renders
  blender -b --python character_male20s.py -- --stage anim            # + gait actions, verification, contact sheets
Files: char_core / char_body / char_head / char_cloth / char_mat / char_rig / char_anim (same folder)."""
import os
import sys
import math
import random
import argparse
import time

import bpy
import bmesh
from mathutils import Vector, Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from char_core import *
import char_body as CB
import char_head as CH
import char_cloth as CC
import char_mat as CM
import char_rig as CR

T0 = time.time()


def log(*a):
    print("[char %6.1fs]" % (time.time() - T0), *a, flush=True)


def parse():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="rest", choices=["build", "rest", "anim"])
    ap.add_argument("--out", default=os.path.join(HERE, "output", "character"))
    ap.add_argument("--samples", type=int, default=48)
    ap.add_argument("--res", type=int, default=720)
    ap.add_argument("--views", default="front,side,back,q34,head_front,head_q34,head_side,hands")
    ap.add_argument("--no-hair", action="store_true")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--sheets", action="store_true")
    ap.add_argument("--glb", action="store_true")
    ap.add_argument("--web-glb", default="", dest="web_glb", help="also write a light glTF (flat colours, few hair locks, Idle/Walk/Run/Sprint/Jump) for the web viewer")
    ap.add_argument("--test-controller", action="store_true", dest="test_controller")
    ap.add_argument("--poses", default="")
    ap.add_argument("--sheet-only", default="", dest="sheet_only")
    ap.add_argument("--sheet-w", type=int, default=0, dest="sheet_w")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--fast", action="store_true", help="lower head resolution for quick tests")
    return ap.parse_args(argv)


ARGS = parse()


# ------------------------------------------------------------------------------------------------------ object helpers
def make_obj(name, mb, mats, coll, smooth=True):
    me = bpy.data.meshes.new(name)
    me.from_pydata(mb.v, [], mb.f)
    me.update()
    n = len(me.polygons)
    me.polygons.foreach_set("material_index", mb.m[:n])
    me.polygons.foreach_set("use_smooth", [smooth] * n)
    for k, d in mb.attr.items():
        a = me.attributes.new(k, "FLOAT", "POINT")
        a.data.foreach_set("value", [d.get(i, 0.0) for i in range(len(mb.v))])
    if mb.uv:
        uvl = me.uv_layers.new(name="UVMap")
        flat = []
        for i, f in enumerate(mb.f):
            uv = mb.uv.get(i)
            flat += [c for p in uv for c in p] if uv else [0.0, 0.0] * len(f)
        uvl.data.foreach_set("uv", flat)
    for m in mats:
        me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def finalize(ob, levels=0, render_levels=None):
    if levels > 0:
        sd = ob.modifiers.new("Subsurf", "SUBSURF")
        sd.levels = levels
        sd.render_levels = render_levels if render_levels is not None else levels
        sd.subdivision_type = "CATMULL_CLARK"


def build_all(coll):
    rng = random.Random(20)
    parts = {}
    # ------------------------------------------------------------------ body skin
    body = MB()
    CB.torso(body, detail=True, tag="torso", z0=0.83, z1=1.445, nz=30, n=32)
    CB.neck_skin(body)
    fingers = {"L": {}, "R": {}}
    for side, sn in ((1, "L"), (-1, "R")):
        CB.arm_skin(body, side)
        CB.hand_skin(body, side, fingers[sn])
        CB.leg_skin(body, side)
    parts["body"] = (body, "MAT_Skin_Body", 1)
    log("body: %d verts" % len(body.v))
    # ------------------------------------------------------------------ head
    head = MB()
    bvh = CH.build_head(head, nseg=72 if (ARGS.fast or ARGS.web_glb) else 112, nring=72 if (ARGS.fast or ARGS.web_glb) else 112)
    CH.build_ear(head, 1, bvh)
    CH.build_ear(head, -1, bvh)
    parts["head"] = (head, "MAT_Skin_Head", 1)
    lips = MB()
    CH.build_lips(lips, bvh)
    parts["lips"] = (lips, "MAT_Skin_Head", 1)
    lids = MB()
    for s in (1, -1):
        CH.build_eyelids(lids, s)
    parts["lids"] = (lids, "MAT_Skin_Head", 1)
    brows = MB()
    CH.build_brows(brows, bvh, rng)
    parts["brows"] = (brows, "MAT_Brow", 0)
    eyes = {}
    for s, sn in ((1, "L"), (-1, "R")):
        e = MB()
        cor = CH.build_eyeball(e, s)
        eyes[sn] = (e, cor)
    log("head: %d verts" % len(head.v))
    hair = MB()
    cap = MB()
    if not ARGS.no_hair:
        n = CH.build_hair(hair, cap, bvh, rng, n_locks=1800 if ARGS.web_glb else (6500 if ARGS.fast else 11000))
        CH.build_scalp_cap(cap, head)
        log("hair: %d locks, %d verts" % (n, len(hair.v)))
    # ------------------------------------------------------------------ clothes
    shirt = MB()
    CC.tshirt(shirt)
    pants = MB()
    CC.trousers(pants)
    shoes = MB()
    for s in (1, -1):
        CC.sneakers(shoes, s)
    watch = MB()
    CC.watch(watch, 1)
    return dict(body=body, head=head, lips=lips, lids=lids, brows=brows, eyes=eyes, hair=hair, cap=cap, shirt=shirt, pants=pants, shoes=shoes,
                watch=watch, fingers=fingers, parts=parts)


def make_materials():
    M = {}
    M["skin_body"] = CM.skin("MAT_Skin_Body", head=False)
    M["skin_head"] = CM.skin("MAT_Skin_Head", head=True)
    M["eye"] = CM.eyeball()
    M["cornea"] = CM.cornea()
    M["hair"] = CM.hair()
    M["roots"] = CM.hair_roots()
    M["brow"] = CM.brow()
    M["tee"] = CM.fabric("MAT_Tee", "#E4E2DA", 0.88, 1500.0, 0.55)
    M["rib"] = CM.fabric("MAT_TeeRib", "#D6D4CC", 0.9, 2200.0, 0.55)
    M["chino"] = CM.fabric("MAT_Chino", "#27303F", 0.82, 1300.0, 0.35, twill=True, color2="#2E384A")
    M["belt"] = CM.leather("MAT_Belt", "#2A1B13", 0.42)
    M["leather"] = CM.leather("MAT_ShoeUpper", "#E9E7E1", 0.42)
    M["sole"] = CM.rubber("MAT_ShoeSole")
    M["lace"] = CM.fabric("MAT_Lace", "#F0EEE8", 0.8, 3000.0, 0.3)
    M["lining"] = CM.plain("MAT_ShoeLining", "#2B2B2E", 0.7)
    M["strap"] = CM.fabric("MAT_WatchStrap", "#141416", 0.6, 1600.0, 0.1)
    M["steel"] = CM.metal("MAT_WatchSteel")
    M["dial"] = CM.plain("MAT_WatchDial", "#0B0C0E", 0.15)
    return M


def assemble(coll):
    data = build_all(coll)
    M = make_materials()
    arm, segs = CR.make_armature(coll, data["fingers"])
    log("armature: %d bones" % len(segs))
    objs = {}

    def add(name, mb, mats, levels, fixed=None, smooth=True):
        ob = make_obj(name, mb, mats, coll, smooth)
        CR.skin_object(ob, arm, segs, mb, fixed=fixed)
        finalize(ob, levels)
        objs[name] = ob
        return ob
    add("Body", data["body"], [M["skin_body"]], 1)
    add("Head", data["head"], [M["skin_head"]], 1)
    add("Lips", data["lips"], [M["skin_head"]], 1, fixed="Head")
    add("Eyelids", data["lids"], [M["skin_head"]], 1, fixed="Head")
    add("Brows", data["brows"], [M["brow"]], 0, fixed="Head")
    for sn, sname in (("L", "LeftEye"), ("R", "RightEye")):
        e, cor = data["eyes"][sn]
        add("Eyeball_" + sn, e, [M["eye"]], 0, fixed=sname)
        add("Cornea_" + sn, cor, [M["cornea"]], 0, fixed=sname)
    if data["hair"].v:
        add("Hair", data["hair"], [M["hair"]], 0, fixed="Head")
        add("HairRoots", data["cap"], [M["roots"]], 0, fixed="Head")
    add("Shirt", data["shirt"], [M["tee"], M["rib"]], 1)
    add("Trousers", data["pants"], [M["chino"], M["belt"]], 1)
    add("Sneakers", data["shoes"], [M["leather"], M["sole"], M["lace"], M["lining"]], 0)
    add("Watch", data["watch"], [M["strap"], M["steel"], M["dial"]], 0, fixed="LeftForeArm")
    return arm, objs, segs


# ------------------------------------------------------------------------------------------------------ studio + renders
def studio(coll, res):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = ARGS.samples
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    sc.render.resolution_x = res
    sc.render.resolution_y = int(res * 1.25)
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = -0.2
    w = bpy.data.worlds.new("StudioWorld")
    sc.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.42, 0.44, 0.47, 1.0)
    bg.inputs["Strength"].default_value = 0.9
    # floor
    bpy.ops.mesh.primitive_plane_add(size=12, location=(0, 0, 0))
    fl = bpy.context.active_object
    fl.name = "Studio_Floor"
    fm = bpy.data.materials.new("MAT_Floor")
    fm.use_nodes = True
    fm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.32, 0.33, 0.35, 1)
    fm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.8
    fl.data.materials.append(fm)
    for c in fl.users_collection:
        c.objects.unlink(fl)
    coll.objects.link(fl)
    # lights: warm key (sun-like area), cool fill, rim
    def area(name, loc, target, energy, size, color):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy, ld.size, ld.color = energy, size, color
        lo = bpy.data.objects.new(name, ld)
        coll.objects.link(lo)
        lo.location = loc
        d = Vector(target) - Vector(loc)
        lo.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        return lo
    area("Key", (-2.4, -3.2, 3.0), (0, 0, 1.1), 900, 2.2, (1.0, 0.93, 0.85))
    area("Fill", (3.2, -2.4, 1.6), (0, 0, 1.1), 260, 3.0, (0.85, 0.92, 1.0))
    area("Rim", (0.5, 3.2, 2.6), (0, 0, 1.2), 500, 1.5, (1.0, 1.0, 1.0))


def make_cam(name, loc, target, lens, coll):
    cd = bpy.data.cameras.new(name)
    cd.lens = lens
    cd.sensor_width = 36.0
    co = bpy.data.objects.new(name, cd)
    coll.objects.link(co)
    co.location = loc
    co.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return co


VIEWS = {
    "front": ((0.0, -6.2, 0.98), (0.0, 0, 0.86), 62),
    "back": ((0.0, 6.2, 0.98), (0.0, 0, 0.86), 62),
    "side": ((6.2, 0.0, 0.98), (0.0, 0, 0.86), 62),
    "q34": ((3.6, -4.6, 1.15), (0.0, 0, 0.88), 58),
    "head_front": ((0.0, -1.10, 1.60), (0.0, 0, 1.60), 80),
    "head_q34": ((-0.62, -0.95, 1.63), (0.0, 0, 1.60), 82),
    "head_side": ((1.15, 0.0, 1.60), (0.0, 0, 1.60), 80),
    "hands": ((0.75, -1.15, 0.98), (0.27, -0.03, 0.80), 82),
    "eye": ((0.10, -0.62, 1.615), (0.02, -0.07, 1.590), 110),
    "head_top": ((0.0, -0.55, 1.98), (0.0, 0.0, 1.62), 70),
}


def render_views(coll, names, outdir, tag=""):
    sc = bpy.context.scene
    os.makedirs(outdir, exist_ok=True)
    for nm in names:
        if nm not in VIEWS:
            continue
        loc, tgt, lens = VIEWS[nm]
        cam = make_cam("Cam_" + nm, loc, tgt, lens, coll)
        sc.camera = cam
        sc.render.filepath = os.path.join(outdir, "%s%s.png" % (tag, nm))
        bpy.ops.render.render(write_still=True)
        log("rendered", nm)


def main():
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    coll = bpy.data.collections.new("Character")
    bpy.context.scene.collection.children.link(coll)
    arm, objs, segs = assemble(coll)
    log("assembled: %d objects" % len(objs))
    if ARGS.stage == "build":
        return
    if ARGS.stage in ("rest", "anim"):
        studio(coll, ARGS.res)
        if ARGS.stage == "rest":
            render_views(coll, ARGS.views.split(","), ARGS.out)
    if ARGS.save and ARGS.stage != "anim":
        os.makedirs(ARGS.out, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(ARGS.out, "character_male20s.blend"))
    if ARGS.stage == "anim":
        import char_anim as CA
        CA.run(arm, objs, segs, coll, ARGS, log, render_views)


main()
