"""Kibana dashboards for the acts, pushed with the Dashboards API (GA since 9.5; header elastic-api-version 2023-10-31).

    python -m coldchain.dashboards push [--only ID] [--range FROM TO]   # create or replace, by stable id
    python -m coldchain.dashboards check [--only ID] [--range FROM TO]  # run every panel query through _query
    python -m coldchain.dashboards list
    python -m coldchain.dashboards delete

Every panel is an ES|QL chart, so it reads the same field names on indexed and federated data. Queries filter on the
dashboard time picker (?_tstart, ?_tend). `check` runs each query with a fixed range so a panel that cannot work fails
here instead of on stage. It cannot show how Kibana renders a panel: open the dashboards once before a show.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field

import requests

from .elastic import client
from . import panels
from .envfile import load_env

T = "@timestamp >= ?_tstart AND @timestamp < ?_tend"
NOMINAL = 'CASE(coldchain.application == "frozen", -24.0, 2.0)'  # chain.yaml: frozen at -24 C, chilled at +2 C
ATTACKER = "203.0.113.0/24"
# "Warm and no defrost": at least 3 of the last 10 minutes of the range more than 2 K above nominal, relay never on in the
# range. Measured on the synthetic data: 0 cabinets in 34 days of baseline, 46 from about T0+10 min (rule 2 of CLAUDE.md 8.2).
WARM_ROW = (f"coldchain.case.temperature.air - {NOMINAL} > 2 AND coldchain.case.defrost.active == false "
            "AND @timestamp >= newest - 10 minutes")


@dataclass
class Dash:
    id: str
    title: str
    description: str
    time: tuple[str, str] = ("now-24h", "now")
    panels: list[dict] = field(default_factory=list)
    controls: list[dict] = field(default_factory=list)
    queries: list[tuple[str, str, dict]] = field(default_factory=list)  # (panel title, esql, params) for `check`
    y: int = 0

    def add(self, title: str, cfg: dict, w: int, h: int, x: int | None = None, y: int | None = None, query: str | None = None,
            params: dict | None = None) -> None:
        """Place a panel. Panels in one row share y; pass x to put it next to the previous one."""
        self.panels.append({"type": "vis", "grid": {"x": x or 0, "y": self.y if y is None else y, "w": w, "h": h},
                            "config": {**cfg, "title": title}})
        if query:
            self.queries.append((title, query, params or {}))

    def row(self, h: int) -> None:
        self.y += h

    def body(self) -> dict:
        nav = nav_panel(self.id)
        panels = self.panels
        if nav:  # a navigation strip on top: every other panel moves down by its height
            panels = [nav] + [{**p, "grid": {**p["grid"], "y": p["grid"]["y"] + nav["grid"]["h"]}} for p in self.panels]
        return {"title": self.title, "description": self.description,
                "time_range": {"from": self.time[0], "to": self.time[1]},
                "tags": [], "panels": panels, "pinned_panels": self.controls}


# The acts in story order: dashboard id, label, a few words. The navigation strip links to the previous and the next one.
ACTS = [("coldchain-act0-sources", "Act 0", "The realms you usually do not watch"),
        ("coldchain-act1a-cabinet", "Act 1", "Store 07 from above"),
        ("coldchain-act1b-estate", "Act 2", "The whole estate"),
        ("coldchain-act3-history", "Act 3", "The history nobody looked at"),
        ("coldchain-hunt-findings", "Act 4", "Hunting agent"),
        ("coldchain-pos-evidence", "Act 5", "The POS lead")]
NAV_HEIGHT = 2

NAV_CSS = """<style>
.cc-nav{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:12px;padding:0 2px}
.cc-nav a{color:inherit;text-decoration:none;opacity:.7}
.cc-nav a:hover{opacity:1;text-decoration:underline}
.cc-nav .side{flex:1 1 0;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cc-nav .side.r{text-align:right}
.cc-nav .steps{display:flex;gap:6px;align-items:center}
.cc-nav .step{display:inline-flex;width:22px;height:22px;align-items:center;justify-content:center;border-radius:50%;
  border:1px solid rgba(128,128,128,.45);font-size:11px;opacity:.75}
.cc-nav .step:hover{opacity:1;background:rgba(128,128,128,.22);text-decoration:none}
.cc-nav .step.cur{background:#69707D;border-color:#69707D;color:#fff;opacity:1;font-weight:700}
</style>"""


def nav_panel(dash_id: str) -> dict | None:
    """A quiet strip: small previous and next links on the sides and one numbered dot per act in the middle."""
    ids = [a[0] for a in ACTS]
    dash_id = {panels.LIT_PAGE: panels.DARK_PAGE}.get(dash_id, dash_id)  # "the light is on" is Act 0 with the light on
    if dash_id.startswith("coldchain-act1a-s07-"):  # a clicked cabinet is still Act 1
        dash_id = "coldchain-act1a-cabinet"
    if dash_id.startswith("coldchain-act1b-s"):  # a clicked store is still Act 2
        dash_id = "coldchain-act1b-estate"
    if dash_id not in ids:
        return None
    i = ids.index(dash_id)

    def side(j: int, arrow_first: bool, cls: str) -> str:
        if not 0 <= j < len(ACTS):
            return f'<span class="side {cls}"></span>'
        did, label, words = ACTS[j]
        text = f"\u2039 {label}: {words}" if arrow_first else f"{label}: {words} \u203A"
        return f'<span class="side {cls}"><a href="/app/dashboards#/view/{did}">{text}</a></span>'

    dots = "".join(
        f'<a class="step{" cur" if j == i else ""}" title="{a[1]}: {a[2]}" href="/app/dashboards#/view/{a[0]}">{a[1].split()[1]}</a>'
        for j, a in enumerate(ACTS))
    html = f'{NAV_CSS}<div class="cc-nav">{side(i - 1, True, "l")}<span class="steps">{dots}</span>{side(i + 1, False, "r")}</div>'
    return {"type": "custom_content", "grid": {"x": 0, "y": 0, "w": 48, "h": NAV_HEIGHT},
            "config": {"template": html, "esql_query": ["ROW x = 1"]}}


def esql(q: str) -> dict:
    return {"type": "esql", "query": " ".join(q.split("\n")) if "//" in q else q.strip()}


def md(content: str, w: int = 48, h: int = 5, d: Dash | None = None, x: int = 0) -> dict:
    return {"type": "markdown", "grid": {"x": x, "y": d.y if d else 0, "w": w, "h": h}, "config": {"content": content}}


GREEN, AMBER, RED = "#54B399", "#F5A700", "#BD271E"


def tile_color(key: str) -> dict:
    """Colour of a tile's number by value, from the thresholds of its kb-baselines row (coldchain/baselines.py)."""
    from .baselines import THRESHOLDS
    t = THRESHOLDS[key]
    if t["direction"] == "down":
        steps = [{"lt": t["red_below"], "color": RED}, {"gte": t["red_below"], "color": GREEN}]
    elif "amber" in t:
        steps = [{"lt": t["amber"], "color": GREEN}, {"gte": t["amber"], "lt": t["red"], "color": AMBER}, {"gte": t["red"], "color": RED}]
    else:
        steps = [{"lt": t["red"], "color": GREEN}, {"gte": t["red"], "color": RED}]
    return {"type": "dynamic", "range": "absolute", "steps": steps}


def vs_normal(col: str, key: str, rate: bool) -> str:
    """ES|QL tail: look the tile's normal up in kb-baselines and say how far the value is from it, with an arrow.

    A rate (count per day) is scaled to the length of the picker window; a level is used as it is.
    """
    scale = 'kb.baseline.value * DATE_DIFF("minutes", ?_tstart, ?_tend) / 1440.0' if rate else "kb.baseline.value"
    return (f'| EVAL kb.key = "{key}" | LOOKUP JOIN kb-baselines ON kb.key | EVAL normal = ROUND({scale}, 0), delta = {col} - normal '
            '| EVAL vs_normal = CASE(delta > 0, CONCAT("\u25B2 +", TO_STRING(TO_INTEGER(delta)), " above normal (", TO_STRING(TO_INTEGER(normal)), ")"), '
            'delta < 0, CONCAT("\u25BC ", TO_STRING(TO_INTEGER(delta)), " below normal (", TO_STRING(TO_INTEGER(normal)), ")"), '
            'CONCAT("= normal (", TO_STRING(TO_INTEGER(normal)), ")")) '
            f"| KEEP {col}, vs_normal")


def metric(d: Dash, title: str, q: str, col: str, w: int = 12, h: int = 6, x: int = 0, params: dict | None = None,
           normal: tuple[str, bool] | None = None) -> None:
    """A tile; with `normal=(kb-baselines key, rate)` it shows the value against its baseline, arrow included."""
    metrics = [{"type": "primary", "column": col, "label": " "}]
    if normal:
        metrics[0]["color"] = tile_color(normal[0])
        q = q + " " + vs_normal(col, *normal)
        metrics.append({"type": "secondary", "column": "vs_normal", "label": " "})
    d.add(title, {"type": "metric", "data_source": esql(q), "metrics": metrics}, w, h, x, query=q, params=params)


def table(d: Dash, title: str, q: str, cols: list[str], w: int = 48, h: int = 10, x: int = 0, params: dict | None = None) -> None:
    d.add(title, {"type": "data_table", "data_source": esql(q), "metrics": [{"column": c} for c in cols]}, w, h, x, query=q,
          params=params)


def lines(d: Dash, title: str, q: str, x_col: str, y_cols: list[str], w: int = 48, h: int = 10, x: int = 0, by: str | None = None,
          kind: str = "line", params: dict | None = None, ytitle: str | None = None) -> None:
    layer = {"type": kind, "data_source": esql(q), "x": {"column": x_col}, "y": [{"column": c} for c in y_cols]}
    if by:
        layer["breakdown_by"] = {"column": by}
    cfg = {"type": "xy", "layers": [layer], "axis": {"x": {"title": {"visible": False}}},
           "legend": {"visibility": "visible" if by or len(y_cols) > 1 else "hidden", "placement": "outside", "position": "bottom"}}
    if ytitle:
        cfg["axis"]["y"] = {"title": {"text": ytitle, "visible": True}}
    d.add(title, cfg, w, h, x, query=q, params=params)


# ES|QL has no number formatting: put thousands separators in with a regular expression (lookahead for groups of three digits).
THOUSANDS = r'REPLACE(TO_STRING({col}), "(\\d)(?=(\\d{{3}})+$)", "$1,")'


def custom(d: Dash, title: str, q: str, template: str, w: int = 48, h: int = 10, x: int = 0, show_title: bool = True) -> None:
    """A Serverless custom panel (`custom_content`): one ES|QL query, filled into an HTML, CSS and Liquid template."""
    cfg = {"template": template, "esql_query": [q]}
    if show_title:
        cfg = {"title": title, **cfg}
    d.panels.append({"type": "custom_content", "grid": {"x": x, "y": d.y, "w": w, "h": h}, "config": cfg})
    d.queries.append((title, q, {}))


# --- Act 0: the realms you usually do not watch ------------------------------------------------------------------------

def act0() -> Dash:
    d = Dash("coldchain-act0-sources", "Act 0: The streetlight effect - we search where the light is",
             "Every source the demo reads, in one place: telemetry, audit, probes, network flows, POS terminals, the knowledge base. Synthetic data.",
             time=("now-24h", "now"))
    q = ("FROM kb-sources | SORT tier_order, rows DESC "
         "| EVAL rows_txt = " + THOUSANDS.format(col="rows") + " | KEEP tier, zone, label, what, rows_txt")
    custom(d, "The realms", q, panels.REALMS, w=48, h=50, show_title=False)
    d.row(50)
    return d


def act0_lit() -> Dash:
    d = Dash(panels.LIT_PAGE, "Act 0: The light is on - one platform, every realm",
             "The same sources with the light on: nothing in the dark. Synthetic data.", time=("now-24h", "now"))
    q = ("FROM kb-sources | SORT tier_order, rows DESC "
         "| EVAL rows_txt = " + THOUSANDS.format(col="rows") + " | KEEP tier, zone, label, what, rows_txt")
    custom(d, "The realms, lit", q, panels.REALMS_LIT, w=48, h=50, show_title=False)
    d.row(50)
    return d


# --- Act 1: the estate -------------------------------------------------------------------------------------------

CONTRACTOR_CABINET = "S07-C05"  # one of the 46 attacked cabinets: what the contractor's portal shows


STORE_QUERY = """FROM (FROM metrics-coldchain.case-default
        | WHERE retail.store.id == "S07" AND @timestamp >= ?_tstart AND @timestamp < ?_tend
        | STATS setpoint = MAX(coldchain.case.setpoint), readings = COUNT(*) BY cab = device.id
        | EVAL kind = "cabinet"),
     (FROM logs-coldchain.audit-default
        | WHERE retail.store.id == "S07" AND @timestamp >= ?_tstart AND @timestamp < ?_tend
        | STATS events = COUNT(*), changes = COUNT(*) WHERE event.action == "parameter-change",
                logins = COUNT(*) WHERE event.action == "logged-in" AND NOT CIDR_MATCH(source.ip, "198.51.100.0/24")
                AND NOT CIDR_MATCH(source.ip, "10.0.0.0/8")
        | EVAL kind = "audit"),
     (FROM logs-netflow.summary-default
        | WHERE retail.store.id == "S07" AND @timestamp >= ?_tstart AND @timestamp < ?_tend
        | STATS flows = COUNT(*), mb = ROUND(SUM(network.bytes) / 1000000.0, 1) BY role = retail.device.role
        | EVAL kind = "flows"),
     (FROM kb-assets
        | WHERE retail.store.id == "S07" AND device.id == "S07-SM800"
        | EVAL kind = "asset", internet = coldchain.exposure.internet, firmware = coldchain.controller.firmware,
               contractor = contractor.account.id
        | KEEP kind, internet, firmware, contractor),
     (FROM kb-assets
        | WHERE retail.store.id == "S07"
        | STATS devices = COUNT(*)
        | EVAL kind = "assets")
| SORT kind, cab
| LIMIT 100"""


def act1a(cabinet: str = CONTRACTOR_CABINET) -> Dash:
    """What one contractor sees: a single cabinet, no estate, no alerts. Same indexed data as 1b, filtered to one device.

    Every cabinet of store 07 has its own copy (clicked from the store layout); the contractor's cabinet is the Act 1 page.
    """
    cab = f'device.id == "{cabinet}"'
    default = cabinet == CONTRACTOR_CABINET
    d = Dash("coldchain-act1a-cabinet" if default else f"coldchain-act1a-{cabinet.lower()}",
             "Act 1: Store 07, Colmar, from above - what each system says" + ("" if default else f" (cabinet {cabinet[-2:]})"),
             "Synthetic data. Only this cabinet: no other cabinet, no store comparison, no alerts.")
    custom(d, "Store 07 from above", STORE_QUERY, panels.store_layout(cabinet), w=32, h=22, show_title=False)
    tiles_q = (f"FROM (FROM metrics-coldchain.case-* | WHERE {cab} AND {T} AND @timestamp <= NOW() | SORT @timestamp DESC | LIMIT 1 "
               "| EVAL kind = \"now\", setpoint = ROUND(coldchain.case.setpoint, 1), air = ROUND(coldchain.case.temperature.air, 1) "
               "| KEEP kind, setpoint, air), "
               f"(FROM logs-coldchain.audit-* | WHERE {cab} AND {T} AND event.action == \"parameter-change\" "
               "| STATS changes = COUNT(*) | EVAL kind = \"changes\" | KEEP kind, changes)")
    custom(d, "State of the cabinet the contractor sees", tiles_q, panels.cabinet_tiles(cabinet), w=16, h=22, x=32, show_title=False)
    d.row(22)
    q = (f"FROM metrics-coldchain.case-* | WHERE {cab} AND {T} AND @timestamp <= NOW() "
         "| STATS air = ROUND(AVG(coldchain.case.temperature.air), 1), setpoint = ROUND(AVG(coldchain.case.setpoint), 1) "
         "BY t = BUCKET(@timestamp, 5 minutes) | SORT t")
    cfg = {"type": "xy", "layers": [{"type": "line", "data_source": esql(q), "x": {"column": "t"},
                                     "y": [{"column": "air"}, {"column": "setpoint", "axis": "y2", "color": {"type": "static", "color": RED}}]}],
           "axis": {"x": {"title": {"visible": False}}, "y": {"title": {"text": "air temperature °C", "visible": True}},
                    "y2": {"title": {"text": "setpoint °C", "visible": True}}},
           "legend": {"visibility": "visible", "placement": "outside", "position": "bottom"}}
    d.add(f"{cabinet}: air temperature and setpoint", cfg, 48, 12, query=q)
    d.row(12)
    table(d, "Changes on this cabinet",
          f'FROM logs-coldchain.audit-* | WHERE {cab} AND {T} AND event.action == "parameter-change" '
          '| SORT @timestamp DESC | LIMIT 15 | EVAL time = DATE_FORMAT("MM-dd HH:mm", @timestamp) '
          "| RENAME user.name AS user, source.ip AS source, coldchain.parameter.code AS parameter, "
          "coldchain.parameter.value.old AS old, coldchain.parameter.value.new AS new | KEEP time, user, source, parameter, old, new",
          ["time", "user", "source", "parameter", "old", "new"], h=10)
    d.row(10)
    return d


# (longitude, latitude, town) of each store, for the schematic map of Act 2 (towns from config/chain.yaml)
from .geo import STORE_GEO  # noqa: E402  (towns of the stores, shared with the truck generator)


def geo_cases() -> str:
    """ES|QL EVAL fragment: map position (x, y in the base map's units) and town of the store in column `store`."""
    from . import mapdata
    # Strasbourg, Schiltigheim, Illkirch and Kehl are within 5 km: nudge them apart so the dots do not cover each other
    nudge = {"S02": (-13, -11), "S08": (-15, 12), "S11": (17, 0), "S01": (0, 4)}
    xs = ", ".join(f'store == "{k}", {round((v[0] - mapdata.LON0) * mapdata.K * mapdata.S + nudge.get(k, (0, 0))[0], 1)}' for k, v in STORE_GEO.items())
    ys = ", ".join(f'store == "{k}", {round((mapdata.LAT1 - v[1]) * mapdata.S + nudge.get(k, (0, 0))[1], 1)}' for k, v in STORE_GEO.items())
    towns = ", ".join(f'store == "{k}", "{v[2]}"' for k, v in STORE_GEO.items())
    return f'x = CASE({xs}, 0.0), y = CASE({ys}, 0.0), town = CASE({towns}, "")'


def store_map_query() -> str:
    """Rows for the map: one per store (cabinets at +50, warm, bad frozen cabinets right now, position) and one per truck (position,
    cargo, next stop from the ERP plan, minutes to the planned arrival)."""
    from . import mapdata, trucks
    stores = ("FROM metrics-coldchain.case-default | EVAL rise = coldchain.case.temperature.air - " + NOMINAL +
              " | STATS attacked = COUNT_DISTINCT(device.id) WHERE coldchain.case.setpoint > 5, "
              "warm = COUNT_DISTINCT(device.id) WHERE @timestamp >= NOW() - 10 minutes AND rise > 2 AND coldchain.case.defrost.active == false "
              "AND coldchain.case.setpoint > 5, "
              "bad_now = COUNT_DISTINCT(device.id) WHERE @timestamp >= NOW() - 15 minutes AND @timestamp <= NOW() AND coldchain.application == \"frozen\" "
              f"AND {trucks.BAD_CABINET} BY store = retail.store.id "
              f'| EVAL kind = "store", {geo_cases()}')
    tx = f"ROUND((ST_X(host.geo.location) - {mapdata.LON0}) * {mapdata.K} * {mapdata.S}, 1)"
    ty = f"ROUND(({mapdata.LAT1} - ST_Y(host.geo.location)) * {mapdata.S}, 1)"
    fleet = (trucks.upcoming_stops() + " | INLINE STATS first_arr = MIN(erp.delivery.planned_arrival) BY device.id "
             "| WHERE erp.delivery.planned_arrival == first_arr "
             f'| EVAL kind = "truck", truck = device.id, dest = retail.store.id, cargo = coldchain.truck.cargo, '
             "cargo_temp = ROUND(coldchain.truck.cargo_temp, 1), status = coldchain.truck.status, "
             'eta = DATE_DIFF("minutes", NOW(), erp.delivery.planned_arrival), pallets = erp.cargo.pallets, value = erp.cargo.value_eur, '
             f"delivery = erp.delivery.id, tx = {tx}, ty = {ty} "
             "| KEEP kind, truck, dest, cargo, cargo_temp, status, eta, pallets, value, delivery, tx, ty")
    return f"FROM ({stores}), ({fleet}) | SORT kind, store"


def estate_tiles_query(store: str | None = None) -> str:
    """Four values, each looked up against its normal in kb-baselines; the stripe colour comes from the same thresholds as before."""
    from .baselines import THRESHOLDS as th

    def state(key: str, v: str = "value") -> str:
        x = th[key]
        if x["direction"] == "down":
            return f'CASE({v} < {x["red_below"] // (20 if store else 1)}, "red", "green")'
        if key == "cabinets-warm":  # stores, not cabinets: any alert is red
            return f'CASE({v} >= 1, "red", "green")'
        if "amber" in x:
            return f'CASE({v} >= {x["red"]}, "red", {v} >= {x["amber"]}, "amber", "green")'
        return f'CASE({v} >= {x["red"]}, "red", "green")'

    # Rule 2 ("warm for too long, no defrost") judges the last minutes of the data, so a cabinet that was warm and has been restored
    # reads zero there; its alert stays. The tile counts the stores that rule 2 alerted on in the window.
    sf = f' AND retail.store.id == "{store}"' if store else ""  # one store: every tile is filtered to it
    af = f' AND kibana.alert.suppression.terms.value == "{store}"' if store else ""
    warm = (f'FROM .alerts-security.alerts-default | WHERE {T}{af} AND kibana.alert.rule.name LIKE "*warm for too long*" '
            "| STATS value = COUNT_DISTINCT(kibana.alert.suppression.terms.value)")
    parts = [
        (1, "parameter-changes", "Parameter changes",
         f'FROM logs-coldchain.audit-* | WHERE {T}{sf} AND event.action == "parameter-change" | STATS value = COUNT(*)'),
        (2, "cabinets-reporting", "Cabinets reporting",
         f"FROM metrics-coldchain.case-* | WHERE {T}{sf} | STATS value = COUNT_DISTINCT(device.id)"),
        (3, "cabinets-warm", "Stores alerted: warm, no defrost", warm),
        (4, "open-alerts", "Open alerts", f"FROM .alerts-security.alerts-default | WHERE {T}{af} | STATS value = COUNT(*)"),
    ]
    union = ", ".join(f'({q} | EVAL ord = {o}, key = "{k}", label = "{lab}")' for o, k, lab, q in parts)
    states = ", ".join(f'key == "{k}", {state(k)}' for _, k, _, _ in parts)
    return (f"FROM {union} | EVAL kb.key = key | LOOKUP JOIN kb-baselines ON kb.key "
            '| EVAL normal = ROUND(CASE(key == "parameter-changes", kb.baseline.value * DATE_DIFF("minutes", ?_tstart, ?_tend) / 1440.0, '
            f"kb.baseline.value) / {20 if store else 1}, 0) "  # the baselines are for the estate: a store is a twentieth
            f"| EVAL delta = TO_INTEGER(value - normal), normal = TO_INTEGER(normal), state = CASE({states}, \"green\") "
            "| SORT ord | KEEP ord, label, value, normal, delta, state")


def act1(store: str | None = None) -> Dash:
    """Act 2. With STORE the whole page is filtered to that store (a dot of the map links to it); without, the estate."""
    town = STORE_GEO[store][2] if store else ""
    d = Dash("coldchain-act1b-estate" if not store else f"coldchain-act1b-{store.lower()}",
             "Act 2: The same blip across the whole estate, not on SOC's radar" + (f" ({store} {town})" if store else ""),
             "Synthetic data, fictional chain: 20 stores, 480 cabinets. Central IT's view.")
    sf = f' AND retail.store.id == "{store}"' if store else ""
    # Left: the schematic map of the stores. Right: the four tiles, then the chart.
    custom(d, "Twenty stores on the map", store_map_query(), panels.store_map(store, town), w=20, h=28, show_title=False)
    custom(d, "Estate tiles", estate_tiles_query(store), panels.ESTATE_TILES, w=28, h=9, x=20, show_title=False)
    d.row(9)
    # One native chart (brush a time range to zoom, as in any Kibana chart): hottest and coolest store (median cabinet) as lines, the
    # setpoint changes as vertical bars on the right axis, raised (warming) red and lowered (cooling) blue, stacked.
    q = (f"FROM metrics-coldchain.case-*, logs-coldchain.audit-* | WHERE {T}{sf} AND @timestamp <= NOW() "
         f"| EVAL warm = coldchain.case.temperature.air - {NOMINAL}, "
         'change = event.action == "parameter-change" AND coldchain.parameter.code == "setpoint" '
         "| STATS typical = MEDIAN(warm), "
         "up = COUNT(*) WHERE change AND coldchain.parameter.value.new > coldchain.parameter.value.old, "
         "down = COUNT(*) WHERE change AND coldchain.parameter.value.new < coldchain.parameter.value.old "
         f"BY t = BUCKET(@timestamp, 5 minutes), unit = {'device.id' if store else 'retail.store.id'} "  # a store: hottest and coolest cabinet
         "| STATS hottest = ROUND(MAX(typical), 1), coolest = ROUND(MIN(typical), 1), "
         "warming = SUM(up), cooling = SUM(down) BY t | SORT t")
    cfg = {"type": "xy",
           "layers": [{"type": "bar_stacked", "data_source": esql(q), "x": {"column": "t"},
                       "y": [{"column": "warming", "axis": "y2", "color": {"type": "static", "color": RED}},
                             {"column": "cooling", "axis": "y2", "color": {"type": "static", "color": "#6092C0"}}]},
                      {"type": "line", "data_source": esql(q), "x": {"column": "t"},
                       "y": [{"column": "hottest", "color": {"type": "static", "color": "#E7664C"}},
                             {"column": "coolest", "color": {"type": "static", "color": "#00BFB3"}}]}],
           "axis": {"x": {"title": {"visible": False}, "scale": "temporal"}, "y": {"title": {"text": f"K above nominal (hottest and coolest {'cabinet' if store else 'store'})", "visible": True}},
                    "y2": {"title": {"text": "setpoint changes per 5 minutes: raised (red), lowered (blue)", "visible": True}}},
           "legend": {"visibility": "visible", "placement": "outside", "position": "bottom"}}
    d.add("The estate warms as the setpoints change: hottest and coolest store (median cabinet) and setpoint changes", cfg, 28, 19, x=20, query=q)
    # Logins and setpoint changes in one list, grouped per minute, store, user and source so that the 9 logins stay visible
    # next to the 46 changes and the 46 restores.
    tbl = (f'FROM logs-coldchain.audit-* | WHERE {T}{sf} AND event.action IN ("logged-in", "parameter-change") '
           '| EVAL what = CASE(event.action == "logged-in", "logged in", '
           'CONCAT("setpoint ", TO_STRING(coldchain.parameter.value.old), " -> ", TO_STRING(coldchain.parameter.value.new))), '
           "src = TO_STRING(source.ip) "
           "| STATS n = COUNT(*), t = MAX(@timestamp) BY m = BUCKET(@timestamp, 1 minute), store = retail.store.id, user = user.name, src, what "
           '| SORT t DESC | LIMIT 60 | EVAL time = DATE_FORMAT("MM-dd HH:mm:ss", t), what = CASE(n > 1, CONCAT(what, " x", TO_STRING(n)), what) '
           "| RENAME src AS source | KEEP time, store, user, source, what")
    d.row(19)
    table(d, "Latest logins and setpoint changes", tbl, ["time", "store", "user", "source", "what"], w=48, h=11)
    d.row(11)
    return d


# --- Act 3: the history nobody looked at ---------------------------------------------------------------------------------

ADMIN = 'event.action == "logged-in" AND user.name == "admin"'
OUTSIDE = 'NOT CIDR_MATCH(source.ip, "198.51.100.0/24") AND NOT CIDR_MATCH(source.ip, "10.0.0.0/8")'  # neither a contractor nor a store LAN
# a hit: a setpoint raised above 5 C by an address that is not a contractor's (the warming attack; the contractors' own changes are excluded)
HIT = ('event.action == "parameter-change" AND coldchain.parameter.code == "setpoint" AND coldchain.parameter.value.new > 5 '
       'AND NOT CIDR_MATCH(source.ip, "198.51.100.0/24")')


def history_per_store() -> str:
    """Per store, in the picker's period: admin logins, how many came from an unknown address, setpoint hits, and the first time of each."""
    return (f"FROM logs-coldchain.audit-default | WHERE {T} AND (({ADMIN}) OR ({HIT})) "
            f"| EVAL adm = {ADMIN}, out = adm AND {OUTSIDE}, hit = {HIT}, ip = TO_STRING(source.ip) "
            "| STATS logins = COUNT(*) WHERE adm, outside = COUNT(*) WHERE out, hit_cabs = COUNT_DISTINCT(device.id) WHERE hit, "
            "first_outside = MIN(@timestamp) WHERE out, first_hit = MIN(@timestamp) WHERE hit, ips = VALUES(ip) WHERE out "
            "BY store = retail.store.id")


def history_map_query() -> str:
    """One row per store (all 20, even without events): status hit, visited (an unknown address logged in as admin, nothing changed yet)
    or clear, with the dates, the address and the lead time between the first unknown login and the first hit."""
    return (f'FROM ({history_per_store()}), (FROM kb-assets | WHERE retail.device.role == "system-manager" | EVAL store = retail.store.id | KEEP store) '
            "| STATS logins = MAX(logins), outside = MAX(outside), hit_cabs = MAX(hit_cabs), first_outside = MIN(first_outside), "
            "first_hit = MIN(first_hit), ips = VALUES(ips) BY store "
            "| EVAL logins = COALESCE(logins, 0), outside = COALESCE(outside, 0), hit_cabs = COALESCE(hit_cabs, 0), "
            'status = CASE(hit_cabs > 0, "hit", outside > 0, "visited", "clear"), '
            'lead_days = CASE(outside > 0 AND hit_cabs > 0 AND first_hit > first_outside, DATE_DIFF("days", first_outside, first_hit), -1), '
            'first_outside_txt = DATE_FORMAT("yyyy-MM-dd", first_outside), first_hit_txt = DATE_FORMAT("yyyy-MM-dd", first_hit), '
            'from_ip = MV_CONCAT(ips, ", "), '
            'from_lbl = DATE_FORMAT("yyyy-MM-dd", ?_tstart), to_lbl = DATE_FORMAT("yyyy-MM-dd", ?_tend), '
            f"{geo_cases()} | SORT store")


def history_tiles_query() -> str:
    """One row for the four cards, from the same per-store numbers as the map."""
    return (f"{history_per_store()} "
            "| STATS visited = COUNT(*) WHERE outside > 0, hit_stores = COUNT(*) WHERE hit_cabs > 0, "
            "next_stores = COUNT(*) WHERE outside > 0 AND hit_cabs == 0, outside_logins = SUM(outside), all_logins = SUM(logins), "
            "first_outside = MIN(first_outside) "
            '| EVAL first_txt = DATE_FORMAT("yyyy-MM-dd", first_outside)')


def act3() -> Dash:
    d = Dash("coldchain-act3-history", "Act 3: The history nobody looked at",
             "Which stores an unknown address logged in to as admin in the last 12 months, and which of them the warming attack has hit. Synthetic data.",
             time=("now-1y", "now"))
    custom(d, "Stores visited by an unknown address", history_map_query(), panels.history_map(), w=20, h=28, show_title=False)
    custom(d, "History tiles", history_tiles_query(), panels.HISTORY_TILES, w=28, h=9, x=20, show_title=False)
    d.row(9)
    q = (f"FROM logs-coldchain.audit-default | WHERE {T} AND {ADMIN} AND {OUTSIDE} "
         "| STATS logins = COUNT(*) BY week = BUCKET(@timestamp, 40, ?_tstart, ?_tend)")  # about 40 bars, whatever the period
    cfg = {"type": "xy", "layers": [{"type": "bar", "data_source": esql(q), "x": {"column": "week"},
                                     "y": [{"column": "logins", "label": "outside admin logins", "color": {"type": "static", "color": RED}}]}],
           "axis": {"x": {"title": {"visible": False}}, "y": {"title": {"text": "outside admin logins", "visible": True}}},
           "legend": {"visibility": "hidden"}, "styling": {"overlays": {"partial_buckets": {"visible": True}}}}
    d.add("Outside admin logins over time (brush a range to zoom the page)", cfg, 28, 19, x=20, query=q)
    d.row(19)
    return d


# --- Act 5: the POS lead (hypothetical) ----------------------------------------------------------------------------------

# The POS scenario is a fixed three-week story: its panels do not follow the time picker.
ET = '@timestamp >= "2026-10-22T00:00:00Z" AND @timestamp < "2026-11-12T00:00:00Z"'

EVIDENCE = """FROM logs-network_traffic.tls-pos
| WHERE @timestamp >= "2026-10-22T00:00:00Z" AND @timestamp < "2026-11-12T00:00:00Z" AND retail.store.id == "S07"
| EVAL host.ip = TO_STRING(source.ip), tls.client.server_name = TO_STRING(tls.client.server_name)
| LOOKUP JOIN kb-assets-by-ip ON host.ip
| LOOKUP JOIN kb-device-profiles ON retail.device.role, tls.client.server_name
| WHERE profile.allowed IS NULL
| STATS received = SUM(destination.bytes), chunks = COUNT(*), nights = COUNT_DISTINCT(DATE_TRUNC(1 day, @timestamp)),
        first_seen = MIN(@timestamp), ja3 = VALUES(tls.client.ja3) BY host = host.name, server = tls.client.server_name
| EVAL received_gb = ROUND(received / 1073741824.0, 2), first_seen_txt = DATE_FORMAT("yyyy-MM-dd", first_seen)
| SORT received DESC
| KEEP host, server, received_gb, chunks, nights, first_seen_txt, ja3
| LIMIT 3"""


def pos() -> Dash:
    d = Dash("coldchain-pos-evidence", "Act 5: The POS that nobody watched",
             "Hypothetical scenario, synthetic data: a back-office POS PC downloads 4 GB at night and then reaches the refrigeration system manager.",
             time=("2026-10-22T00:00:00.000Z", "2026-11-11T23:59:59.000Z"))
    custom(d, "What the S07 back-office POS talked to that its profile does not allow", EVIDENCE, panels.POS_EVIDENCE, w=48, h=9)
    d.row(9)
    s = "logs-netflow.summary-pos"
    lines(d, "Bytes received per night: the S07 back-office POS against its 19 peers (MB)",
          f'FROM {s} | WHERE {ET} AND retail.device.role == "pos-backoffice" '
          "| STATS b = SUM(destination.bytes) BY day = BUCKET(@timestamp, 1 day), host.name "
          '| EVAL who = CASE(host.name == "S07-POS-BO-01", "S07-POS-BO-01", "average peer") '
          "| STATS mb = ROUND(AVG(b) / 1000000.0, 1) BY day, who", "day", ["mb"], w=24, h=12, by="who", kind="bar")
    lines(d, "CPU: the S07 back-office POS against its peers (%)",
          "FROM logs-pos.terminal-pos | WHERE " + ET + ' AND retail.device.role == "pos-backoffice" '
          '| EVAL who = CASE(host.name == "S07-POS-BO-01", "S07-POS-BO-01", "average peer") '
          "| STATS cpu = ROUND(AVG(host.cpu.usage) * 100, 0) BY t = BUCKET(@timestamp, 6 hours), who", "t", ["cpu"], w=24, h=12, x=24, by="who")
    d.row(12)
    lines(d, "Free disk (%)", "FROM logs-pos.terminal-pos | WHERE " + ET + ' AND retail.device.role == "pos-backoffice" '
          '| EVAL who = CASE(host.name == "S07-POS-BO-01", "S07-POS-BO-01", "average peer") '
          "| STATS free = ROUND(AVG(coldchain.pos.disk_free_pct), 0) BY t = BUCKET(@timestamp, 6 hours), who", "t", ["free"], w=24, h=10, by="who")
    table(d, "First time inside store S07: who called whom",
          f'FROM {s} | WHERE {ET} AND retail.store.id == "S07" AND CIDR_MATCH(source.ip, "10.7.0.0/16") '
          'AND CIDR_MATCH(destination.ip, "10.7.0.0/16") AND retail.device.role == "pos-backoffice" '
          "| STATS first_seen = MIN(@timestamp), flows = COUNT(*) BY from = host.name, to = destination.ip, port = destination.port "
          "| EVAL first_seen = DATE_FORMAT(\"yyyy-MM-dd\", first_seen) | SORT first_seen DESC | LIMIT 8",
          ["first_seen", "from", "to", "port", "flows"], w=24, h=10, x=24)
    d.row(10)
    return d


def hunt() -> Dash:
    d = Dash("coldchain-hunt-findings", "Act 4: Hunting agent - the agent that keeps looking",
             "Findings of the scheduled hunt by the SOC agent (an Elastic Workflow every 30 minutes). Synthetic data.", time=("now-24h", "now"))
    d.panels.append(md("## Nobody asked, and something is going on\nEvery 30 minutes a workflow asks the SOC agent to sweep the estate: live "
                       "data, a year of history, device profiles, exposure. It records what is abnormal, with a proposed action. It proposes, it "
                       "runs nothing. **AlertZero is not offered on every deployment, so this is the same pattern built from Elastic Workflows and "
                       "Agent Builder (preview).**", h=5, d=d))
    d.row(5)
    tiles = (("critical", "Critical findings", RED), ("high", "High findings", AMBER), ("medium", "Medium findings", "#6092C0"))
    for i, (sev, title, color) in enumerate(tiles):
        metric(d, title, f'FROM cc-hunt-findings | WHERE severity == "{sev}" | STATS findings = COUNT(*)', "findings", w=12, x=12 * i)
        d.panels[-1]["config"]["metrics"][0]["color"] = {"type": "dynamic", "range": "absolute", "steps": [
            {"lt": 1, "color": GREEN}, {"gte": 1, "color": color}]}
    metric(d, "Stores involved", "FROM cc-hunt-findings | STATS stores = COUNT_DISTINCT(stores)", "stores", w=12, x=36)
    d.row(6)
    q = ("FROM cc-hunt-findings | EVAL rank = CASE(severity == \"critical\", 0, severity == \"high\", 1, severity == \"medium\", 2, 3) "
         "| SORT rank, @timestamp DESC | LIMIT 12 | EVAL stores_txt = MV_CONCAT(stores, \", \") "
         "| KEEP severity, title, stores_txt, why_abnormal, proposed_action")
    custom(d, "What the agent found", q, panels.FINDINGS, w=48, h=26)
    d.row(26)
    return d


# Ids are listed, not read from the builders.
DASHBOARDS = {"coldchain-act0-sources": act0, "coldchain-act0-lit": act0_lit, "coldchain-act1a-cabinet": act1a, "coldchain-act1b-estate": act1,
              "coldchain-act3-history": act3, "coldchain-hunt-findings": hunt, "coldchain-pos-evidence": pos}
# one Act 2 page per store, opened by clicking its dot on the map
for _s in STORE_GEO:
    DASHBOARDS[f"coldchain-act1b-{_s.lower()}"] = (lambda s=_s: act1(s))
# one Act 1 page per other cabinet of store 07, opened by clicking its number in the layout
for _n in range(1, 25):
    _cab = f"S07-C{_n:02d}"
    if _cab != CONTRACTOR_CABINET:
        DASHBOARDS[f"coldchain-act1a-{_cab.lower()}"] = (lambda c=_cab: act1a(c))


# --- push / check ------------------------------------------------------------------------------------------------

def kibana() -> tuple[str, requests.Session]:
    e = load_env()
    s = requests.Session()
    s.headers.update({"Authorization": f"ApiKey {e['ELASTIC_API_KEY']}", "kbn-xsrf": "true",
                      "Content-Type": "application/json", "elastic-api-version": "2023-10-31"})
    return e["KIBANA_URL"].rstrip("/"), s


def build(only: str | None, rng: list[str] | None) -> list[Dash]:
    out = []
    for i, f in DASHBOARDS.items():
        if only and only != i:
            continue
        d = f()
        if rng:
            d.time = (rng[0], rng[1])
        out.append(d)
    return out


def push(only: str | None, rng: list[str] | None) -> int:
    url, s = kibana()
    bad = 0
    for d in build(only, rng):
        r = s.put(f"{url}/api/dashboards/{d.id}", json=d.body(), timeout=60)
        if r.status_code >= 400:
            bad += 1
            msg = r.json().get("message", r.text)
            print(f"{d.id}: {r.status_code}\n" + "\n".join(l for l in msg.split("\n") if "expected value to equal" not in l)[:2500])
        else:
            print(f"{d.id}: {r.status_code} {url}/app/dashboards#/view/{d.id}")
    return bad


def check(only: str | None, rng: list[str] | None) -> int:
    es = client()
    bad = 0
    for d in build(only, rng):
        w0, w1 = d.time
        print(f"== {d.id}  range {w0} -> {w1}")
        tstart = rng[0] if rng else None
        for title, q, params in d.queries:
            ps = [{"_tstart": tstart or _abs(w0)}, {"_tend": (rng[1] if rng else _abs(w1))}] + [{k: v} for k, v in params.items()]
            try:
                r = es.esql.query(query=q, params=ps, format="json")
                print(f"  ok   {len(r['values']):>4} rows  {title}  {json.dumps(r['values'][0], default=str)[:110] if r['values'] else ''}")
            except Exception as e:
                bad += 1
                print(f"  FAIL {title}: {str(e)[:300]}")
    return bad


def _abs(v: str) -> str:
    """Relative range ends (now-1h) are turned into absolute times for the check."""
    from datetime import datetime, timedelta, timezone
    if not v.startswith("now"):
        return v
    t = datetime.now(timezone.utc)
    if "-" in v:
        n = v.split("-", 1)[1]
        k = int(n[:-1])
        t -= {"m": timedelta(minutes=k), "h": timedelta(hours=k), "d": timedelta(days=k), "y": timedelta(days=365 * k)}[n[-1]]
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["push", "check", "list", "delete"])
    ap.add_argument("--only")
    ap.add_argument("--range", nargs=2, metavar=("FROM", "TO"))
    a = ap.parse_args(argv)
    if a.cmd == "push":
        sys.exit(1 if push(a.only, a.range) else 0)
    if a.cmd == "check":
        sys.exit(1 if check(a.only, a.range) else 0)
    url, s = kibana()
    for i in DASHBOARDS:
        if a.cmd == "delete" and (not a.only or a.only == i):
            print(i, s.delete(f"{url}/api/dashboards/{i}", timeout=60).status_code)
        elif a.cmd == "list":
            print(i, s.get(f"{url}/api/dashboards/{i}", timeout=60).status_code)


if __name__ == "__main__":
    main()
