"""Enoden scene -> web assets (glTF / Draco + small JSON / binary side files), called from enoden_kamakurakokomae.py with --web-export DIR.

Procedural node materials cannot travel through glTF, so this module
  * estimates one flat colour per material (average of the constants upstream of the Principled base colour),
  * bakes the colour of the terrain and of the PLATEAU buildings into a vertex-colour layer (glTF multiplies it with the white base colour),
  * drops the heavy scatter objects (trees, leaf cards, grass ...) -- the web viewer instances low-poly trees from trees.json,
  * merges the static meshes per collection (few draw calls) but keeps the alarm lamps, the barrier arms and the train separate,
  * bakes a 1 m walkable height grid (ground.bin) and writes meta.json (spawn, landmarks, crossing / train data).

Output:  world.glb  train.glb  ground.bin  trees.json  meta.json  (coordinates in glTF space: x = Blender x, y = Blender z, z = -Blender y)"""
import json
import math
import os
import random
import struct

import bpy
from mathutils import Euler, Matrix, Vector
from mathutils.bvhtree import BVHTree

SKIP_PREFIX = ("Trees_", "Shrubs_", "Grass_", "Leaf_Litter", "Weeds_", "Ocean", "Headlight", "Tactile_Domes", "Cemetery_Gravestones", "Cemetery_Sotoba",
               "Focus_", "Cam", "Rig_Male20s", "Body", "Head", "Lips", "Eyelids", "Brows", "Eyeball", "Cornea", "Hair", "Shirt", "Trousers", "Sneakers", "Watch",
               "Enoden_1000")
SKIP_COLLECTIONS = ("P5_Character", "P4_Cameras", "P1_Trees", "P1_Ocean")
WALK_NAMES = ("Terrain_PLATEAU_DEM", "Roads_Asphalt", "Lanes_Hillside", "Sidewalk_Concrete", "Platform", "Crossing_Rubber_Boards", "Tactile_Base", "Ballast_Bed")
NUDGE_PREFIX = ("Road_Paint", "Road_Centre", "Paint_", "Manholes", "Kerb_Grates", "Crossing_Rubber_Boards", "Tactile_Base")


def lin(h):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    f = lambda v: v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return (f(c[0]), f(c[1]), f(c[2]))


def ramp_pick(stops, t):
    """Constant colour ramp: last stop whose position <= t."""
    col = stops[0][1]
    for pos, c in stops:
        if t >= pos:
            col = c
    return lin(col)


HOUSE = [(0.0, "#E4DED0"), (0.14, "#CFC7B6"), (0.28, "#BFC6C8"), (0.42, "#E0D2B8"), (0.56, "#B3A99C"), (0.7, "#E9E9E4"), (0.84, "#C7B296"), (0.95, "#A8B4A4")]
PLASTER = [(0.0, "#E1DACB"), (0.5, "#C9BFAE"), (0.8, "#DAD7CE")]
ROOF = [(0.0, "#454A50"), (0.2, "#6B3E37"), (0.4, "#33504E"), (0.6, "#2A2C30"), (0.8, "#5A4A3E"), (0.92, "#7A7F86")]


# ------------------------------------------------------------------------------------------------------ colour estimation
def _upstream(sock, depth=0):
    if depth > 9:
        return []
    if not sock.is_linked:
        dv = getattr(sock, "default_value", None)
        try:
            if dv is not None and len(dv) >= 3:
                return [tuple(dv[:3])]
        except TypeError:
            pass
        return []
    cols = []
    for lk in sock.links:
        n = lk.from_node
        if n.type == "VALTORGB":
            cols += [tuple(e.color[:3]) for e in n.color_ramp.elements]
        elif n.type == "RGB":
            cols.append(tuple(n.outputs[0].default_value[:3]))
        else:
            for inp in n.inputs:
                if inp.type == "RGBA" and inp.enabled:
                    cols += _upstream(inp, depth + 1)
    return cols


