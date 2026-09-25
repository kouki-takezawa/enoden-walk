"""Woody (Toy Story) - procedural, rigged, animated character for Blender 5.2 (personal use).

  blender -b --python woody.py -- --stage rest                  # model + turnaround / face test renders
  blender -b --python woody.py -- --stage anim --sheets --save  # + idle / walk / run / sprint / jump actions, checks, contact sheets, .blend
  blender output/woody/woody.blend --python open_woody.py       # GUI: WASD control + action buttons

Human-sized (about 1.85 m to the crown, 1.92 m with the hat).  Legs use the 20s-male skeleton, so the gait code of char_anim (foot
placement, IK, sliding checks) is reused as-is; the neck and head are longer / bigger.  Files: woody_parts (geometry), woody_mat
(materials), char_core / char_body / char_cloth / char_mat / char_rig / char_anim / char_controller (shared with the male character)."""
import os
import sys
import argparse
import time

import bpy
import bmesh
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import char_core as CO

# ---- Woody's skeleton: same legs / arms as the male rig, longer neck, big head (must happen before anything reads the tables)
CO.SPINE["Neck"] = ((0.0, -0.004, 1.395), (0.0, -0.010, 1.500))
CO.SPINE["Head"] = ((0.0, -0.010, 1.500), (0.0, -0.010, 1.850))

import char_rig as CR
import woody_parts as WP
import woody_mat as WM

T0 = time.time()
RIG_NAME = "Rig_Woody"


def log(*a):
    print("[woody %6.1fs]" % (time.time() - T0), *a, flush=True)


def parse():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="rest", choices=["build", "rest", "anim"])
    ap.add_argument("--out", default=os.path.join(HERE, "output", "woody"))
    ap.add_argument("--samples", type=int, default=48)
    ap.add_argument("--res", type=int, default=720)
    ap.add_argument("--views", default="front,side,back,q34,head_front,head_q34,head_side")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--sheets", action="store_true")
    ap.add_argument("--sheet-only", default="", dest="sheet_only")
    ap.add_argument("--sheet-w", type=int, default=0, dest="sheet_w")
    ap.add_argument("--glb", action="store_true")
    ap.add_argument("--web-glb", default="", dest="web_glb", help="light glTF for the enoden-walk app: baked textures, Idle/Walk/Run/Sprint/Jump")
    ap.add_argument("--poses", default="", help="action:frame:view,...  e.g. run:5:q34")
    ap.add_argument("--test-controller", action="store_true", dest="test_controller")
    ap.add_argument("--no-verify", action="store_true", dest="no_verify")
    a = ap.parse_args(argv)
    a.out = os.path.abspath(a.out)
    return a


ARGS = parse()


# ------------------------------------------------------------------------------------------------------ objects
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
    rest = me.attributes.new("rest", "FLOAT_VECTOR", "POINT")          # rest-pose position: pattern coordinates that follow the cloth
    rest.data.foreach_set("vector", [c for p in mb.v for c in p])
    bm = bmesh.new()                                                     # consistent winding (outward on closed parts)
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def build_all():
    P = {}
    fingers = {"L": {}, "R": {}}
    # head, face
    head = CO.MB()
    bvh = WP.head_mesh(head)
    for s in (1, -1):
        WP.ear(head, s)
    P["Head"] = head
    eye_c = {}
    for s, sn in ((1, "L"), (-1, "R")):
        eye_c[sn] = WP.eye_centre(bvh, s)
        e = CO.MB()
        WP.eyeball(e, eye_c[sn], s)
        P["Eye_" + sn] = e
    lids = CO.MB()
    for sn in ("L", "R"):
        WP.eyelid(lids, eye_c[sn])
    P["Eyelids"] = lids
    brows = CO.MB()
    for s in (1, -1):
        WP.brow(brows, bvh, s)
    P["Brows"] = brows
    m_in, m_line = CO.MB(), CO.MB()
    WP.mouth(m_in, m_line, bvh)
    P["Mouth"], P["LipLine"] = m_in, m_line
    hair = CO.MB()
    WP.hair(hair)
    P["Hair"] = hair
    hat = CO.MB()
    WP.hat(hat)
    P["Hat"] = hat
    # body
    skin = CO.MB()
    WP.neck(skin)
    WP.hands(skin, fingers)
    P["Skin"] = skin
    shirt = CO.MB()
    WP.shirt(shirt)
    vest = CO.MB()
    WP.vest(vest)
    front = WP.bvh_of(shirt, vest)
    col = CO.MB()
    WP.collars(col, front)
    P["Shirt"], P["Vest"], P["Collar"] = shirt, vest, col
    band = CO.MB()
    WP.bandana(band, front)
    P["Bandana"] = band
    bdg = CO.MB()
    WP.badge(bdg, WP.bvh_of(vest))
    P["Badge"] = bdg
    ring = CO.MB()
    WP.pull_ring(ring, front)
    WP.shirt_buttons(ring, WP.bvh_of(shirt))
    trim = CO.MB()
    WP.vest_trim(trim, vest)
    P["VestTrim"] = trim
    P["PullRing"] = ring
    jeans = CO.MB()
    WP.jeans(jeans)
    WP.holster(jeans)
    P["Jeans"] = jeans
    boots = CO.MB()
    for s in (1, -1):
        WP.boot(boots, s)
    P["Boots"] = boots
    return P, fingers, eye_c


