"""Clip Natural Earth data to the Upper Rhine and print SVG paths as JSON. Run: python3 -I build_map.py DATA_DIR OUT.json"""
import json, math, sys
data_dir, out = sys.argv[1], sys.argv[2]
LON0, LON1, LAT0, LAT1 = 6.8, 8.7, 47.45, 49.15
K = math.cos(math.radians(48.3))
S = 400.0
W, H = (LON1 - LON0) * K * S, (LAT1 - LAT0) * S
def proj(lon, lat): return ((lon - LON0) * K * S, (LAT1 - lat) * S)

def clip_ring(ring):
    def inside(p, e):
        x, y = p
        return {"l": x >= LON0, "r": x <= LON1, "b": y >= LAT0, "t": y <= LAT1}[e]
    def inter(a, b, e):
        (x1, y1), (x2, y2) = a, b
        if e in "lr":
            x = LON0 if e == "l" else LON1; t = (x - x1) / (x2 - x1); return (x, y1 + t * (y2 - y1))
        y = LAT0 if e == "b" else LAT1; t = (y - y1) / (y2 - y1); return (x1 + t * (x2 - x1), y)
    pts = ring
    for e in "lrbt":
        if not pts: break
        new = []
        for i, cur in enumerate(pts):
            prev = pts[i - 1]
            if inside(cur, e):
                if not inside(prev, e): new.append(inter(prev, cur, e))
                new.append(cur)
            elif inside(prev, e): new.append(inter(prev, cur, e))
        pts = new
    return pts

def clip_line(pts):
    out_lines, cur = [], []
    def liang(a, b):
        (x1, y1), (x2, y2) = a, b; dx, dy = x2 - x1, y2 - y1; t0, t1 = 0.0, 1.0
        for p, q in ((-dx, x1 - LON0), (dx, LON1 - x1), (-dy, y1 - LAT0), (dy, LAT1 - y1)):
            if p == 0:
                if q < 0: return None
            else:
                r = q / p
                if p < 0:
                    if r > t1: return None
                    t0 = max(t0, r)
                else:
                    if r < t0: return None
                    t1 = min(t1, r)
        return (x1 + t0 * dx, y1 + t0 * dy), (x1 + t1 * dx, y1 + t1 * dy), t1 < 1.0
    for a, b in zip(pts, pts[1:]):
        seg = liang(a, b)
        if seg is None:
            if cur: out_lines.append(cur); cur = []
            continue
        p, q, cut = seg
        if not cur: cur = [p]
        cur.append(q)
        if cut: out_lines.append(cur); cur = []
    if cur: out_lines.append(cur)
    return [l for l in out_lines if len(l) > 1]

def dp(pts, eps):
    if len(pts) < 3: return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]; dx, dy = x2 - x1, y2 - y1; n = math.hypot(dx, dy) or 1e-12
    idx, dmax = 0, 0
    for i in range(1, len(pts) - 1):
        d = abs(dy * pts[i][0] - dx * pts[i][1] + x2 * y1 - y2 * x1) / n
        if d > dmax: idx, dmax = i, d
    if dmax > eps: return dp(pts[:idx + 1], eps)[:-1] + dp(pts[idx:], eps)
    return [pts[0], pts[-1]]

def path(lines, close=False):
    parts = []
    for l in lines:
        if close and len(l) > 5:
            m = len(l) // 2
            simp = dp(l[:m + 1], 0.0012)[:-1] + dp(l[m:], 0.0012)
        else:
            simp = dp(l, 0.0012)
        pp = [proj(*p) for p in simp]
        if len(pp) < 2: continue
        parts.append("M" + " ".join(f"{x:.1f} {y:.1f}" for x, y in pp) + ("Z" if close else ""))
    return "".join(parts)

def polys(geom):
    if geom["type"] == "Polygon": return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon": return geom["coordinates"]
    return []

def lines_of(geom):
    if geom["type"] == "LineString": return [geom["coordinates"]]
    if geom["type"] == "MultiLineString": return geom["coordinates"]
    return []

res = {"viewBox": [round(W, 1), round(H, 1)], "K": K, "S": S, "LON0": LON0, "LAT1": LAT1}
c = json.load(open(f"{data_dir}/ne_10m_admin_0_countries.geojson"))
res["countries"] = {}
for f in c["features"]:
    name = f["properties"].get("NAME") or f["properties"].get("ADMIN")
    if name not in ("France", "Germany", "Switzerland"): continue
    rings = []
    for poly in polys(f["geometry"]):
        r = clip_ring([tuple(p[:2]) for p in poly[0]])
        if len(r) > 2: rings.append(r + [r[0]])
    res["countries"][name] = path(rings, close=True)
a1 = json.load(open(f"{data_dir}/ne_10m_admin_1_states_provinces.geojson"))
res["regions"] = {}
for f in a1["features"]:
    nm = f["properties"].get("name")
    if nm in ("Grand Est", "Baden-Württemberg", "Rheinland-Pfalz", "Bourgogne-Franche-Comté", "Alsace", "Bas-Rhin", "Haut-Rhin", "Basel-Stadt", "Basel-Landschaft"):
        rings = []
        for poly in polys(f["geometry"]):
            r = clip_ring([tuple(p[:2]) for p in poly[0]])
            if len(r) > 2: rings.append(r + [r[0]])
        if rings: res["regions"][nm] = path(rings, close=True)
rv = json.load(open(f"{data_dir}/ne_10m_rivers_lake_centerlines.geojson"))
names = {}
res["rivers"] = {}
for f in rv["features"]:
    nm = f["properties"].get("name") or ""
    segs = []
    for l in lines_of(f["geometry"]):
        segs += clip_line([tuple(p[:2]) for p in l])
    if segs:
        names[nm] = names.get(nm, 0) + len(segs)
        res["rivers"].setdefault(nm, "")
        res["rivers"][nm] += path(segs)
lk = json.load(open(f"{data_dir}/ne_10m_lakes.geojson"))
res["lakes"] = ""
for f in lk["features"]:
    rings = []
    for poly in polys(f["geometry"]):
        r = clip_ring([tuple(p[:2]) for p in poly[0]])
        if len(r) > 2: rings.append(r + [r[0]])
    if rings: res["lakes"] += path(rings, close=True)
json.dump(res, open(out, "w"))
print("viewBox", res["viewBox"]); print("countries", {k: len(v) for k, v in res["countries"].items()})
print("regions", {k: len(v) for k, v in res["regions"].items()}); print("rivers", {k: len(v) for k, v in res["rivers"].items()}); print("lakes", len(res["lakes"]))
