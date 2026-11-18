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


def act1a() -> Dash:
    """What one contractor sees: a single cabinet, no estate, no alerts. Same indexed data as 1b, filtered to one device."""
    cab = f'device.id == "{CONTRACTOR_CABINET}"'
    d = Dash("coldchain-act1a-cabinet", "Act 1: Store 07, Colmar, from above - what each system says",
             "Synthetic data. Only this cabinet: no other cabinet, no store comparison, no alerts.")
    custom(d, "Store 07 from above", STORE_QUERY, panels.STORE_LAYOUT, w=48, h=32, show_title=False)
    d.row(32)
    tile = lambda title, q, col, x: metric(d, title, q, col, w=16, x=x)
    tile("Setpoint now (°C)", f"FROM metrics-coldchain.case-* | WHERE {cab} AND {T} AND @timestamp <= NOW() "
         "| SORT @timestamp DESC | LIMIT 1 | EVAL setpoint = ROUND(coldchain.case.setpoint, 1) | KEEP setpoint", "setpoint", 0)
    tile("Air temperature now (°C)", f"FROM metrics-coldchain.case-* | WHERE {cab} AND {T} AND @timestamp <= NOW() "
         "| SORT @timestamp DESC | LIMIT 1 | EVAL air = ROUND(coldchain.case.temperature.air, 1) | KEEP air", "air", 16)
    tile("Parameter changes on this cabinet", f'FROM logs-coldchain.audit-* | WHERE {cab} AND {T} AND event.action == "parameter-change" '
         "| STATS changes = COUNT(*)", "changes", 32)
    d.row(6)
    q = (f"FROM metrics-coldchain.case-* | WHERE {cab} AND {T} AND @timestamp <= NOW() "
         "| STATS air = ROUND(AVG(coldchain.case.temperature.air), 1), setpoint = ROUND(AVG(coldchain.case.setpoint), 1) "
         "BY t = BUCKET(@timestamp, 5 minutes) | SORT t")
    cfg = {"type": "xy", "layers": [{"type": "line", "data_source": esql(q), "x": {"column": "t"},
                                     "y": [{"column": "air"}, {"column": "setpoint", "axis": "y2", "color": {"type": "static", "color": RED}}]}],
           "axis": {"x": {"title": {"visible": False}}, "y": {"title": {"text": "air temperature °C", "visible": True}},
                    "y2": {"title": {"text": "setpoint °C", "visible": True}}},
           "legend": {"visibility": "visible", "placement": "outside", "position": "bottom"}}
    d.add(f"{CONTRACTOR_CABINET}: air temperature and setpoint", cfg, 48, 12, query=q)
    d.row(12)
    table(d, "Changes on this cabinet",
          f'FROM logs-coldchain.audit-* | WHERE {cab} AND {T} AND event.action == "parameter-change" '
          '| SORT @timestamp DESC | LIMIT 15 | EVAL time = DATE_FORMAT("MM-dd HH:mm", @timestamp) '
          "| RENAME user.name AS user, source.ip AS source, coldchain.parameter.code AS parameter, "
          "coldchain.parameter.value.old AS old, coldchain.parameter.value.new AS new | KEEP time, user, source, parameter, old, new",
          ["time", "user", "source", "parameter", "old", "new"], h=10)
    d.row(10)
    return d


