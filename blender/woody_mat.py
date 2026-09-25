"""Materials for Woody.  Patterns (plaid, cow spots, hair streaks) read the per-vertex attribute 'rest' (rest-pose position, metres) that
woody.make_obj writes, so they stay glued to the deforming cloth and keep a real-world scale."""
import char_mat as CM
from char_mat import NG


def rest(g):
    a = g.n("ShaderNodeAttribute", attribute_type="GEOMETRY", attribute_name="rest")
    return a.outputs["Vector"]


def skin(name="MAT_Woody_Skin"):
    """Painted-vinyl skin: warm peach, pink cheeks (attribute cheek), dark lash line on the lids (attribute lash)."""
    g = NG(name)
    base = g.mix(g.noise(6.0, 2.0, 0.5, vec=rest(g)), "#EBAE86", "#E5A57E")
    base = g.mix(g.math("MULTIPLY", g.attr("cheek"), 0.8), base, "#E0766A")
    base = g.mix(g.attr("lash"), base, "#4A2E22")
    b = g.principled(base, 0.0, 0.40, spec=0.5, sss=0.10, sss_scale=0.008, coat=0.12, coat_rough=0.3)
    b.inputs["Subsurface Radius"].default_value = (1.0, 0.45, 0.3)
    g.put(b.inputs["Normal"], g.bump(g.noise(180.0, 2.0, 0.5, vec=rest(g)), 0.03, 0.0005))
    return g.finish(b.outputs["BSDF"])


def eye(name="MAT_Woody_Eye"):
    """Attribute eyedot = cos(angle from the gaze): black pupil, brown iris, white sclera, glossy coat."""
    g = NG(name)
    d = g.attr("eyedot")
    iris = g.ramp(d, [(0.855, "#2A1406"), (0.905, "#8A4F22"), (0.955, "#4E2A12")])
    col = g.mix(g.mapr(d, 0.848, 0.858, 0.0, 1.0), "#F7F5F0", iris)
    col = g.mix(g.mapr(d, 0.955, 0.962, 0.0, 1.0), col, "#080504")
    b = g.principled(col, 0.0, 0.25, spec=0.5, coat=1.0, coat_rough=0.03)
    return g.finish(b.outputs["BSDF"])


def mouth(name="MAT_Woody_Mouth"):
    g = NG(name)
    v = g.attr("mouthv")
    col = g.mix(g.mapr(v, 0.34, 0.16, 0.0, 1.0), "#3A0E0E", "#B24B4E")          # tongue at the bottom
    col = g.mix(g.mapr(v, 0.60, 0.66, 0.0, 1.0), col, "#F3EFE6")                # upper teeth
    b = g.principled(col, 0.0, 0.3, spec=0.5)
    return g.finish(b.outputs["BSDF"])


def plaid(name="MAT_Woody_Shirt"):
    """Yellow shirt with thin red-brown check lines (4.5 cm) and a faint wider band in between."""
    g = NG(name)
    x, y, z = g.sep(rest(g))
    u = g.math("ADD", x, g.math("MULTIPLY", y, 0.7))

    def line(val, period, width, offset=0.0):
        f = g.math("FRACT", g.math("DIVIDE", g.math("ADD", val, offset), period))
        dist = g.math("MINIMUM", f, g.math("SUBTRACT", 1.0, f))
        return g.mapr(dist, width, width * 0.55, 0.0, 1.0)
    thin = g.math("MAXIMUM", line(u, 0.045, 0.045), line(z, 0.045, 0.045))
    wide = g.math("MAXIMUM", line(u, 0.045, 0.16, 0.0225), line(z, 0.045, 0.16, 0.0225))
    col = g.mix(g.math("MULTIPLY", wide, 0.35), "#EFC743", "#E0A537")
    col = g.mix(g.math("MULTIPLY", thin, 0.9), col, "#B8452A")
    b = g.principled(col, 0.0, 0.8, sheen=0.4, sheen_rough=0.5, spec=0.35)
    g.put(b.inputs["Normal"], g.bump(g.noise(900.0, 2.0, 0.5, vec=rest(g)), 0.08, 0.0005))
    return g.finish(b.outputs["BSDF"])