def assemble(coll):
    P, fingers, eye_c = build_all()
    M = WM.make_all()
    base_defs = CO.bone_defs

    def woody_defs():
        d = base_defs()
        d["Jaw"] = (Vector((0.0, -0.010, 1.560)), Vector((0.0, -0.085, 1.500)), "Head", False)
        for sn, side in (("L", "Left"), ("R", "Right")):
            c = eye_c[sn]
            d[side + "Eye"] = (c.copy(), c + Vector((0, -0.03, 0)), "Head", False)
        return d
    CR.bone_defs = woody_defs
    arm, segs = CR.make_armature(coll, fingers)
    arm.name = RIG_NAME
    arm.data.name = RIG_NAME
    log("armature: %d bones" % len(segs))
    spec = [  # name, materials, subdiv levels, fixed bone, solidify thickness
        ("Head", ["skin"], 1, "Head", 0), ("Eye_L", ["eye"], 1, "LeftEye", 0), ("Eye_R", ["eye"], 1, "RightEye", 0),
        ("Eyelids", ["skin"], 1, "Head", 0), ("Brows", ["brow"], 1, "Head", 0), ("Mouth", ["mouth"], 0, "Head", 0),
        ("LipLine", ["lipline"], 0, "Head", 0), ("Hair", ["hair"], 1, "Head", 0), ("Hat", ["hat", "hatband", "hatstitch"], 1, "Head", 0.007),
        ("Skin", ["skin"], 1, None, 0), ("Shirt", ["shirt", "cuff"], 1, None, 0), ("Vest", ["vest"], 1, None, 0.006), ("VestTrim", ["trim"], 0, None, 0),
        ("Collar", ["shirt"], 1, None, 0.003), ("Bandana", ["bandana"], 1, None, 0), ("Badge", ["gold"], 0, None, 0),
        ("PullRing", ["ring"], 1, None, 0), ("Jeans", ["jeans", "belt", "gold"], 1, None, 0), ("Boots", ["boot", "sole", "stitch"], 1, None, 0),
    ]
    objs = {}
    for name, mats, lv, fixed, thick in spec:
        mb = P[name]
        ob = make_obj("Woody_" + name, mb, [M[m] for m in mats], coll)
        CR.skin_object(ob, arm, segs, mb, fixed=fixed)
        if thick:
            so = ob.modifiers.new("Solidify", "SOLIDIFY")
            so.thickness = thick
            so.offset = 0.0
            so.use_even_offset = True
        if lv:
            sd = ob.modifiers.new("Subsurf", "SUBSURF")
            sd.levels = sd.render_levels = lv
        objs[name] = ob
    # the whole hat (crown + brim) is one object; the brim of the hat mesh is single-sided -> solidify gives it thickness,
    # the crown gets it too which is harmless.
    log("objects: %d, verts %d" % (len(objs), sum(len(P[n].v) for n in P)))
    return arm, objs, segs