def est_material(mat):
    """-> dict(color, rough, metal, alpha, emit)"""
    out = dict(color=(0.6, 0.6, 0.6), rough=0.7, metal=0.0, alpha=1.0, emit=0.0)
    if mat is None:
        return out
    d = mat.diffuse_color
    out["color"] = (d[0], d[1], d[2])
    if not mat.use_nodes:
        return out
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    emi = next((n for n in nt.nodes if n.type == "EMISSION"), None)
    if bsdf is not None:
        cols = _upstream(bsdf.inputs["Base Color"])
        if cols:
            out["color"] = tuple(sum(c[i] for c in cols) / len(cols) for i in range(3))
        for key, nm in (("rough", "Roughness"), ("metal", "Metallic")):
            s = bsdf.inputs[nm]
            if not s.is_linked:
                out[key] = float(s.default_value)
            elif key == "rough":
                out[key] = 0.7
        a = bsdf.inputs["Alpha"]
        if not a.is_linked and a.default_value < 0.99:
            out["alpha"] = float(a.default_value)
        tw = bsdf.inputs.get("Transmission Weight")
        if tw is not None and not tw.is_linked and tw.default_value > 0.5:
            out["alpha"] = 0.3
    if emi is not None:
        st = emi.inputs["Strength"]
        if not st.is_linked and st.default_value > 0.5 and (bsdf is None or "Lamp" in mat.name or "Alarm" in mat.name or "Glow" in mat.name or "Fluor" in mat.name):
            c = emi.inputs["Color"].default_value
            out["color"] = (c[0], c[1], c[2])
            out["emit"] = min(3.0, float(st.default_value) / 3.0)
    n = mat.name
    if "Glass" in n or "Mirror" in n:
        out["alpha"] = min(out["alpha"], 0.45 if "Mirror" not in n else 1.0)
        out["rough"] = 0.05
    return out


_WEB_MATS = {}


def web_material(orig, white=False):
    key = (orig.name if orig else "None") + ("#w" if white else "")
    if key in _WEB_MATS:
        return _WEB_MATS[key]
    e = est_material(orig)
    m = bpy.data.materials.new("W_" + key)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(b.outputs["BSDF"], o.inputs["Surface"])
    c = (1.0, 1.0, 1.0) if white else e["color"]
    b.inputs["Base Color"].default_value = (c[0], c[1], c[2], 1.0)
    b.inputs["Roughness"].default_value = max(0.25, e["rough"])
    b.inputs["Metallic"].default_value = e["metal"]
    b.inputs["Alpha"].default_value = e["alpha"]
    if e["emit"] > 0:
        b.inputs["Emission Color"].default_value = (e["color"][0], e["color"][1], e["color"][2], 1.0)
        b.inputs["Emission Strength"].default_value = e["emit"]
    if e["alpha"] < 0.99:
        for attr, val in (("blend_method", "BLEND"), ("surface_render_method", "BLENDED")):
            try:
                setattr(m, attr, val)
            except Exception:
                pass
    _WEB_MATS[key] = m
    return m


# ------------------------------------------------------------------------------------------------------ vertex colours
def set_corner_colors(me, flat):
    for old in list(me.color_attributes):
        me.color_attributes.remove(old)
    ca = me.color_attributes.new("WebCol", "FLOAT_COLOR", "CORNER")
    ca.data.foreach_set("color", flat)
    me.color_attributes.active_color = ca
    me.color_attributes.render_color_index = 0


def white_colors(ob):
    me = ob.data
    n = len(me.loops)
    set_corner_colors(me, [1.0, 1.0, 1.0, 1.0] * n)


