#!/usr/bin/env python
"""
fetch_plateau.py  --  PLATEAU (Kamakura 2024) + OSM  ->  compact local JSON for the Blender scene.

Bakes the "background base" around the 鎌倉高校前1号踏切 into plateau_data/kamakura_koko.json so that
enoden_kamakurakokomae.py needs no network access:
  * terrain height-field  (PLATEAU dem TIN, rasterised to a regular grid)
  * buildings             (PLATEAU bldg, LOD2 when available else LOD1, split into wall/roof/ground polygons)
  * OSM reference lines   (Enoden track centre-line, level crossings, station platform, roads, coastline)

Local frame (matches the spec's master plan):
  origin  = point on the Enoden centre-line closest to the OSM node of the 1号踏切
  +X      = track direction toward 七里ヶ浜/鎌倉  (true bearing ~96 deg, measured from OSM)
  +Y      = left of +X  (uphill / mountain side, ~north)      -Y = sea side
  Z       = TP elevation minus the DEM height at the origin

Only the compressed parts of the 469 MB CityGML zip that are needed are downloaded (HTTP Range).
Data: Project PLATEAU (MLIT Japan, free to reuse incl. commercial; credit "3D都市モデル(Project PLATEAU)")
      (c) OpenStreetMap contributors, ODbL.

Usage:  python fetch_plateau.py [--cache DIR] [--out FILE] [--force]
"""
import argparse, io, json, math, os, re, sys, time, urllib.parse, urllib.request, zipfile
import xml.etree.ElementTree as ET
import numpy as np

ZIP_URL = ("https://assets.cms.plateau.reearth.io/assets/24/fdd285-69b7-4ded-acab-5182de9a966a/"
           "14204_kamakura-shi_city_2024_citygml_1_op.zip")
OVERPASS_MIRRORS = ["https://overpass-api.de/api/interpreter",
                    "https://overpass.kumi.systems/api/interpreter",
                    "https://overpass.private.coffee/api/interpreter"]
UA = "enoden-blender-modeling/1.0 (personal 3D project)"

# OSM node "鎌倉高校前1号踏切" (railway=level_crossing, official_name tag)
CROSSING_LAT, CROSSING_LON = 35.3066013, 139.5020923

# Region baked into the JSON (local frame, metres).  Spec area is 250 x 180 m; the extra margin is backdrop
# (headland, hills, far coast) that camera 2 sees when it looks east along the coast.
X_RANGE = (-230.0, 420.0)
Y_RANGE = (-70.0, 230.0)
GRID_DX = 2.0


# ----------------------------------------------------------------------------------------------- geodesy
_A, _E2 = 6378137.0, 0.00669437999014


class Frame:
    """Local tangent-plane frame rotated so that +X follows the track (mm-accurate over a few hundred m)."""

    def __init__(self, lat0, lon0, bearing_deg=90.0):
        self.lat0, self.lon0 = lat0, lon0
        p = math.radians(lat0)
        s2 = math.sin(p) ** 2
        self.kn = math.radians(1.0) * _A * (1 - _E2) / (1 - _E2 * s2) ** 1.5      # metres per deg lat
        self.ke = math.radians(1.0) * _A / math.sqrt(1 - _E2 * s2) * math.cos(p)  # metres per deg lon
        self.set_bearing(bearing_deg)

    def set_bearing(self, b):
        self.bearing = b
        self.fe, self.fn = math.sin(math.radians(b)), math.cos(math.radians(b))

    def en(self, lat, lon):
        return (lon - self.lon0) * self.ke, (lat - self.lat0) * self.kn

    def xy(self, lat, lon):
        e, n = self.en(lat, lon)
        return e * self.fe + n * self.fn, -e * self.fn + n * self.fe

    def to_latlon(self, x, y):
        e = x * self.fe - y * self.fn
        n = x * self.fn + y * self.fe
        return self.lat0 + n / self.kn, self.lon0 + e / self.ke


# ----------------------------------------------------------------------------------------------- http zip
class HTTPRangeFile(io.RawIOBase):
    """Seekable read-only file over HTTP Range requests with a block cache (for zipfile on a remote zip)."""
    BLOCK = 4 << 20

    def __init__(self, url):
        self.url = url
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            self.size = int(r.headers["Content-Length"])
        self.pos, self.fetched, self._blk, self._data = 0, 0, -1, b""

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.size + off)
        return self.pos

    def _load(self, blk):
        if blk == self._blk:
            return
        a = blk * self.BLOCK
        b = min(a + self.BLOCK, self.size) - 1
        req = urllib.request.Request(self.url, headers={"Range": "bytes=%d-%d" % (a, b), "User-Agent": UA})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    self._data = r.read()
                break
            except Exception as e:                                                   # transient network errors
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
        self._blk = blk
        self.fetched += len(self._data)

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        out = []
        while n > 0 and self.pos < self.size:
            blk, off = divmod(self.pos, self.BLOCK)
            self._load(blk)
            chunk = self._data[off:off + n]
            out.append(chunk)
            self.pos += len(chunk)
            n -= len(chunk)
        return b"".join(out)

    def readinto(self, b):
        d = self.read(len(b)); b[:len(d)] = d; return len(d)


