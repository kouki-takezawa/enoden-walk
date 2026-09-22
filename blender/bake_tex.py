"""Phase B0: shared Cycles texture-baking helpers, used by the web export to turn this project's procedural
materials into real image textures instead of the single flat colour the export has always fallen back to.

Validated by a standalone smoke test before this was written (see the implementation plan): DIFFUSE(COLOR)/
ROUGHNESS/NORMAL baking all work in this headless Blender 5.2 build, but only on the CPU Cycles device — with a
GPU (or a misconfigured GPU: none was actually available here) the NORMAL pass silently comes back completely
flat (the neutral tangent-space value, R=G=0.5 B=1.0, zero variance) while DIFFUSE/ROUGHNESS still look fine, which
is a very easy failure to miss without checking pixel values. Bake device is therefore forced to CPU here,
independent of whatever `scene.cycles.device` the caller's final-render code path uses elsewhere.

The materials this project bakes (see build_materials() / char_mat.py) use Generated/object noise coordinates, not
UV, so the *shape* of the baked pattern does not depend on the UV layout — only the target mesh's own UV determines
where each part of the pattern lands. That is what makes it safe to bake onto a UV this project's meshes never had
before (smart_project) or onto a small disposable tile plane (bake_tile), without the material needing to "know"
about either.
"""
import os
import struct
import zlib
import bpy

SAMPLES = 24
MARGIN = 28  # margin dilation covers the *gap* left by island_margin below with extended edge colour, not a big
# empty area — too small leaves that gap showing the black clear colour, too large bleeds across it instead.
# Scales with bake resolution (currently 2048 in char_anim.py): a fixed pixel margin covers a smaller fraction of
# the gap as resolution goes up, so this was retuned alongside that increase, not in isolation.


def _write_png(path, width, height, pixels_rgba_float, srgb):
    """Encodes `pixels_rgba_float` (a flat float array, 0..1, RGBA, bottom-to-top as Blender's Image.pixels gives
    it) to an 8-bit PNG by hand, using only zlib/struct from the standard library.

    This exists because Image.save() / save_render() / the object.bake operator's save_mode='EXTERNAL' all proved
    unreliable for a `bpy.data.images.new()`-created bake target in this Blender build: bpy.ops.object.bake()
    demonstrably writes correct, per-material-distinct data into Image.pixels (verified against expected values
    while debugging this), but every built-in save path silently wrote a blank black file regardless of which
    image it was asked to save — every one of a batch of bakes ended up as byte-identical blank files despite
    correct, distinct in-memory pixel data, a state no combination of Image.pack()/.update()/explicit pixel
    reassignment/bpy.ops.image.save_as() with a context override/bake(save_mode='EXTERNAL') fixed. Given
    Image.pixels itself is proven correct, encoding it ourselves sidesteps whatever internal buffer this Blender
    build's save paths actually read from.
    """
    def to_srgb(v):
        return 1.055 * (v ** (1.0 / 2.4)) - 0.055 if v > 0.0031308 else 12.92 * v

    raw = bytearray()
    for y in range(height - 1, -1, -1):  # Blender's pixel buffer is bottom-to-top; PNG scanlines are top-to-bottom
        raw.append(0)  # filter type: None
        row_start = y * width * 4
        for x in range(width):
            o = row_start + x * 4
            r, g, b = pixels_rgba_float[o], pixels_rgba_float[o + 1], pixels_rgba_float[o + 2]
            if srgb:
                r, g, b = to_srgb(r), to_srgb(g), to_srgb(b)
            raw.append(max(0, min(255, int(r * 255.0 + 0.5))))
            raw.append(max(0, min(255, int(g * 255.0 + 0.5))))
            raw.append(max(0, min(255, int(b * 255.0 + 0.5))))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # bit depth 8, colour type 2 = RGB
    idat = zlib.compress(bytes(raw), 6)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", idat))
        f.write(chunk(b"IEND", b""))


def _prep_bake_scene():
    """Forces CPU for baking (see module docstring) and, importantly, a neutral Standard/no-look/zero-exposure view
    transform: save_render() below applies the scene's *view transform* the way a final render would, and this
    project's studio()/configure_render() set a filmic AgX grade for preview renders — baking through that would
    tone-map the diffuse texture and outright corrupt the roughness/normal passes, which are not colour data at
    all. Returns the previous (view_transform, look, exposure) to restore afterward."""
    scene = bpy.context.scene
    scene.cycles.device = "CPU"
    scene.cycles.samples = SAMPLES  # bake quality shouldn't depend on whatever sample count the caller's own preview/final render wants
    try:
        bpy.context.preferences.addons["cycles"].preferences.compute_device_type = "NONE"
    except Exception:
        pass
    vs = scene.view_settings
    prev = (vs.view_transform, vs.look, vs.exposure)
    vs.view_transform = "Standard"
    vs.look = "None"
    vs.exposure = 0.0
    return prev