def bake_terrain(ob):
    me = ob.data
    nv = len(me.vertices)
    aw = {k: me.attributes.get(k) for k in ("w_sand", "w_grass", "w_soil")}
    vals = {}
    for k, a in aw.items():
        arr = [0.0] * nv
        if a:
            a.data.foreach_get("value", arr)
        vals[k] = arr
    rnd = random.Random(5)
    sand, grass, soil, rock = lin("#B8A67C"), lin("#5E6B2C"), lin("#6A6258"), lin("#66653A")
    grass_b = lin("#7E8036")
    cv = []
    for i, v in enumerate(me.vertices):
        ws, wg, wso = vals["w_sand"][i], vals["w_grass"][i], vals["w_soil"][i]
        t = rnd.random()
        g = tuple(grass[k] + (grass_b[k] - grass[k]) * t * 0.7 for k in range(3))
        base = tuple(g[k] * (1 - ws) + sand[k] * ws for k in range(3))
        base = tuple(base[k] * (1 - wso * 0.6) + soil[k] * wso * 0.6 for k in range(3))
        steep = max(0.0, min(1.0, (0.86 - v.normal.z) / 0.2))
        base = tuple(base[k] * (1 - steep * (1 - ws)) + rock[k] * steep * (1 - ws) for k in range(3))
        cv.append(base)
    flat = []
    for p in me.polygons:
        for li in p.loop_indices:
            c = cv[me.loops[li].vertex_index]
            flat += [c[0], c[1], c[2], 1.0]
    set_corner_colors(me, flat)


def bake_buildings(ob):
    me = ob.data
    nf = len(me.polygons)

    def arr(name):
        a = me.attributes.get(name)
        v = [0.0] * nf
        if a:
            a.data.foreach_get("value", v)
        return v
    br, kd, rf = arr("brand"), arr("bkind"), arr("rflat")
    flat = []
    for i, p in enumerate(me.polygons):
        mi = p.material_index
        if mi == 0:
            k = int(round(kd[i]))
            if k == 1:
                col = lin("#8E4B33") if br[i] < 0.62 else ramp_pick(PLASTER, br[i])
            elif k == 2:
                col = lin("#C8C9C6")
            else:
                col = ramp_pick(HOUSE, br[i])
        elif mi == 1:
            col = lin("#7C7D7B") if rf[i] > 0.5 else ramp_pick(ROOF, br[i])
        elif mi == 2:
            col = lin("#D8D6CF")
        else:
            col = lin("#8FADB4")
        for _ in p.loop_indices:
            flat += [col[0], col[1], col[2], 1.0]
    set_corner_colors(me, flat)


# ------------------------------------------------------------------------------------------------------ helpers
def is_skipped(ob):
    if ob.name not in bpy.context.view_layer.objects:              # instancing templates (Rock0 ...) live outside the view layer
        return True
    if any(ob.name.startswith(p) for p in SKIP_PREFIX):
        return True
    return any(c.name in SKIP_COLLECTIONS for c in ob.users_collection)


def to_mesh_objects():
    """Convert CURVE / FONT objects to meshes."""
    for ob in list(bpy.data.objects):
        if ob.type in ("CURVE", "FONT") and not is_skipped(ob):
            bpy.ops.object.select_all(action="DESELECT")
            ob.select_set(True)
            bpy.context.view_layer.objects.active = ob
            try:
                bpy.ops.object.convert(target="MESH")
            except Exception as e:
                print("convert failed", ob.name, e)


def three_matrix(M):
    C = Matrix(((1, 0, 0), (0, 0, 1), (0, -1, 0)))
    return C @ M.to_3x3() @ C.transposed()


def gltf_kwargs(path, use_draco=True):
    valid = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    want = {"filepath": path, "export_format": "GLB", "use_selection": True, "export_apply": True, "export_yup": True, "export_cameras": False,
            "export_lights": False, "export_extras": False, "export_texcoords": False, "export_normals": True, "export_vertex_color": "ACTIVE",
            "export_all_vertex_colors": False, "export_active_vertex_color_when_no_material": True, "export_attributes": False,
            "export_image_format": "NONE", "export_materials": "EXPORT", "export_draco_mesh_compression_enable": use_draco,
            "export_draco_mesh_compression_level": 7, "export_draco_position_quantization": 14, "export_draco_normal_quantization": 8,
            "export_draco_color_quantization": 8, "export_draco_generic_quantization": 12}
    skipped = [k for k in want if k not in valid]
    if skipped:
        print("[web] gltf options not available:", skipped)
    return {k: v for k, v in want.items() if k in valid}


def export_objects(objs, path, draco=True):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.export_scene.gltf(**gltf_kwargs(path, draco))
    print("[web] %s: %d objects, %.2f MB" % (os.path.basename(path), len(objs), os.path.getsize(path) / 1e6))