# ----------------------------------------------------------------------------------------------- OSM
def fetch_osm(cache):
    path = os.path.join(cache, "osm.json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    q = """[out:json][timeout:60];
(
  way["railway"](35.3020,139.4940,35.3110,139.5140);
  node["railway"](35.3020,139.4940,35.3110,139.5140);
  way["highway"](35.3020,139.4940,35.3110,139.5140);
  way["barrier"~"retaining_wall|wall|fence|guard_rail"](35.3040,139.4990,35.3085,139.5060);
  way["natural"="coastline"](35.2980,139.4900,35.3110,139.5160);
);
out geom;"""
    body = urllib.parse.urlencode({"data": q}).encode()
    data, err = None, None
    for attempt in range(6):
        url = OVERPASS_MIRRORS[attempt % len(OVERPASS_MIRRORS)]
        req = urllib.request.Request(url, data=body, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read().decode("utf-8"))
            break
        except Exception as e:                                       # 429/504 are common on the public instances
            err = e
            print("  overpass %s failed (%s), retrying ..." % (url.split("/")[2], e), flush=True)
            time.sleep(5 * (attempt + 1))
    if data is None:
        raise RuntimeError("Overpass API unavailable: %s" % err)
    json.dump(data, open(path, "w", encoding="utf-8"))
    return data


def analyse_osm(osm):
    """Returns (origin_lat, origin_lon, bearing) from the Enoden centre-line around the crossing."""
    fr0 = Frame(CROSSING_LAT, CROSSING_LON)
    rails = []
    for e in osm["elements"]:
        t = e.get("tags", {})
        if e["type"] == "way" and t.get("railway") in ("light_rail", "tram", "rail") and "geometry" in e:
            rails.append([(g["lat"], g["lon"]) for g in e["geometry"]])
    # densify to 1 m and pick the closest point to the crossing node
    best = (1e18, None)
    pts = []
    for line in rails:
        xy = [fr0.en(*p) for p in line]
        for (e0, n0), (e1, n1) in zip(xy, xy[1:]):
            L = math.hypot(e1 - e0, n1 - n0)
            k = max(1, int(L))
            for i in range(k):
                pe, pn = e0 + (e1 - e0) * i / k, n0 + (n1 - n0) * i / k
                pts.append((pe, pn))
                d = math.hypot(pe, pn)
                if d < best[0]:
                    best = (d, (pe, pn))
    oe, on = best[1]
    near = np.array([(e - oe, n - on) for e, n in pts if math.hypot(e - oe, n - on) < 90.0])
    c = near - near.mean(axis=0)
    w, v = np.linalg.eigh(c.T @ c)
    d = v[:, np.argmax(w)]
    if d[0] < 0:
        d = -d                                                                         # point toward +east
    bearing = math.degrees(math.atan2(d[0], d[1]))                                     # from north, clockwise
    lat0 = fr0.lat0 + on / fr0.kn
    lon0 = fr0.lon0 + oe / fr0.ke
    return lat0, lon0, bearing, best[0]


def bake_osm(osm, fr, x_range, y_range):
    out = {"track": [], "roads": [], "coast": [], "platform": [], "level_crossings": [], "station": None,
           "barriers": []}
    inside = lambda x, y: x_range[0] - 60 < x < x_range[1] + 60 and y_range[0] - 60 < y < y_range[1] + 60
    for e in osm["elements"]:
        t = e.get("tags", {})
        if e["type"] == "node":
            x, y = fr.xy(e["lat"], e["lon"])
            if t.get("railway") == "level_crossing":
                out["level_crossings"].append({"x": round(x, 2), "y": round(y, 2), "name": t.get("official_name", "")})
            elif t.get("railway") == "station":
                out["station"] = {"x": round(x, 2), "y": round(y, 2), "name": t.get("name", "")}
            continue
        g = [fr.xy(p["lat"], p["lon"]) for p in e.get("geometry", [])]
        g = [[round(x, 2), round(y, 2)] for x, y in g]
        if not g:
            continue
        if t.get("railway") in ("light_rail", "tram", "rail"):
            out["track"].append(g)
        elif t.get("railway") == "platform":
            out["platform"].append(g)
        elif t.get("highway"):
            if any(inside(x, y) for x, y in g):
                out["roads"].append({"hw": t["highway"], "name": t.get("name", ""), "ref": t.get("ref", ""),
                                     "pts": g})
        elif t.get("natural") == "coastline":
            out["coast"].append(g)
        elif t.get("barrier"):
            out["barriers"].append({"kind": t["barrier"], "pts": g})
    return out


# ----------------------------------------------------------------------------------------------- DEM
_POS = re.compile(rb"<gml:posList[^>]*>([^<]*)</gml:posList>")


def stream_dem_triangles(z, name, fr, lat_rng, lon_rng, cache):
    """Yield (x,y,z)*3 tuples for every DEM triangle that touches the lat/lon window."""
    cpath = os.path.join(cache, "dem_tri.npy")
    if os.path.exists(cpath):
        return np.load(cpath)
    tris = []
    info = z.getinfo(name)
    print("  streaming DEM %s (%.0f MB uncompressed) ..." % (name, info.file_size / 1e6), flush=True)
    t0, carry, total = time.time(), b"", 0
    with z.open(name) as f:
        while True:
            chunk = f.read(8 << 20)
            if not chunk:
                break
            total += len(chunk)
            buf = carry + chunk
            last = buf.rfind(b"</gml:posList>")
            if last < 0:
                carry = buf
                continue
            carry = buf[last + 14:]
            for m in _POS.finditer(buf[:last + 14]):
                s = m.group(1)
                sp = s.split(None, 2)
                if len(sp) < 3:
                    continue
                lat = float(sp[0])
                if not (lat_rng[0] < lat < lat_rng[1]):
                    continue
                lon = float(sp[1])
                if not (lon_rng[0] < lon < lon_rng[1]):
                    continue
                v = s.split()
                if len(v) < 9:
                    continue
                vals = [float(q) for q in v[:9]]
                tri = []
                for i in range(3):
                    x, y = fr.xy(vals[3 * i], vals[3 * i + 1])
                    tri += [x, y, vals[3 * i + 2]]
                tris.append(tri)
            if total % (64 << 20) < (8 << 20):
                print("    %.0f MB  triangles kept: %d  (%.0fs)" % (total / 1e6, len(tris), time.time() - t0), flush=True)
    arr = np.array(tris, dtype=np.float64)
    np.save(cpath, arr)
    return arr


def rasterise(tris, z0, x_range, y_range, dx):
    nx = int(round((x_range[1] - x_range[0]) / dx)) + 1
    ny = int(round((y_range[1] - y_range[0]) / dx)) + 1
    grid = np.full((ny, nx), np.nan)
    for t in tris:
        x = t[0::3]; y = t[1::3]; h = t[2::3]
        i0 = max(0, int(math.floor((min(x) - x_range[0]) / dx)))
        i1 = min(nx - 1, int(math.ceil((max(x) - x_range[0]) / dx)))
        j0 = max(0, int(math.floor((min(y) - y_range[0]) / dx)))
        j1 = min(ny - 1, int(math.ceil((max(y) - y_range[0]) / dx)))
        if i1 < i0 or j1 < j0:
            continue
        gx, gy = np.meshgrid(x_range[0] + dx * np.arange(i0, i1 + 1), y_range[0] + dx * np.arange(j0, j1 + 1))
        d = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
        if abs(d) < 1e-9:
            continue
        a = ((y[1] - y[2]) * (gx - x[2]) + (x[2] - x[1]) * (gy - y[2])) / d
        b = ((y[2] - y[0]) * (gx - x[2]) + (x[0] - x[2]) * (gy - y[2])) / d
        c = 1 - a - b
        m = (a >= -1e-6) & (b >= -1e-6) & (c >= -1e-6)
        zz = a * h[0] + b * h[1] + c * h[2]
        sub = grid[j0:j1 + 1, i0:i1 + 1]
        sub[m] = zz[m] - z0
    return grid


def sample_grid(grid, x, y, x_range, y_range, dx):
    i = int(round((x - x_range[0]) / dx)); j = int(round((y - y_range[0]) / dx))
    if 0 <= j < grid.shape[0] and 0 <= i < grid.shape[1]:
        return grid[j, i]
    return float("nan")


# ----------------------------------------------------------------------------------------------- buildings
def _it(el, name):
    """Descendants by local name (Element.iter() has no {*} wildcard; iterfind() does)."""
    return el.iterfind(".//{*}" + name)


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _ring(poly, fr, z0):
    """exterior ring of a gml:Polygon -> flat [x,y,z,...] (closing vertex dropped)."""
    for pl in _it(poly, "posList"):
        v = [float(q) for q in pl.text.split()]
        n = len(v) // 3
        if n < 4:
            return None
        out = []
        for i in range(n - 1):
            x, y = fr.xy(v[3 * i], v[3 * i + 1])
            out += [round(x, 2), round(y, 2), round(v[3 * i + 2] - z0, 2)]
        return out
    return None


def _classify_lod1(ring):
    """Sign of the polygon normal z: up -> roof, down -> ground, else wall."""
    n = len(ring) // 3
    nx = ny = nz = 0.0
    for i in range(n):
        x0, y0, z0 = ring[3 * i:3 * i + 3]
        x1, y1, z1 = ring[3 * ((i + 1) % n):3 * ((i + 1) % n) + 3]
        nx += (y0 - y1) * (z0 + z1); ny += (z0 - z1) * (x0 + x1); nz += (x0 - x1) * (y0 + y1)
    L = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    if nz / L > 0.5:
        return "r"
    if nz / L < -0.5:
        return "g"
    return "w"


def parse_buildings(fileobj, fr, z0, x_range, y_range):
    out = []
    for ev, el in ET.iterparse(fileobj, events=("end",)):
        if _local(el.tag) != "Building":
            continue
        polys = []
        lod2 = False
        for bb in _it(el, "boundedBy"):
            for surf in bb:
                kind = {"WallSurface": "w", "RoofSurface": "r", "GroundSurface": "g"}.get(_local(surf.tag), "w")
                if _local(surf.tag) == "ClosureSurface":
                    continue
                for p in _it(surf, "Polygon"):
                    r = _ring(p, fr, z0)
                    if r:
                        polys.append([kind, r]); lod2 = True
        if not lod2:
            for sol in _it(el, "lod1Solid"):
                for p in _it(sol, "Polygon"):
                    r = _ring(p, fr, z0)
                    if r:
                        polys.append([_classify_lod1(r), r])
        if polys:
            xs = [r[0::3] for _, r in polys]; ys = [r[1::3] for _, r in polys]
            x0 = min(min(a) for a in xs); x1 = max(max(a) for a in xs)
            y0 = min(min(a) for a in ys); y1 = max(max(a) for a in ys)
            if x1 > x_range[0] and x0 < x_range[1] and y1 > y_range[0] and y0 < y_range[1]:
                h = el.find("{*}measuredHeight")

                def txt(tag):
                    e = el.find(".//{*}" + tag)
                    return e.text.strip() if e is not None and e.text else ""

                fl = txt("storeysAboveGround")
                out.append({"id": el.get("{http://www.opengis.net/gml}id", ""),
                            "h": float(h.text) if h is not None and h.text else 0.0,
                            "use": txt("usage"),                       # Building_usage code list: 411 house, 412 apartment house, 413 shop-house ...
                            "struct": txt("buildingStructureType"),    # 601 wood, 610 non-wood, 611 unknown
                            "fl": int(fl) if fl.lstrip("-").isdigit() else 0,
                            "lod": 2 if lod2 else 1, "polys": polys})
        el.clear()
    return out


def tile_codes(fr, x_range, y_range):
    """All 3rd-mesh codes (JIS X 0410, 8 digits) touching the region."""
    lats, lons = [], []
    for x in (x_range[0], x_range[1]):
        for y in (y_range[0], y_range[1]):
            la, lo = fr.to_latlon(x, y)
            lats.append(la); lons.append(lo)

    def idx(lat, lon):
        p = int(lat * 1.5); a = lat * 1.5 - p
        u = int(lon - 100); b = lon - 100 - u
        q = int(a * 8); a2 = a * 8 - q
        v = int(b * 8); b2 = b * 8 - v
        r = int(a2 * 10); c = int(b2 * 10)
        return p, u, q, v, r, c

    def to_i(t):  # linear index on the 3rd-mesh lattice
        p, u, q, v, r, c = t
        return (p * 80 + q * 10 + r), (u * 80 + v * 10 + c)

    lo_i = to_i(idx(min(lats), min(lons))); hi_i = to_i(idx(max(lats), max(lons)))
    codes = []
    for i in range(lo_i[0], hi_i[0] + 1):
        for j in range(lo_i[1], hi_i[1] + 1):
            p, rem = divmod(i, 80); q, r = divmod(rem, 10)
            u, rem2 = divmod(j, 80); v, c = divmod(rem2, 10)
            codes.append("%02d%02d%d%d%d%d" % (p, u, q, v, r, c))
    return codes


# ----------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--cache", default=os.path.join(os.environ.get("LOCALAPPDATA", here), "enoden_plateau_cache"))
    ap.add_argument("--out", default=os.path.join(here, "plateau_data", "kamakura_koko.json"))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.cache, exist_ok=True)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    if os.path.exists(a.out) and not a.force:
        print("exists:", a.out, "(use --force to rebuild)"); return

    print("[1/4] OSM ...", flush=True)
    osm = fetch_osm(a.cache)
    lat0, lon0, bearing, dist = analyse_osm(osm)
    print("  origin on centre-line: %.7f, %.7f  (%.1f m from OSM crossing node), track bearing %.2f deg" %
          (lat0, lon0, dist, bearing))
    fr = Frame(lat0, lon0, bearing)

    print("[2/4] PLATEAU zip directory ...", flush=True)
    f = HTTPRangeFile(ZIP_URL)
    z = zipfile.ZipFile(f)

    print("[3/4] DEM ...", flush=True)
    corners = [fr.to_latlon(x, y) for x in X_RANGE for y in Y_RANGE]
    lat_rng = (min(c[0] for c in corners) - 0.0006, max(c[0] for c in corners) + 0.0006)
    lon_rng = (min(c[1] for c in corners) - 0.0006, max(c[1] for c in corners) + 0.0006)
    tris = stream_dem_triangles(z, "udx/dem/523974_dem_6697_op.gml", fr, lat_rng, lon_rng, a.cache)
    print("  DEM triangles in window:", len(tris))
    # z0 = height at origin: first pass with raw heights
    tmp = rasterise(tris, 0.0, X_RANGE, Y_RANGE, GRID_DX)
    z0 = sample_grid(tmp, 0.0, 0.0, X_RANGE, Y_RANGE, GRID_DX)
    if not np.isfinite(z0):
        z0 = float(np.nanmedian(tmp[int(-Y_RANGE[0] / GRID_DX) - 3:int(-Y_RANGE[0] / GRID_DX) + 4, :]))
    grid = tmp - z0
    print("  DEM height at origin (TP) = %.2f m -> scene Z0;  land coverage %.0f%%, z range %.1f .. %.1f" %
          (z0, 100.0 * np.isfinite(grid).mean(), np.nanmin(grid), np.nanmax(grid)))

    print("[4/4] buildings ...", flush=True)
    blds = []
    for code in tile_codes(fr, X_RANGE, Y_RANGE):
        name = "udx/bldg/%s_bldg_6697_op.gml" % code
        try:
            info = z.getinfo(name)
        except KeyError:
            continue
        cpath = os.path.join(a.cache, os.path.basename(name))
        if not os.path.exists(cpath):
            with z.open(name) as src, open(cpath, "wb") as dst:
                while True:
                    b = src.read(1 << 20)
                    if not b:
                        break
                    dst.write(b)
        with open(cpath, "rb") as fh:
            got = parse_buildings(fh, fr, z0, X_RANGE, Y_RANGE)
        print("  %s  %.1f MB  -> %d buildings in region" % (code, info.file_size / 1e6, len(got)), flush=True)
        blds += got
    print("  total buildings:", len(blds), " LOD2:", sum(b["lod"] == 2 for b in blds))

    data = {
        "meta": {
            "origin_lat": lat0, "origin_lon": lon0, "bearing_deg": bearing, "z0_tp": float(z0),
            "x_range": X_RANGE, "y_range": Y_RANGE,
            "credit": "3D都市モデル(Project PLATEAU) 鎌倉市 2024年度, MLIT Japan; (c) OpenStreetMap contributors (ODbL)",
        },
        "heightfield": {"x0": X_RANGE[0], "y0": Y_RANGE[0], "dx": GRID_DX, "nx": int(grid.shape[1]),
                        "ny": int(grid.shape[0]),
                        "z": [None if not np.isfinite(v) else round(float(v), 2) for v in grid.ravel()]},
        "buildings": blds,
        "osm": bake_osm(osm, fr, X_RANGE, Y_RANGE),
    }
    with open(a.out, "w", encoding="utf-8") as fo:
        json.dump(data, fo, ensure_ascii=False, separators=(",", ":"))
    print("wrote", a.out, "%.2f MB" % (os.path.getsize(a.out) / 1e6), " (net downloaded %.1f MB)" % (f.fetched / 1e6))


if __name__ == "__main__":
    main()