# ------------------------------------------------------------------------------------------------------ studio + renders
def studio(coll, res):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = ARGS.samples
    sc.cycles.use_denoising = True
    sc.render.resolution_x = res
    sc.render.resolution_y = int(res * 1.25)
    sc.view_settings.view_transform = "Standard"          # saturated, cartoon-like colours
    sc.view_settings.look = "None"
    sc.view_settings.exposure = -0.35
    w = bpy.data.worlds.new("StudioWorld")
    sc.world = w
    w.use_nodes = True
    nt = w.node_tree
    bg = next((n for n in nt.nodes if n.type == "BACKGROUND"), None)
    if bg is None:                                   # Blender 5.x: a new world has no nodes
        bg = nt.nodes.new("ShaderNodeBackground")
        out = next((n for n in nt.nodes if n.type == "OUTPUT_WORLD"), None) or nt.nodes.new("ShaderNodeOutputWorld")
        nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    bg.inputs["Color"].default_value = (0.50, 0.56, 0.62, 1.0)
    bg.inputs["Strength"].default_value = 0.55
    bpy.ops.mesh.primitive_plane_add(size=12, location=(0, 0, 0))
    fl = bpy.context.active_object
    fl.name = "Studio_Floor"
    fl.data.materials.append(WM.CM.plain("MAT_Floor", "#6E6255", 0.7))
    for c in fl.users_collection:
        c.objects.unlink(fl)
    coll.objects.link(fl)

    def area(name, loc, target, energy, size, color):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy, ld.size, ld.color = energy, size, color
        lo = bpy.data.objects.new(name, ld)
        coll.objects.link(lo)
        lo.location = loc
        lo.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    area("Key", (-2.4, -3.2, 3.2), (0, 0, 1.2), 520, 2.2, (1.0, 0.94, 0.86))
    area("Fill", (3.2, -2.4, 1.7), (0, 0, 1.2), 160, 3.0, (0.86, 0.92, 1.0))
    area("Rim", (0.5, 3.2, 2.8), (0, 0, 1.3), 320, 1.5, (1.0, 1.0, 1.0))


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
    "front": ((0.0, -6.8, 1.02), (0.0, 0, 0.97), 60),
    "back": ((0.0, 6.8, 1.02), (0.0, 0, 0.97), 60),
    "side": ((6.8, 0.0, 1.02), (0.0, 0, 0.97), 60),
    "q34": ((3.9, -5.0, 1.25), (0.0, 0, 0.98), 57),
    "head_front": ((0.0, -1.30, 1.70), (0.0, 0, 1.69), 72),
    "head_q34": ((-0.80, -1.05, 1.74), (0.0, 0, 1.69), 72),
    "head_side": ((1.30, 0.0, 1.70), (0.0, 0, 1.69), 72),
    "chest": ((0.35, -1.25, 1.32), (0.0, 0, 1.28), 60),
}


def render_views(coll, names, outdir, tag=""):
    sc = bpy.context.scene
    os.makedirs(outdir, exist_ok=True)
    for nm in names:
        if nm not in VIEWS:
            continue
        loc, tgt, lens = VIEWS[nm]
        sc.camera = make_cam("Cam_" + nm, loc, tgt, lens, coll)
        sc.render.filepath = os.path.join(outdir, "%s%s.png" % (tag, nm))
        bpy.ops.render.render(write_still=True)
        log("rendered", nm)