def cowhide(name="MAT_Woody_Vest"):
    """White hide with big irregular black spots."""
    g = NG(name)
    r = rest(g)
    n = g.noise(4.2, 2.2, 0.45, vec=r, distortion=0.35)
    spot = g.mapr(n, 0.540, 0.552, 0.0, 1.0)
    col = g.mix(spot, "#EEEAE0", "#141210")
    fur = g.noise(700.0, 3.0, 0.6, vec=r)
    b = g.principled(col, 0.0, 0.78, sheen=0.7, sheen_rough=0.4, spec=0.3)
    g.put(b.inputs["Normal"], g.bump(fur, 0.12, 0.0006))
    return g.finish(b.outputs["BSDF"])


def hair(name="MAT_Woody_Hair"):
    g = NG(name)
    x, y, z = g.sep(rest(g))
    streak = g.noise(1.0, 3.0, 0.6, vec=g.combine(g.math("MULTIPLY", x, 160.0), g.math("MULTIPLY", y, 160.0), g.math("MULTIPLY", z, 20.0)))
    col = g.mix(g.mapr(streak, 0.35, 0.7, 0.0, 1.0), "#5A2A12", "#7C3F1E")
    b = g.principled(col, 0.0, 0.5, spec=0.5, coat=0.1)
    g.put(b.inputs["Normal"], g.bump(streak, 0.25, 0.0006))
    return g.finish(b.outputs["BSDF"])


def bandana(name="MAT_Woody_Bandana"):
    """Red with small white polka dots (a 3-D dot lattice on the rest position, 1.6 cm)."""
    g = NG(name)
    r = g.mapping(rest(g), scale=(1 / 0.016, 1 / 0.016, 1 / 0.016))
    x, y, z = g.sep(r)

    def cell(v):
        return g.math("SUBTRACT", g.math("FRACT", v), 0.5)
    cx, cy, cz = cell(x), cell(y), cell(z)
    d = g.math("SQRT", g.math("ADD", g.math("ADD", g.math("MULTIPLY", cx, cx), g.math("MULTIPLY", cy, cy)), g.math("MULTIPLY", cz, cz)))
    dot = g.mapr(d, 0.30, 0.26, 0.0, 1.0)
    col = g.mix(dot, "#C2202A", "#F4EEE6")
    b = g.principled(col, 0.0, 0.75, sheen=0.5, sheen_rough=0.5, spec=0.35)
    return g.finish(b.outputs["BSDF"])


def felt(name, color, color2):
    g = NG(name)
    col = g.mix(g.noise(9.0, 3.0, 0.55, vec=rest(g)), color, color2)
    b = g.principled(col, 0.0, 0.72, sheen=0.5, sheen_rough=0.4, spec=0.35)
    g.put(b.inputs["Normal"], g.bump(g.noise(500.0, 3.0, 0.6, vec=rest(g)), 0.10, 0.0005))
    return g.finish(b.outputs["BSDF"])


def make_all():
    M = {}
    M["skin"] = skin()
    M["eye"] = eye()
    M["mouth"] = mouth()
    M["lipline"] = CM.plain("MAT_Woody_LipLine", "#9C5446", 0.45)
    M["brow"] = CM.plain("MAT_Woody_Brow", "#3A2213", 0.6)
    M["hair"] = hair()
    M["hat"] = felt("MAT_Woody_Hat", "#7A3A1C", "#6A3016")
    M["hatstitch"] = CM.plain("MAT_Woody_HatStitch", "#D8B27A", 0.6)
    M["trim"] = CM.fabric("MAT_Woody_VestTrim", "#ECE8DE", 0.8, 900.0, 0.4)
    M["hatband"] = CM.leather("MAT_Woody_HatBand", "#3E2010", 0.5)
    M["shirt"] = plaid()
    M["cuff"] = CM.fabric("MAT_Woody_Cuff", "#E9BF3E", 0.8, 1500.0, 0.4)
    M["vest"] = cowhide()
    M["bandana"] = bandana()
    M["jeans"] = CM.fabric("MAT_Woody_Jeans", "#3F5F95", 0.85, 1500.0, 0.3, twill=True, color2="#34507F")
    M["belt"] = CM.leather("MAT_Woody_Belt", "#5A361D", 0.45)
    M["gold"] = CM.metal("MAT_Woody_Gold", "#D8AE52", 0.25)
    M["holster"] = CM.leather("MAT_Woody_Holster", "#744624", 0.45)
    M["boot"] = CM.leather("MAT_Woody_Boot", "#8A5530", 0.4)
    M["sole"] = CM.plain("MAT_Woody_Sole", "#3A2415", 0.6)
    M["stitch"] = CM.plain("MAT_Woody_Stitch", "#D9A868", 0.6)
    M["ring"] = CM.plain("MAT_Woody_PullRing", "#F1EFEA", 0.3)
    return M