# ------------------------------------------------------------------------------------------------------ main entry
def run(outdir, footprints, web_trees, cfg, log):
    os.makedirs(outdir, exist_ok=True)
    sc = bpy.context.scene
    to_mesh_objects()
    train = bpy.data.objects.get("Enoden_1000_TwoCar")            # its origin is the track centre; the cab end is at x = train_front_x
    dg0 = bpy.context.evaluated_depsgraph_get()
    walk_bvh = []
    for ob in bpy.data.objects:                                    # walkable surfaces (before anything is merged / renamed)
        if ob.type == "MESH" and (ob.name in WALK_NAMES or (ob.name.startswith("SeaWall") and "Railing" not in ob.name)):
            walk_bvh.append(BVHTree.FromObject(ob, dg0))
    for ob in bpy.data.objects:
        if ob.type == "MESH":
            for m in list(ob.modifiers):
                if m.type == "BEVEL":
                    ob.modifiers.remove(m)

    # ---- barrier arms: quaternions for the raised / lowered positions (three.js axes)
    arms = []
    for ob in bpy.data.objects:
        if ob.name.startswith("Barrier_Arm"):
            down = ob.matrix_world.to_quaternion()
            e = ob.rotation_euler.copy()
            up_e = (e[0], -1.40, e[2])
            upq = Euler(up_e, "XYZ").to_quaternion()
            d3, u3 = three_matrix(down.to_matrix()).to_quaternion(), three_matrix(upq.to_matrix()).to_quaternion()
            arms.append(dict(name=ob.name, down=[d3.x, d3.y, d3.z, d3.w], up=[u3.x, u3.y, u3.z, u3.w]))

    # ---- vertex colours + material replacement
    static = []
    special = []
    for ob in list(bpy.data.objects):
        if ob.type != "MESH" or is_skipped(ob):
            continue
        n = ob.name
        if n.startswith(NUDGE_PREFIX):
            ob.location.z += 0.03
        vc = False
        if n == "Terrain_PLATEAU_DEM":
            bake_terrain(ob)
            vc = True
        elif n == "Buildings_PLATEAU":
            bake_buildings(ob)
            vc = True
        else:
            white_colors(ob)
        for slot in ob.material_slots:
            slot.material = web_material(slot.material, white=vc)
        if n in ("Alarm_Lamps_ON", "Alarm_Lamps_OFF") or n.startswith("Barrier_"):
            special.append(ob)
        else:
            static.append(ob)
    if train is not None:
        for slot in train.material_slots:
            slot.material = web_material(slot.material)
    # alarm lamps: dedicated materials so that the viewer can swap them
    lamp_on = bpy.data.materials.new("LampBright")
    lamp_off = bpy.data.materials.new("LampDark")
    for m, col, em in ((lamp_on, (1.0, 0.08, 0.02), 4.0), (lamp_off, (0.18, 0.02, 0.02), 0.0)):
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        b = nt.nodes.new("ShaderNodeBsdfPrincipled")
        o = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(b.outputs["BSDF"], o.inputs["Surface"])
        b.inputs["Base Color"].default_value = (col[0], col[1], col[2], 1.0)
        b.inputs["Roughness"].default_value = 0.3
        if em > 0:
            b.inputs["Emission Color"].default_value = (col[0], col[1], col[2], 1.0)
            b.inputs["Emission Strength"].default_value = em
    for ob in special:
        if ob.name == "Alarm_Lamps_ON":
            ob.material_slots[0].material = lamp_on
        elif ob.name == "Alarm_Lamps_OFF":
            ob.material_slots[0].material = lamp_off

    # ---- merge the static meshes per collection
    groups = {}
    for ob in static:
        groups.setdefault(ob.users_collection[0].name if ob.users_collection else "misc", []).append(ob)
    merged = []
    for cname, objs in groups.items():
        objs = [o for o in objs if o.name in bpy.data.objects]
        if not objs:
            continue
        if len(objs) > 1 and not any(o.name == "Terrain_PLATEAU_DEM" for o in objs):
            bpy.ops.object.select_all(action="DESELECT")
            for o in objs:
                o.select_set(True)
            act = max(objs, key=lambda o: len(o.data.polygons))
            bpy.context.view_layer.objects.active = act
            bpy.ops.object.join()
            act.name = "Merged_" + cname
            merged.append(act)
        else:
            merged.extend(objs)
    world_objs = merged + special
    for o in bpy.data.objects:
        if o.type == "MESH" and o.parent is not None and o.name.startswith("Barrier_Reflector") and o not in world_objs:
            world_objs.append(o)
    export_objects(world_objs, os.path.join(outdir, "world.glb"))
    if train is not None:
        export_objects([train], os.path.join(outdir, "train.glb"))

    # ---- walkable height grid (1 m): highest hit of the walkable objects, blocked under buildings
    walk = walk_bvh
    x0, x1, y0, y1, step = -200.0, 300.0, -45.0, 200.0, 1.0
    nx, ny = int((x1 - x0) / step) + 1, int((y1 - y0) / step) + 1
    grid = [float("nan")] * (nx * ny)
    for j in range(ny):
        y = y0 + j * step
        for i in range(nx):
            x = x0 + i * step
            best = None
            for t in walk:
                h = t.ray_cast(Vector((x, y, 200.0)), Vector((0, 0, -1)), 400.0)
                if h[0] is not None and (best is None or h[0].z > best):
                    best = h[0].z
            if best is not None:
                grid[j * nx + i] = best
    blocked = 0
    for (bx0, bx1, by0, by1, poly) in footprints:
        i0, i1 = max(0, int((bx0 - 1 - x0) / step)), min(nx - 1, int((bx1 + 1 - x0) / step))
        j0, j1 = max(0, int((by0 - 1 - y0) / step)), min(ny - 1, int((by1 + 1 - y0) / step))
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                cx, cy = x0 + i * step, y0 + j * step
                for dx, dy in ((0, 0), (0.45, 0), (-0.45, 0), (0, 0.45), (0, -0.45)):
                    if _pip(cx + dx, cy + dy, poly):
                        if grid[j * nx + i] == grid[j * nx + i]:
                            blocked += 1
                        grid[j * nx + i] = float("nan")
                        break
    with open(os.path.join(outdir, "ground.bin"), "wb") as f:
        f.write(struct.pack("<%df" % len(grid), *grid))
    log("web: ground grid %d x %d (%d cells blocked by buildings)" % (nx, ny, blocked))

    # ---- trees (instanced in the viewer)
    tj = [[k, round(x, 2), round(z, 2), round(-y, 2), round(h, 2), round(w, 2), round(r, 2)] for (k, x, y, z, w, h, r) in web_trees]
    with open(os.path.join(outdir, "trees.json"), "w") as f:
        json.dump({"kinds": ["broad", "pine", "cedar", "shrub"], "trees": tj}, f, separators=(",", ":"))

    # ---- meta
    meta = {
        "coords": "three.js: x = Blender x, y = Blender z, z = -Blender y",
        "grid": {"x0": x0, "y0": y0, "step": step, "nx": nx, "ny": ny},
        "spawn": {"x": 3.6, "y": -5.2, "z": cfg["r134"]["walk_z"], "yaw_deg": 90.0},
        "sea_level": cfg["sea"]["z"],
        "sun": {"azimuth_deg": cfg["sun"]["rotation"], "elevation_deg": 12.0},
        "track": {"y": 0.0, "x0": -125.0, "x1": 125.0, "z": 0.0},
        "crossing": {"x": 0.0, "y": 0.0, "arms": arms},
        "poi": [
            {"name": "1号踏切", "x": 0.0, "y": 0.0},
            {"name": "鎌倉高校前駅", "x": -32.5, "y": 2.6},
            {"name": "国道134号", "x": 40.0, "y": -10.0},
            {"name": "相模湾の海岸", "x": 20.0, "y": -30.0},
            {"name": "丘の住宅街", "x": 10.0, "y": 60.0},
            {"name": "海沿いの歩道", "x": -60.0, "y": -16.5},
        ],
    }
    with open(os.path.join(outdir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    log("web: export finished ->", outdir)


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