def act1() -> Dash:
    d = Dash("coldchain-act1b-estate", "Act 2: The same blip across the whole estate, not on SOC's radar",
             "Synthetic data, fictional chain: 20 stores, 480 cabinets. Central IT's view.")
    metric(d, "Parameter changes", f'FROM logs-coldchain.audit-* | WHERE {T} AND event.action == "parameter-change" '
                                   '| STATS changes = COUNT(*)', "changes", x=0,
           normal=("parameter-changes", True))
    metric(d, "Cabinets reporting", f"FROM metrics-coldchain.case-* | WHERE {T} | STATS cabinets = COUNT_DISTINCT(device.id)",
           "cabinets", x=12, normal=("cabinets-reporting", False))
    metric(d, "Cabinets warm, no defrost",
           f"FROM metrics-coldchain.case-* | WHERE {T} AND @timestamp <= NOW() | INLINE STATS newest = MAX(@timestamp) "
           f"| STATS late_warm = COUNT(*) WHERE {WARM_ROW}, relay_on = COUNT(*) WHERE coldchain.case.defrost.active == true AND @timestamp >= newest - 60 minutes "
           "BY device.id | WHERE late_warm >= 3 AND relay_on == 0 | STATS cabinets = COUNT(*)", "cabinets", x=24,
           normal=("cabinets-warm", False))
    metric(d, "Open alerts", f"FROM .alerts-security.alerts-default | WHERE {T} | STATS alerts = COUNT(*)", "alerts", x=36,
           normal=("open-alerts", False))
    d.row(6)
    q = (f"FROM metrics-coldchain.case-default | EVAL rise = coldchain.case.temperature.air - {NOMINAL} "
         "| STATS attacked = COUNT_DISTINCT(device.id) WHERE coldchain.case.setpoint > 5, "
         "warm = COUNT_DISTINCT(device.id) WHERE @timestamp >= NOW() - 10 minutes AND rise > 2 AND coldchain.case.defrost.active == false "
         "AND coldchain.case.setpoint > 5 BY store = retail.store.id | SORT store")
    custom(d, "Twenty stores, one look", q, panels.STORE_GRID, w=48, h=9)
    d.row(9)
    # One query over telemetry and audit: every 5-minute slot has a value, so the red line sits at 0 between changes.
    q = (f"FROM metrics-coldchain.case-*, logs-coldchain.audit-* | WHERE {T} AND @timestamp <= NOW() "
         f"| EVAL warm = coldchain.case.temperature.air - {NOMINAL} "
         '| STATS typical = MEDIAN(warm), chg = COUNT(*) WHERE event.action == "parameter-change" '
         "BY t = BUCKET(@timestamp, 5 minutes), retail.store.id "
         "| STATS hottest = ROUND(MAX(typical), 1), coolest = ROUND(MIN(typical), 1), changes = SUM(chg) BY t | SORT t")
    cfg = {"type": "xy", "layers": [{"type": "line", "data_source": esql(q), "x": {"column": "t"},
                                     "y": [{"column": "hottest"}, {"column": "coolest"},
                                           {"column": "changes", "axis": "y2", "color": {"type": "static", "color": RED}}]}],
           "axis": {"x": {"title": {"visible": False}}, "y": {"title": {"text": "K above nominal", "visible": True}},
                    "y2": {"title": {"text": "parameter changes per 5 minutes", "visible": True}}},
           "legend": {"visibility": "visible", "placement": "outside", "position": "bottom"}}
    d.add("The estate warms as the setpoints change: hottest and coolest store (median cabinet) and parameter changes", cfg, 48, 12,
          query=q)
    d.row(12)
    table(d, "Latest parameter changes",
          f'FROM logs-coldchain.audit-* | WHERE {T} AND event.action == "parameter-change" '
          "| SORT @timestamp DESC | LIMIT 15 | EVAL time = DATE_FORMAT(\"MM-dd HH:mm\", @timestamp) "
          "| RENAME retail.store.id AS store, device.id AS cabinet, user.name AS user, source.ip AS source, "
          "coldchain.parameter.code AS parameter, coldchain.parameter.value.old AS old, coldchain.parameter.value.new AS new "
          "| KEEP time, store, cabinet, user, source, parameter, old, new",
          ["time", "store", "cabinet", "user", "source", "parameter", "old", "new"], w=30, h=10)
    lines(d, "Alerts per store and rule",
          f'FROM .alerts-security.alerts-default | WHERE {T} AND kibana.alert.rule.name LIKE "Cold chain:*" '
          '| EVAL rule = CASE(kibana.alert.rule.name LIKE "*outside documented*", "Setpoint outside normal", '
          'kibana.alert.rule.name LIKE "*warm for too long*", "Warm, no defrost", kibana.alert.rule.name) '
          "| STATS alerts = COUNT(*) BY store = kibana.alert.suppression.terms.value, rule | SORT store", "store", ["alerts"], w=18, h=10, x=30,
          by="rule", kind="bar", ytitle="alerts")
    d.row(10)
    table(d, "What central IT knows about the estate (inventory), and what reports live",
          'FROM kb-assets | EVAL role = COALESCE(retail.device.role, "cabinet") | STATS devices = COUNT(*) BY role '
          '| EVAL live_feed = CASE(role == "cabinet", "telemetry and audit", role == "temperature-logger", "probe readings", '
          'role == "system-manager", "audit and flows", role IN ("pos-lane", "pos-backoffice"), "network flows (scenario)", "inventory only") | SORT devices DESC | KEEP role, devices, live_feed',
          ["role", "devices", "live_feed"], h=9)
    d.row(9)
    return d