# ------------------------------------------------------------------------------------------------------ animation
def run_anim(arm, objs, coll):
    import char_anim as CA
    sc = bpy.context.scene
    sc.render.fps = CA.FPS
    rig = CA.RigData(arm)
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    for g in CA.GAITS.values():
        g["stride_wrap"] = 0.0
    CA.GAITS["walk"]["arm"] = 26                 # a slightly looser, cartoonier arm swing than the male walk
    CA.GAITS["walk"]["arm_add"] = 8
    acts = {}
    for gname, g in CA.GAITS.items():
        acts[gname], _ = CA.bake_action(arm, rig, "Woody_" + gname.capitalize(), "gait", g["T"], g, True)
    acts["idle"], _ = CA.bake_action(arm, rig, "Woody_Idle", "idle", 120, None, True)
    acts["jump"], _ = CA.bake_action(arm, rig, "Woody_Jump", "jump", 46, None, False)
    log("actions baked: %s" % ", ".join(a.name for a in acts.values()))
    if not ARGS.no_verify:
        log("verification (treadmill frame, ground contact = sole point < 6 mm):")
        for gname in ("walk", "run", "sprint"):
            CA.verify_gait(arm, rig, gname, CA.GAITS[gname], acts[gname], log)
    if ARGS.test_controller:
        import char_controller as CTL
        log("controller self-test:")
        CTL.selftest(arm, rig, log)
        arm.location = (0, 0, 0)
        arm.rotation_euler = (0, 0, 0)
        for pb in arm.pose.bones:
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.location = (0, 0, 0)
    show, show_len = CA.bake_showcase(arm, rig, log)
    show.name = "Woody_Showcase"
    acts["showcase"] = show
    for a in list(bpy.data.actions):                 # the showcase blends from the gait functions; nothing else should be left over
        if a.name.startswith("Male_"):
            bpy.data.actions.remove(a)
    poses = [x for x in ARGS.poses.split(",") if x]
    if poses:
        cams = {"side": CA.make_ortho_cam(coll, "PoseSide", (8.0, 0.0, 1.0), (0.0, 0.0, 1.0), 2.25),
                "front": CA.make_ortho_cam(coll, "PoseFront", (0.0, -8.0, 1.0), (0.0, 0.0, 1.0), 2.25),
                "q34": make_cam("PoseQ", (3.2, -3.9, 1.3), (0, 0, 0.98), 52, coll)}
        for item in poses:
            an, fr, vw = item.split(":")
            arm.animation_data.action = acts[an]
            sc.camera = cams[vw]
            sc.render.resolution_x, sc.render.resolution_y = 720, 900
            sc.frame_set(int(fr) + 1)
            sc.render.filepath = os.path.join(ARGS.out, "pose_%s_%s_%s.png" % (an, fr, vw))
            bpy.ops.render.render(write_still=True)
            log("  pose", item)
        arm.animation_data.action = None
    if ARGS.sheets:
        cam_s = CA.make_ortho_cam(coll, "SheetSide", (8.0, 0.0, 1.0), (0.0, 0.0, 1.0), 2.25)
        cam_f = CA.make_ortho_cam(coll, "SheetFront", (0.0, -8.0, 1.0), (0.0, 0.0, 1.0), 2.25)
        sc.cycles.samples = 14
        CA.SHEET_W = ARGS.sheet_w
        plan = {"walk": [round(i * CA.GAITS["walk"]["T"] / 8) for i in range(8)],
                "run": [round(i * CA.GAITS["run"]["T"] / 8) for i in range(8)],
                "sprint": [round(i * CA.GAITS["sprint"]["T"] / 8) for i in range(8)],
                "jump": [0, 6, 10, 13, 18, 24, 30, 33, 38, 45]}
        only = [x for x in ARGS.sheet_only.split(",") if x]
        for gname, frames in plan.items():
            if only and gname not in only:
                continue
            CA.render_sheet(arm, acts[gname], frames, os.path.join(ARGS.out, "sheet_%s_side.png" % gname), cam_s, log)
            if gname in ("walk", "run"):
                CA.render_sheet(arm, acts[gname], frames, os.path.join(ARGS.out, "sheet_%s_front.png" % gname), cam_f, log)
    # leave the file ready to play: showcase on the rig, checker track, chase camera
    arm.animation_data.action = show
    sc.frame_start, sc.frame_end = 1, show_len + 1
    sc.frame_set(1)
    for o in list(coll.objects):
        if o.name == "Studio_Floor":
            bpy.data.objects.remove(o)
    CA.make_track_floor(coll)
    cam = bpy.data.objects.new("Cam_Follow", bpy.data.cameras.new("Cam_Follow"))
    coll.objects.link(cam)
    cam.data.lens = 45
    cam.parent = arm
    cam.location = (3.6, -1.2, 1.25)
    cam.rotation_euler = (Vector((0.0, 0.0, 1.0)) - Vector((3.6, -1.2, 1.25))).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = 1280, 720
    sc.cycles.samples = ARGS.samples
    return acts


# ------------------------------------------------------------------------------------------------------ web export
BAKE_RES = {"Head": 1024, "Shirt": 1024, "Vest": 1024, "Jeans": 512, "Hat": 512, "Hair": 512, "Skin": 512, "Bandana": 512, "Boots": 512,
            "Eye_L": 256, "Eye_R": 256, "Mouth": 256, "Eyelids": 256, "Collar": 256}
WEB_LOOK = {"Eye_L": (0.15, 0.0), "Eye_R": (0.15, 0.0), "Badge": (0.3, 0.9), "Head": (0.5, 0.0), "Skin": (0.5, 0.0), "Eyelids": (0.5, 0.0),
            "Mouth": (0.4, 0.0), "Boots": (0.5, 0.0)}


