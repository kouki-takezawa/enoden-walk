"""Armature (Mixamo-style humanoid names) and distance-based skin weights."""
import math
import bpy
import bmesh
from mathutils import Vector, Matrix
from char_core import *

SIDE = {"L": "Left", "R": "Right"}


def make_armature(coll, finger_defs):
    """finger_defs[side_name]['Index'] = [(head, tail) x3]  (world/rest coordinates).  Returns (armature object, dict bone -> (head, tail))."""
    data = bpy.data.armatures.new("Rig_Male20s")
    arm = bpy.data.objects.new("Rig_Male20s", data)
    coll.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    defs = bone_defs()
    segs = {}
    eb = data.edit_bones
    for name, (h, t, par, conn) in defs.items():
        b = eb.new(name)
        b.head, b.tail = Vector(h), Vector(t)
        if (b.tail - b.head).length < 0.01:
            b.tail = b.head + Vector((0, 0, 0.05))
        segs[name] = (Vector(b.head), Vector(b.tail))
    for name, (h, t, par, conn) in defs.items():
        if par:
            eb[name].parent = eb[par]
            eb[name].use_connect = bool(conn) and (eb[par].tail - eb[name].head).length < 1e-4
    # fingers
    for sn, sname in (("L", "Left"), ("R", "Right")):
        fd = finger_defs[sn]
        for finger, chain in fd.items():
            prev = sname + "Hand"
            for k, (h, t) in enumerate(chain, start=1):
                name = "%s%s%d" % (sname, finger, k)
                b = eb.new(name)
                b.head, b.tail = Vector(h), Vector(t)
                b.parent = eb[prev]
                b.use_connect = k > 1
                segs[name] = (Vector(h), Vector(t))
                prev = name
    for b in eb:
        b.use_deform = b.name != "Root"
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.show_in_front = True
    return arm, segs


def candidates(tag):
    if tag is None:
        return ["Hips"]
    if tag in ("torso", "shirt"):
        return ["Hips", "Spine", "Spine1", "Spine2", "Neck", "LeftShoulder", "RightShoulder", "LeftArm", "RightArm"]
    if tag == "pants_hip":
        return ["Hips", "Spine"]
    if tag == "neck":
        return ["Neck", "Head", "Spine2"]
    if tag == "head":
        return ["Head", "Neck"]
    if tag == "hair":
        return ["Head"]
    if tag.startswith("lids_") or tag.startswith("brow"):
        return ["Head"]
    kind, _, rest = tag.partition("_")
    if kind in ("arm", "sleeve"):
        S = SIDE[rest]
        return [S + "Shoulder", S + "Arm", S + "ForeArm", S + "Hand", "Spine2"]
    if kind == "watch":
        return [SIDE[rest] + "ForeArm"]
    if kind == "hand":
        S = SIDE[rest]
        return [S + "ForeArm", S + "Hand"]
    if kind == "finger":
        s, _, f = rest.partition("_")
        S = SIDE[s]
        return [S + "Hand"] + ["%s%s%d" % (S, f, k) for k in (1, 2, 3)]
    if kind in ("leg", "pants"):
        S = SIDE[rest]
        return ["Hips", S + "UpLeg", S + "Leg", S + "Foot"]
    if kind in ("foot", "shoe"):
        S = SIDE[rest]
        return [S + "Leg", S + "Foot", S + "Toe"]
    if kind == "eye":
        return [SIDE[rest] + "Eye"]
    return ["Hips"]


def seg_dist(p, a, b):
    ab = b - a
    t = clamp((p - a).dot(ab) / max(ab.dot(ab), 1e-9))
    return (p - (a + ab * t)).length, t


def skin_object(obj, arm, segs, mb, power=4.0, eps=0.012, max_inf=4, fixed=None):
    """Create vertex groups for every bone of `arm` on obj and weight the vertices by segment distance, limited to the tag's bone set."""
    for name in segs:
        obj.vertex_groups.new(name=name)
    gi = {vg.name: vg.index for vg in obj.vertex_groups}
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    dl = bm.verts.layers.deform.verify()
    bm.verts.ensure_lookup_table()
    cache = {}
    for i, v in enumerate(bm.verts):
        tag = mb.tag[i] if i < len(mb.tag) else None
        p = Vector(v.co)
        if fixed is not None:
            w = {fixed: 1.0}
        else:
            cand = cache.get(tag)
            if cand is None:
                cand = [b for b in candidates(tag) if b in segs]
                cache[tag] = cand
            ws = []
            for b in cand:
                a, t = segs[b]
                if b in ("Head",):
                    t = t + (t - a).normalized() * 0.5
                if b.endswith("Toe") or b.endswith("Hand"):
                    t = t + (t - a).normalized() * 0.1
                d, _ = seg_dist(p, a, t)
                wt = 1.0 / (d + eps) ** power
                if tag in ("torso", "shirt") and (b.endswith("Arm") or b.endswith("Shoulder")):
                    wt *= smoothstep(1.22, 1.33, p.z)                      # raising the arms must not drag the lower shirt / ribs
                ws.append((wt, b))
            ws.sort(reverse=True)
            ws = ws[:max_inf]
            tot = sum(w for w, _ in ws)
            w = {b: wv / tot for wv, b in ws}
        for b, wv in w.items():
            if wv > 0.004:
                v[dl][gi[b]] = wv
    bm.to_mesh(obj.data)
    bm.free()
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    mod.use_deform_preserve_volume = False
    obj.parent = arm