# --- Act 3: the history nobody looked at ---------------------------------------------------------------------------------

OUTSIDE_LOGINS = ('WHERE event.action == "logged-in" AND NOT CIDR_MATCH(source.ip, "198.51.100.0/24") '
                  'AND NOT CIDR_MATCH(source.ip, "10.0.0.0/8")')
YEAR = {"from": "now-1y", "to": "now"}


def act3() -> Dash:
    d = Dash("coldchain-act3-history", "Act 3: The history nobody looked at",
             "A year of store audit. The same internet address logged in to three stores months before the attack. Synthetic data.",
             time=("now-1y", "now"))
    metric(d, "Events in the history", "FROM logs-coldchain.audit-default | STATS events = COUNT(*)", "events", w=16)
    metric(d, "Days of history", 'FROM logs-coldchain.audit-default | STATS days = DATE_DIFF("days", MIN(@timestamp), MAX(@timestamp))', "days", w=16, x=16)
    metric(d, "Stores an outsider logged in to", f"FROM logs-coldchain.audit-default | {OUTSIDE_LOGINS} | STATS stores = COUNT_DISTINCT(retail.store.id)",
           "stores", w=16, x=32)
    for pn in d.panels:
        pn["config"]["time_range"] = YEAR
    d.row(6)
    q = (f"FROM logs-coldchain.audit-default | {OUTSIDE_LOGINS} "
         "| STATS first_seen = MIN(@timestamp) BY store = retail.store.id | EVAL days_ago = DATE_DIFF(\"days\", first_seen, NOW()), "
         "first_seen_txt = DATE_FORMAT(\"yyyy-MM-dd HH:mm\", first_seen) | SORT first_seen | KEEP store, days_ago, first_seen_txt")
    custom(d, "When the same address first logged in to each store", q, panels.FIRST_VISITS, w=48, h=12)
    d.row(12)
    q = (f"FROM logs-coldchain.audit-default | {OUTSIDE_LOGINS} "
         "| STATS stores = COUNT_DISTINCT(retail.store.id) BY week = BUCKET(@timestamp, 1 week)")
    cfg = {"type": "xy", "layers": [{"type": "bar", "data_source": esql(q), "x": {"column": "week"},
                                     "y": [{"column": "stores", "label": "stores with an outside login", "color": {"type": "static", "color": RED}}]}],
           "axis": {"x": {"title": {"visible": False}}, "y": {"title": {"text": "stores per week", "visible": True}}},
           "legend": {"visibility": "hidden"}, "time_range": YEAR}
    d.add("Outside logins per week over the year", cfg, 48, 10, query=q)
    d.row(10)
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
DASHBOARDS = {"coldchain-act0-sources": act0, "coldchain-act1a-cabinet": act1a, "coldchain-act1b-estate": act1,
              "coldchain-act3-history": act3, "coldchain-hunt-findings": hunt, "coldchain-pos-evidence": pos}


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