def _restore_view_settings(prev):
    vs = bpy.context.scene.view_settings
    vs.view_transform, vs.look, vs.exposure = prev


def smart_unwrap(obj, angle_limit_deg=89.0, island_margin=0.05):
    """Adds a UV layer via smart_project for a mesh that has none (this project's procedural geometry mostly
    doesn't). Run on the object's *final* topology (post-modifier, e.g. after Subsurf has been applied) — fewer,
    cleaner islands than on the low-poly control cage. A HIGH angle_limit (fewer, bigger islands, more per-island
    UV stretch) is deliberate: the materials being baked are procedural/seamless in world space, so stretch just
    reallocates texel density unevenly (harmless) — but with the *small*, *many* islands a low angle_limit produces,
    the post-bake margin dilation bleeds one island's colour into its packed neighbours (visible as a jarring
    black/white blotch pattern on a first attempt at this), which is the worse problem to have here."""
    import math
    bpy.context.view_layer.objects.active = obj
    prev_mode = obj.mode
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    # Recalculate outward normals before baking: procedural geometry can carry stray inverted-normal faces
    # (common on thin/capped extremity geometry - fingers, arm caps), and Cycles bakes those as near-black
    # since the ray sees the surface from behind. Cheap and safe on a manifold-ish mesh either way.
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.uv.smart_project(angle_limit=math.radians(angle_limit_deg), island_margin=island_margin)
    bpy.ops.object.mode_set(mode=prev_mode if prev_mode != "EDIT" else "OBJECT")


def bake_to_uv(obj, mat, outdir, name_prefix, resolution=1024, passes=("diffuse", "roughness", "normal")):
    """Bakes `mat` (assumed already assigned to obj, which already has a UV layer) to `passes` and saves each as a
    PNG under outdir/{name_prefix}_{pass}.png. Returns {pass: filepath}. A temporary Image Texture node is added to
    the material for each pass and removed afterward (the node is never linked into the shader, so the material's
    real appearance is untouched) — the standard, non-destructive way to direct bpy.ops.object.bake's output."""
    prev_view = _prep_bake_scene()
    os.makedirs(outdir, exist_ok=True)
    nt = mat.node_tree
    bpy.context.view_layer.objects.active = obj
    for o in bpy.context.view_layer.objects:
        o.select_set(o is obj)
    out = {}
    try:
        for pass_name in passes:
            img = bpy.data.images.new(f"{name_prefix}_{pass_name}", resolution, resolution, alpha=False)
            node = nt.nodes.new("ShaderNodeTexImage")
            node.image = img
            for n in nt.nodes:
                n.select = False
            node.select = True
            nt.nodes.active = node
            if pass_name == "diffuse":
                bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, margin=MARGIN, use_clear=True)
            elif pass_name == "roughness":
                bpy.ops.object.bake(type="ROUGHNESS", margin=MARGIN, use_clear=True)
            elif pass_name == "normal":
                bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", margin=MARGIN, use_clear=True)
            else:
                raise ValueError(f"unknown bake pass {pass_name!r}")
            path = os.path.join(outdir, f"{name_prefix}_{pass_name}.png")
            _write_png(path, resolution, resolution, img.pixels[:], srgb=(pass_name == "diffuse"))
            nt.nodes.remove(node)
            bpy.data.images.remove(img)
            out[pass_name] = path
    finally:
        _restore_view_settings(prev_view)
    return out


def bake_tile(mat, outdir, name_prefix, tile_m=2.0, resolution=1024, passes=("diffuse", "roughness", "normal"), collection=None):
    """For materials that don't belong to any one mesh (generic props/surfaces): builds a disposable tile_m x
    tile_m plane with a simple [0,1] UV, assigns `mat`, bakes, then deletes the plane. The returned images are
    meant to be applied at runtime as a *repeating* texture (three.js RepeatWrapping) at 1 tile == tile_m metres,
    which composes with this project's existing world-position-based shaders without needing per-mesh UV at all."""
    coll = collection or bpy.context.scene.collection
    mesh = bpy.data.meshes.new(f"{name_prefix}_tile")
    half = tile_m / 2.0
    mesh.from_pydata(
        [(-half, -half, 0), (half, -half, 0), (half, half, 0), (-half, half, 0)],
        [], [(0, 1, 2, 3)],
    )
    mesh.update()
    uv = mesh.uv_layers.new(name="UVMap")
    uv.data.foreach_set("uv", [0, 0, 1, 0, 1, 1, 0, 1])
    ob = bpy.data.objects.new(f"{name_prefix}_tile", mesh)
    coll.objects.link(ob)
    ob.data.materials.append(mat)
    try:
        out = bake_to_uv(ob, mat, outdir, name_prefix, resolution=resolution, passes=passes)
    finally:
        bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.meshes.remove(mesh)
    return out
