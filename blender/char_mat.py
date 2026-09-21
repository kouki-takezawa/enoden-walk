"""Procedural materials for the character (skin with subsurface, eye, hair, cloth, leather, rubber).  Textures use Generated coordinates so
they stay glued to the deforming meshes."""
import bpy
import math


def hexc(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return (f(r), f(g), f(b), 1.0)


class NG:
    def __init__(self, name):
        self.mat = bpy.data.materials.new(name)
        self.mat.use_nodes = True
        self.nt = self.mat.node_tree
        self.nt.nodes.clear()
        self.out = self.nt.nodes.new("ShaderNodeOutputMaterial")
        self._tc = None

    def n(self, idname, **props):
        nd = self.nt.nodes.new(idname)
        for k, v in props.items():
            try:
                setattr(nd, k, v)
            except Exception:
                pass
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

    def coord(self, kind="Generated"):
        if self._tc is None:
            self._tc = self.n("ShaderNodeTexCoord")
        return self._tc.outputs[kind]

    def uv(self):
        return self.coord("UV")

    def mapping(self, vec=None, scale=(1, 1, 1), loc=(0, 0, 0)):
        m = self.n("ShaderNodeMapping")
        self.put(m.inputs["Vector"], vec if vec is not None else self.coord())
        m.inputs["Scale"].default_value = scale
        m.inputs["Location"].default_value = loc
        return m.outputs["Vector"]

    def noise(self, scale, detail=3.0, rough=0.55, vec=None, distortion=0.0):
        nd = self.n("ShaderNodeTexNoise", noise_dimensions="3D")
        self.put(nd.inputs["Vector"], vec if vec is not None else self.coord())
        nd.inputs["Scale"].default_value = scale
        nd.inputs["Detail"].default_value = detail
        nd.inputs["Roughness"].default_value = rough
        nd.inputs["Distortion"].default_value = distortion
        return nd.outputs["Fac"]

    def sep(self, vec):
        s = self.n("ShaderNodeSeparateXYZ")
        self.put(s.inputs["Vector"], vec)
        return s.outputs["X"], s.outputs["Y"], s.outputs["Z"]

    def combine(self, x, y, z):
        c = self.n("ShaderNodeCombineXYZ")
        self.put(c.inputs["X"], x)
        self.put(c.inputs["Y"], y)
        self.put(c.inputs["Z"], z)
        return c.outputs["Vector"]

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

    def bump(self, height, strength=0.3, dist=0.01, normal=None):
        b = self.n("ShaderNodeBump")
        self.put(b.inputs["Height"], height)
        b.inputs["Strength"].default_value = strength
        b.inputs["Distance"].default_value = dist
        if normal is not None:
            self.put(b.inputs["Normal"], normal)
        return b.outputs["Normal"]

    def attr(self, name, out="Fac"):
        a = self.n("ShaderNodeAttribute", attribute_type="GEOMETRY", attribute_name=name)
        return a.outputs[out]

    def principled(self, base="#808080", metallic=0.0, rough=0.5, **kw):
        p = self.n("ShaderNodeBsdfPrincipled")
        self.put(p.inputs["Base Color"], base)
        self.put(p.inputs["Metallic"], metallic)
        self.put(p.inputs["Roughness"], rough)
        names = {"coat": "Coat Weight", "coat_rough": "Coat Roughness", "transmission": "Transmission Weight", "ior": "IOR",
                 "spec": "Specular IOR Level", "normal": "Normal", "sheen": "Sheen Weight", "sheen_rough": "Sheen Roughness",
                 "sss": "Subsurface Weight", "sss_radius": "Subsurface Radius", "sss_scale": "Subsurface Scale", "aniso": "Anisotropic",
                 "emit": "Emission Color", "emit_strength": "Emission Strength", "alpha": "Alpha"}
        for k, v in kw.items():
            self.put(p.inputs[names.get(k, k)], v)
        return p

    def finish(self, shader):
        self.nt.links.new(shader, self.out.inputs["Surface"])
        return self.mat


def _skin_core(g, head=False):
    """Skin BSDF.  Colours: East-Asian light-medium skin (warm, slightly yellow), pinker lips / lids / cheeks, pores + micro relief."""
    base = g.mix(g.noise(9.0, 4.0, 0.6), "#C48E69", "#BB855F")
    var = g.noise(3.0, 2.0, 0.5)
    base = g.mix(g.math("MULTIPLY", g.ramp(var, [(0.3, (0, 0, 0, 1)), (0.7, (1, 1, 1, 1))]), 0.35), base, "#A46B4C")
    if head:
        cheek = g.attr("cheek")
        base = g.mix(g.math("MULTIPLY", cheek, 0.24), base, "#C98474")
        eyer = g.attr("eyering")
        base = g.mix(g.math("MULTIPLY", eyer, 0.22), base, "#B98572")
        brow = g.attr("brow")
        base = g.mix(g.math("MULTIPLY", brow, 0.10), base, "#8A6650")
        nost = g.attr("nostril")
        base = g.mix(g.math("MULTIPLY", nost, 0.85), base, "#3A2019")
        lip = g.attr("lip")
        base = g.mix(g.math("MULTIPLY", lip, 0.92), base, "#8A4B44")
        # faint stubble shadow on chin / upper lip / jaw
        z = g.sep(g.coord())[2]
        stub = g.math("MULTIPLY", g.ramp(g.noise(700.0, 2.0, 0.5), [(0.55, (0, 0, 0, 1)), (0.8, (1, 1, 1, 1))]),
                      g.mapr(z, 0.32, 0.06, 0.0, 0.10))
        base = g.mix(stub, base, "#4E4038")
    pores = g.noise(520.0, 4.0, 0.62)
    wrink = g.noise(60.0, 3.0, 0.5)
    height = g.math("ADD", g.math("MULTIPLY", pores, 0.55), g.math("MULTIPLY", wrink, 0.45))
    rough = g.mapr(g.noise(30.0, 2.0, 0.5), 0.3, 0.7, 0.36, 0.55)
    if head:
        rough = g.math("SUBTRACT", rough, g.math("MULTIPLY", g.attr("lip"), 0.12))
    bsdf = g.principled(base, 0.0, rough, spec=0.5, sss=0.22, sss_scale=0.012, sheen=0.12, coat=0.0, ior=1.4)
    bsdf.inputs["Subsurface Radius"].default_value = (1.0, 0.36, 0.22)
    try:
        bsdf.subsurface_method = "RANDOM_WALK_SKIN"
    except Exception:
        try:
            bsdf.subsurface_method = "RANDOM_WALK"
        except Exception:
            pass
    g.put(bsdf.inputs["Normal"], g.bump(height, 0.10 if head else 0.08, 0.0006))
    return bsdf


def skin(name, head=False):
    g = NG(name)
    return g.finish(_skin_core(g, head).outputs["BSDF"])


def eyeball(name="MAT_Eye"):
    """Sclera + iris + pupil painted on the front hemisphere of a sphere using Generated coordinates (centre 0.5, front = -Y)."""
    g = NG(name)
    px, py, pz = g.sep(g.coord())
    dx, dy, dz = g.math("SUBTRACT", px, 0.5), g.math("SUBTRACT", py, 0.5), g.math("SUBTRACT", pz, 0.5)
    rr = g.math("SQRT", g.math("ADD", g.math("MULTIPLY", dx, dx), g.math("MULTIPLY", dz, dz)))
    rr = g.math("MULTIPLY", rr, 2.0)                                                     # 0 at the pole, 1 at the equator
    front = g.math("LESS_THAN", py, 0.5)
    ang = g.math("ARCTAN2", dz, dx)
    fib = g.noise(6.0, 3.0, 0.6, vec=g.combine(g.math("MULTIPLY", ang, 1.6), g.math("MULTIPLY", rr, 14.0), 0.0))
    iris_col = g.mix(g.ramp(fib, [(0.3, (0, 0, 0, 1)), (0.7, (1, 1, 1, 1))]), "#4A2C1A", "#7A4A28")
    iris_col = g.mix(g.mapr(rr, 0.18, 0.31, 1.0, 0.0), iris_col, "#241209")                 # dark pupil-side ring
    limbus = g.mapr(rr, 0.40, 0.46, 0.0, 1.0)
    iris_col = g.mix(limbus, iris_col, "#1A100A")
    is_iris = g.mapr(rr, 0.470, 0.445, 0.0, 1.0)
    is_pupil = g.mapr(rr, 0.19, 0.16, 0.0, 1.0)
    veins = g.ramp(g.noise(30.0, 5.0, 0.6), [(0.55, (0, 0, 0, 1)), (0.8, (1, 1, 1, 1))])
    sclera = g.mix(g.math("MULTIPLY", veins, 0.18), "#ECE5DE", "#C98F86")
    sclera = g.mix(g.mapr(rr, 0.55, 0.98, 0.0, 0.35), sclera, "#BFA9A0")                        # shading toward the lid corners
    col = g.mix(g.math("MULTIPLY", is_iris, front), sclera, iris_col)
    col = g.mix(g.math("MULTIPLY", is_pupil, front), col, "#050403")
    bsdf = g.principled(col, 0.0, 0.18, spec=0.6, coat=0.0)
    return g.finish(bsdf.outputs["BSDF"])


def cornea(name="MAT_Cornea"):
    g = NG(name)
    tr = g.n("ShaderNodeBsdfTransparent")
    gl = g.n("ShaderNodeBsdfGlossy")
    gl.inputs["Roughness"].default_value = 0.0
    mx = g.n("ShaderNodeMixShader")
    g.put(mx.inputs["Fac"], 0.10)
    g.nt.links.new(tr.outputs["BSDF"], mx.inputs[1])
    g.nt.links.new(gl.outputs["BSDF"], mx.inputs[2])
    return g.finish(mx.outputs["Shader"])


def hair(name="MAT_Hair", tint="#15100D"):
    g = NG(name)
    uv = g.sep(g.uv())
    lr = g.attr("lockrand")
    strand = g.noise(1.0, 1.0, 0.5, vec=g.combine(g.math("MULTIPLY", uv[0], 90.0), g.math("MULTIPLY", uv[1], 3.0), lr))
    col = g.mix(g.mapr(strand, 0.3, 0.7, 0.0, 1.0), tint, "#3B2A20")
    col = g.mix(g.mapr(lr, 0.0, 1.0, 0.0, 0.5), col, "#0B0807")
    bsdf = g.principled(col, 0.0, 0.34, spec=0.7, coat=0.25, coat_rough=0.25, aniso=0.0)
    g.put(bsdf.inputs["Normal"], g.bump(strand, 0.15, 0.0004))
    return g.finish(bsdf.outputs["BSDF"])


def hair_roots(name="MAT_HairRoots"):
    g = NG(name)
    return g.finish(g.principled("#0E0A08", 0.0, 0.7).outputs["BSDF"])


def brow(name="MAT_Brow"):
    g = NG(name)
    return g.finish(g.principled("#17110E", 0.0, 0.45, spec=0.5).outputs["BSDF"])


def fabric(name, color, rough=0.86, weave=1400.0, sheen=0.5, twill=False, color2=None):
    g = NG(name)
    col = color
    if color2:
        col = g.mix(g.noise(2.5, 3.0, 0.5), color, color2)
    if twill:
        x, y, z = g.sep(g.coord())
        diag = g.combine(g.math("MULTIPLY", g.math("ADD", x, z), weave * 0.05), 0.0, 0.0)
        wv = g.n("ShaderNodeTexWave", wave_type="BANDS", bands_direction="X")
        g.put(wv.inputs["Vector"], g.mapping(scale=(weave * 0.05, weave * 0.05, weave * 0.05)))
        wv.inputs["Scale"].default_value = 1.0
        wv.inputs["Distortion"].default_value = 0.6
        height = g.math("ADD", wv.outputs["Fac"], g.math("MULTIPLY", g.noise(weave * 0.3, 2.0, 0.5), 0.5))
    else:
        checker = g.n("ShaderNodeTexChecker")
        g.put(checker.inputs["Vector"], g.mapping(scale=(weave * 0.06, weave * 0.06, weave * 0.06)))
        checker.inputs["Scale"].default_value = 1.0
        height = g.math("ADD", checker.outputs["Fac"], g.math("MULTIPLY", g.noise(weave * 0.25, 2.0, 0.5), 0.6))
    fuzz = g.math("MULTIPLY", g.noise(12.0, 3.0, 0.6), 0.10)
    col = g.mix(fuzz, col, "#7F7F7C") if False else col
    bsdf = g.principled(col, 0.0, rough, sheen=sheen, sheen_rough=0.5, spec=0.35)
    g.put(bsdf.inputs["Normal"], g.bump(height, 0.12, 0.0006))
    return g.finish(bsdf.outputs["BSDF"])


def leather(name, color, rough=0.45):
    g = NG(name)
    grain = g.noise(380.0, 3.0, 0.6)
    bsdf = g.principled(color, 0.0, rough, spec=0.5, coat=0.15, coat_rough=0.3)
    g.put(bsdf.inputs["Normal"], g.bump(grain, 0.25, 0.0008))
    return g.finish(bsdf.outputs["BSDF"])


def rubber(name, color="#EDE7DA", rough=0.62):
    g = NG(name)
    dirt = g.mix(g.math("MULTIPLY", g.ramp(g.noise(30.0, 4.0, 0.6), [(0.5, (0, 0, 0, 1)), (0.85, (1, 1, 1, 1))]), 0.35), color, "#B5AA94")
    bsdf = g.principled(dirt, 0.0, rough, spec=0.4)
    g.put(bsdf.inputs["Normal"], g.bump(g.noise(220.0, 3.0, 0.6), 0.2, 0.0008))
    return g.finish(bsdf.outputs["BSDF"])


def metal(name, color="#B8BABD", rough=0.28):
    g = NG(name)
    return g.finish(g.principled(color, 1.0, rough).outputs["BSDF"])


def plain(name, color, rough=0.5, metallic=0.0):
    g = NG(name)
    return g.finish(g.principled(color, metallic, rough).outputs["BSDF"])