def export_web(arm, objs, path):
    """glTF for the web: modifiers applied (subsurf / solidify, weights kept), each object's procedural colours baked into one
    diffuse texture on a smart-project UV, one simple material per object, the five locomotion actions."""
    for d in (HERE, os.path.join(HERE, "enoden-walk", "blender")):
        if d not in sys.path:
            sys.path.append(d)
    import bake_tex
    sc = bpy.context.scene
    sc.cycles.device = "CPU"
    sc.cycles.samples = 2
    if arm.animation_data:
        arm.animation_data.action = None
    arm.location = (0, 0, 0)
    for pb in arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
    tex_dir = os.path.join(os.path.dirname(path), "_woody_tex") if not ARGS.out else os.path.join(ARGS.out, "web_tex")
    os.makedirs(tex_dir, exist_ok=True)
    for name, ob in objs.items():
        arm_mods = [m for m in ob.modifiers if m.type == "ARMATURE"]
        for m in arm_mods:
            m.show_viewport = False
        dg = bpy.context.evaluated_depsgraph_get()
        me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
        for m in list(ob.modifiers):
            if m.type != "ARMATURE":
                ob.modifiers.remove(m)
        mats = [s_.material for s_ in ob.material_slots]
        ob.data = me
        if len(me.materials) == 0:
            for m in mats:
                me.materials.append(m)
        for m in arm_mods:
            m.show_viewport = True
        for p_ in me.polygons:
            p_.use_smooth = True
        # bake every slot of the object into one image
        res = BAKE_RES.get(name, 256)
        bake_tex.smart_unwrap(ob)
        img = bpy.data.images.new("bake_" + name, res, res, alpha=False)
        nodes = []
        for m in {s_.material for s_ in ob.material_slots if s_.material}:
            nt = m.node_tree
            for n in nt.nodes:
                n.select = False
                if n.type == "BSDF_PRINCIPLED":
                    n.inputs["Metallic"].default_value = 0.0                     # the diffuse colour of a metal bakes black otherwise
            tn = nt.nodes.new("ShaderNodeTexImage")
            tn.image = img
            tn.select = True
            nt.nodes.active = tn
            nodes.append((nt, tn))
        for o in bpy.context.view_layer.objects:
            o.select_set(o is ob)
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, margin=16, use_clear=True)
        png = os.path.join(tex_dir, "woody_%s.png" % name.lower())
        bake_tex._write_png(png, res, res, img.pixels[:], srgb=False)          # a byte image already holds sRGB values
        for nt, tn in nodes:
            nt.nodes.remove(tn)
        bpy.data.images.remove(img)
        rough, metal = WEB_LOOK.get(name, (0.72, 0.0))
        wm = bpy.data.materials.new("W_Woody_" + name)
        wm.use_nodes = True
        nt = wm.node_tree
        nt.nodes.clear()
        b = nt.nodes.new("ShaderNodeBsdfPrincipled")
        o = nt.nodes.new("ShaderNodeOutputMaterial")
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(png)
        nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
        nt.links.new(b.outputs["BSDF"], o.inputs["Surface"])
        b.inputs["Roughness"].default_value = rough
        b.inputs["Metallic"].default_value = metal
        me.materials.clear()
        me.materials.append(wm)
        for p_ in me.polygons:
            p_.material_index = 0
        log("web bake: %-8s %4d px, %d verts" % (name, res, len(me.vertices)))
    for a in list(bpy.data.actions):
        if a.name not in ("Woody_Idle", "Woody_Walk", "Woody_Run", "Woody_Sprint", "Woody_Jump"):
            bpy.data.actions.remove(a)
    bpy.ops.object.select_all(action="DESELECT")
    for o in [arm] + list(objs.values()):
        o.select_set(True)
    bpy.context.view_layer.objects.active = arm
    valid = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    want = {"filepath": path, "export_format": "GLB", "use_selection": True, "export_animations": True, "export_animation_mode": "ACTIONS",
            "export_apply": False, "export_yup": True, "export_texcoords": True, "export_normals": True, "export_image_format": "JPEG",
            "export_jpeg_quality": 88, "export_materials": "EXPORT", "export_force_sampling": True, "export_optimize_animation_size": True,
            "export_skins": True, "export_draco_mesh_compression_enable": True, "export_draco_mesh_compression_level": 7,
            "export_draco_position_quantization": 14, "export_draco_normal_quantization": 8, "export_draco_generic_quantization": 12,
            "export_draco_texcoord_quantization": 12}
    bpy.ops.export_scene.gltf(**{k: v for k, v in want.items() if k in valid})
    log("web glb: %s (%.2f MB)" % (path, os.path.getsize(path) / 1e6))


def main():
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    coll = bpy.data.collections.new("Woody")
    bpy.context.scene.collection.children.link(coll)
    arm, objs, segs = assemble(coll)
    if ARGS.stage == "build":
        return
    studio(coll, ARGS.res)
    if ARGS.stage == "rest":
        render_views(coll, [v for v in ARGS.views.split(",") if v], ARGS.out)
    else:
        run_anim(arm, objs, coll)
    if ARGS.save:
        os.makedirs(ARGS.out, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(ARGS.out, "woody.blend"))
        log("saved woody.blend")
    if ARGS.glb:
        import char_anim as CA
        CA.export_glb(arm, objs, os.path.join(ARGS.out, "woody.glb"), log)
    if ARGS.web_glb:
        export_web(arm, objs, os.path.abspath(ARGS.web_glb))


main()
