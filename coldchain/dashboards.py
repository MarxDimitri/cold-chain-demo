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
from .federation import env

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
        ("coldchain-act1a-cabinet", "Act 1", "One cabinet"),
        ("coldchain-act1b-estate", "Act 2", "The whole estate"),
        ("coldchain-act5a-history", "Act 3a", "History read in place"),
        ("coldchain-act5b-history-frozen", "Act 3b", "History on the frozen tier"),
        ("coldchain-hunt-findings", "Act 4", "Hunting agent"),
        ("coldchain-epilogue-edge", "Act 5", "Edge devices")]
NAV_HEIGHT = 3


def _link(i: int) -> str:
    did, label, words = ACTS[i]
    return f"[**{label}** {words}](/app/dashboards#/view/{did})"


def nav_panel(dash_id: str) -> dict | None:
    """A strip with links to the previous and next act, and to every act."""
    ids = [a[0] for a in ACTS]
    if dash_id not in ids:
        return None
    i = ids.index(dash_id)
    prev = f"\u25C0 {_link(i - 1)}" if i > 0 else "&nbsp;"
    nxt = f"{_link(i + 1)} \u25B6" if i < len(ACTS) - 1 else "&nbsp;"
    strip = " \u00B7 ".join(f"**{a[1]}**" if j == i else f"[{a[1]}](/app/dashboards#/view/{a[0]})" for j, a in enumerate(ACTS))
    return {"type": "markdown", "grid": {"x": 0, "y": 0, "w": 48, "h": NAV_HEIGHT},
            "config": {"content": f"{prev} &nbsp;&nbsp;|&nbsp;&nbsp; {strip} &nbsp;&nbsp;|&nbsp;&nbsp; {nxt}",
                       "settings": {"open_links_in_new_tab": True}}}


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


# --- Act 0: every source of truth, one language ----------------------------------------------------------------------

TIER_COLORS = {"Indexed": "#6092C0", "Frozen tier": "#9170B8", "Raw in S3": "#54B399", "Knowledge base": "#F5A700", "Produced": "#D36086"}
ALL_TIME = {"from": "now-10y", "to": "now"}  # these panels read a catalog without @timestamp: the picker must not matter


def act0() -> Dash:
    d = Dash("coldchain-act0-sources", "CC Act 0: The realms you usually do not watch",
             "Every dataset the demo uses, in five tiers, all read with ES|QL. Counts measured with `make sources`. Synthetic data.",
             time=("now-1y", "now"))
    # The streetlight effect, as a chart: we search where the light is (the live index, 35 days); the dark is the year of
    # history that only exists in raw files and on the frozen tier. It sits on top, under the navigation strip.
    lit = ('FROM cc-history-audit | WHERE @timestamp >= NOW() - 35 days | STATS events = COUNT(*) BY week = BUCKET(@timestamp, 1 week) '
           '| SORT week')
    dark = ('FROM cc-history-audit | WHERE @timestamp < NOW() - 35 days | STATS events = COUNT(*) BY week = BUCKET(@timestamp, 1 week) '
            '| SORT week')
    layers = [{"type": "bar", "data_source": esql(q), "x": {"column": "week"},
               "y": [{"column": "events", "label": label, "color": {"type": "static", "color": color}}]}
              for q, label, color in ((dark, "In the dark: only in raw files and on the frozen tier", "#343741"),
                                      (lit, "Under the streetlight: the live index, 35 days", "#F5A700"))]
    d.add("Store audit events per week: what the light covers, and what it does not",
          {"type": "xy", "layers": layers, "time_range": {"from": "now-1y", "to": "now"},
           "axis": {"x": {"title": {"visible": False}}, "y": {"title": {"text": "audit events", "visible": True}}},
           "legend": {"visibility": "visible", "placement": "outside", "position": "bottom"}}, 48, 10, query=dark)
    d.queries.append(("streetlight (lit layer)", lit, {}))
    d.row(10)
    d.panels.append(md("## Every source of truth, one platform, one language\n"
                       "Telemetry, audit, network flows, a year of raw history in S3, the knowledge base, and what the agent finds: "
                       "different shapes, different storage, different cost. **One platform and one language, ES|QL**, reads all of them, "
                       "so you can ask a question nobody modelled in advance. Every tile, chart and table on this page is an ES|QL query "
                       "(raw files are counted once with `make sources`).\n\n"
                       "```\nFROM logs-coldchain.audit-default     // live index: 35 days, milliseconds\n"
                       "FROM cc-history-audit               // frozen tier: 12 months, about a second\n"
                       "FROM raw_store_audit                // raw files in S3, never ingested: 12 months, about 80 seconds (experimental)\n"
                       "FROM kb-assets | ...                // the knowledge base: context joined to any of them\n```", h=9, d=d))
    d.row(9)
    from .sources import CORRELATION  # one statement over the live index, the raw files and the knowledge base
    d.panels.append(md("### One statement, three sources\nCorrelate across different sources in one ES|QL statement: the live index and the raw "
                       "files in S3 (two subqueries), joined to the knowledge base. Which stores did the attacker's address visit, when "
                       "first, where is that on record, and whose contractor account runs each store? The result below was measured when "
                       "`make sources` last ran (about 75 s: the raw files are read in place); run `make correlation` after the attack to "
                       "see today's visits next to the history.\n\n```\n" + CORRELATION + "\n```", h=14, d=d))
    d.row(14)
    q = ("FROM cc-esql-correlation | SORT first_seen | EVAL first_seen = DATE_FORMAT(\"yyyy-MM-dd HH:mm\", first_seen), "
         "measured = DATE_FORMAT(\"yyyy-MM-dd HH:mm\", measured_at) | KEEP store, contractor, visits, first_seen, seen_in, seconds, measured")
    cols = [("store", 80), ("contractor", 110), ("visits", 80), ("first_seen", 160), ("seen_in", 330), ("seconds", 90), ("measured", 160)]
    d.add("Attacker address: visits per store, where it is on record, and the contractor account", {
        "type": "data_table", "time_range": ALL_TIME, "data_source": esql(q), "metrics": [{"column": c, "width": w} for c, w in cols]},
        48, 9, query=q)
    d.row(9)
    for i, tier in enumerate(TIER_COLORS):
        q = f'FROM kb-sources | WHERE tier == "{tier}" | STATS rows = SUM(rows), sources = COUNT(*)'
        d.add(tier, {"type": "metric", "data_source": esql(q), "time_range": ALL_TIME, "metrics": [
            {"type": "primary", "column": "rows", "label": " ", "color": {"type": "static", "color": TIER_COLORS[tier]}},
            {"type": "secondary", "column": "sources", "label": "sources"}]}, 9, 6, 1 + 9 * i, query=q)
    d.row(6)
    q = "FROM kb-sources | WHERE rows > 0 | EVAL size = ROUND(LOG10(rows), 2) | SORT size DESC | KEEP source, tier, size"
    lines(d, "How big: orders of magnitude of rows (log10)", q, "source", ["size"], w=24, h=14, by="tier", kind="bar", ytitle="log10 rows")
    d.panels[-1]["config"]["time_range"] = ALL_TIME
    q = "FROM kb-sources | WHERE days IS NOT NULL | SORT days DESC | KEEP source, tier, days"
    lines(d, "How far back each source reaches (days)", q, "source", ["days"], w=24, h=14, x=24, by="tier", kind="bar", ytitle="days")
    d.panels[-1]["config"]["time_range"] = ALL_TIME
    d.row(14)
    q = ("FROM kb-sources | SORT tier_order, rows DESC | EVAL first_seen = DATE_FORMAT(\"yyyy-MM-dd\", first_seen), last_seen = DATE_FORMAT(\"yyyy-MM-dd\", last_seen) "
         "| KEEP tier, source, what, rows, first_seen, last_seen, ask_with")
    cols = [("tier", 120), ("source", 250), ("what", 640), ("rows", 110), ("first_seen", 100), ("last_seen", 100), ("ask_with", 380)]
    d.add("Where each source lives and how to ask it", {"type": "data_table", "time_range": ALL_TIME, "data_source": esql(q),
          "metrics": [{"column": c, "width": w} for c, w in cols]}, 48, 17, query=q)
    d.row(17)
    return d


# --- Act 1: the estate -------------------------------------------------------------------------------------------

CONTRACTOR_CABINET = "S07-C05"  # one of the 46 attacked cabinets: what the contractor's portal shows


def act1a() -> Dash:
    """What one contractor sees: a single cabinet, no estate, no alerts. Same indexed data as 1b, filtered to one device."""
    cab = f'device.id == "{CONTRACTOR_CABINET}"'
    d = Dash("coldchain-act1a-cabinet", "CC Act 1: One cabinet, the contractor's view",
             "Synthetic data. Only this cabinet: no other cabinet, no store comparison, no alerts.")
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
    d = Dash("coldchain-act1b-estate", "CC Act 2: The same blip across the whole estate, not on SOC's radar",
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
          'role == "system-manager", "audit and flows", "inventory only") | SORT devices DESC | KEEP role, devices, live_feed',
          ["role", "devices", "live_feed"], h=9)
    d.row(9)
    return d


# --- Epilogue: the TV box (hypothetical) -------------------------------------------------------------------------

# The epilogue is a fixed three-week story: its panels do not follow the time picker.
ET = '@timestamp >= "2026-10-22T00:00:00Z" AND @timestamp < "2026-11-12T00:00:00Z"'

EVIDENCE = """FROM raw_store_tls
| WHERE @timestamp >= "2026-10-22T00:00:00Z" AND @timestamp < "2026-11-12T00:00:00Z" AND retail.store.id == "S07"
| EVAL host.ip = TO_STRING(source.ip), tls.client.server_name = TO_STRING(tls.client.server_name)
| LOOKUP JOIN kb-assets-by-ip ON host.ip
| LOOKUP JOIN kb-device-profiles ON retail.device.role, tls.client.server_name
| WHERE profile.allowed IS NULL
| STATS received = SUM(destination.bytes), chunks = COUNT(*), nights = COUNT_DISTINCT(DATE_TRUNC(1 day, @timestamp)),
        ja3 = VALUES(tls.client.ja3) BY host.name, tls.client.server_name
| EVAL received_gb = ROUND(received / 1073741824.0, 2)
| SORT received DESC
| KEEP host.name, tls.client.server_name, received_gb, chunks, nights, ja3
| LIMIT 10"""


def epilogue() -> Dash:
    d = Dash("coldchain-epilogue-edge", "CC Act 5: Edge devices on no one’s radar",
             "Scenario B, hypothetical and synthetic: a TV box that downloads 4.6 GB over nine nights.",
             time=("2026-10-22T00:00:00.000Z", "2026-11-11T23:59:59.000Z"))
    d.panels.append(md("## Follow the lead: the quiet TV box\n**Hypothetical scenario, synthetic data.** The hunting agent (Act 4) found a TV box "
                       "talking to a store's system manager, a path no rule watches. This is the evidence. Detection runs on the indexed "
                       "flow summaries and the edge metrics. The evidence table at the bottom reads the raw TLS records "
                       "**in place from S3** (data federation, experimental).", h=4, d=d))
    d.row(4)
    s = "logs-netflow.summary-epilogue"
    lines(d, "Bytes received per night: the S07 TV box against its 19 peers (MB)",
          f'FROM {s} | WHERE {ET} AND retail.device.role == "tv-box" '
          "| STATS b = SUM(destination.bytes) BY day = BUCKET(@timestamp, 1 day), host.name "
          '| EVAL who = CASE(host.name == "S07-TVBOX-01", "S07-TVBOX-01", "average peer") '
          "| STATS mb = ROUND(AVG(b) / 1000000.0, 1) BY day, who", "day", ["mb"], w=24, h=12, by="who", kind="bar")
    lines(d, "Signage player CPU (S07-SIG-02 against its peers)",
          "FROM logs-signage.cms-epilogue | WHERE " + ET + ' | EVAL who = CASE(host.name == "S07-SIG-02", "S07-SIG-02", "average peer") '
          "| STATS cpu = ROUND(AVG(host.cpu.usage) * 100, 0) BY t = BUCKET(@timestamp, 6 hours), who", "t", ["cpu"], w=24, h=12,
          x=24, by="who")
    d.row(12)
    lines(d, "Signage free storage (%)", "FROM logs-signage.cms-epilogue | WHERE " + ET +
          ' | EVAL who = CASE(host.name == "S07-SIG-02", "S07-SIG-02", "average peer") '
          "| STATS free = ROUND(AVG(coldchain.edge.storage.free_pct), 0) BY t = BUCKET(@timestamp, 6 hours), who", "t", ["free"],
          w=24, h=10, by="who")
    lines(d, "TV box power draw (W)", "FROM logs-power.plug-epilogue | WHERE " + ET +
          ' | EVAL who = CASE(host.name == "S07-PLUG-01", "S07 TV box", "average peer") '
          "| STATS watts = ROUND(AVG(coldchain.edge.power.watts), 1) BY t = BUCKET(@timestamp, 6 hours), who", "t", ["watts"],
          w=24, h=10, x=24, by="who")
    d.row(10)
    table(d, "Internal flows in store S07, first seen",
          f'FROM {s} | WHERE {ET} AND retail.store.id == "S07" AND CIDR_MATCH(source.ip, "10.7.0.0/16") '
          'AND CIDR_MATCH(destination.ip, "10.7.0.0/16") '
          "| STATS first_seen = MIN(@timestamp), flows = COUNT(*) BY source.ip, destination.ip, destination.port "
          "| SORT first_seen DESC | LIMIT 10", ["first_seen", "source.ip", "destination.ip", "destination.port", "flows"], h=9)
    d.row(9)
    d.panels.append(md("### Evidence read in place (federation, experimental)", h=2, d=d))
    d.row(2)
    table(d, "Not allowed by the device profile: server, volume, nights, JA3", EVIDENCE,
          ["host.name", "tls.client.server_name", "received_gb", "chunks", "nights", "ja3"], h=7)
    d.row(7)
    return d


# --- Act 5: the history nobody ingested (federation, experimental) -----------------------------------------------

OUTSIDE = ("FROM raw_store_audit | WHERE event.action == \"logged-in\" "
           "| EVAL ip = TO_STRING(source.ip), store = TO_STRING(retail.store.id) "
           f'| WHERE NOT CIDR_MATCH(TO_IP(ip), "198.51.100.0/24") AND NOT CIDR_MATCH(TO_IP(ip), "10.0.0.0/8")')


# Two layers, two queries. Kibana adds the picker's time filter to every panel query and would drop the federated rows
# in a query that also reads an index, so the history layer reads the dataset alone (it ignores the picker) and the blip
# layer reads the indexed audit (it follows the picker: "Last 24 hours" during a live run).
HISTORY = """FROM raw_store_audit
| WHERE event.action == "logged-in"
| EVAL ip = TO_STRING(source.ip), store = TO_STRING(retail.store.id)
| WHERE NOT CIDR_MATCH(TO_IP(ip), "198.51.100.0/24") AND NOT CIDR_MATCH(TO_IP(ip), "10.0.0.0/8")
| STATS first_seen = MIN(@timestamp) BY store
| EVAL kind = "Attacker logs in (first time per store)"
| STATS stores = COUNT(*) BY week = BUCKET(first_seen, 1 week), kind
| SORT week"""

BLIP = """FROM logs-coldchain.audit-default
| WHERE event.action == "parameter-change" AND coldchain.parameter.code == "setpoint" AND coldchain.parameter.value.new > 5
| STATS first_seen = MIN(@timestamp) BY retail.store.id
| EVAL kind = "Setpoint changed to +50 (the blip)"
| STATS stores = COUNT(*) BY week = BUCKET(first_seen, 1 week), kind
| SORT week"""


def act5() -> Dash:
    d = Dash("coldchain-act5a-history", "CC Act 3a: The history nobody ingested",
             "A year of raw store audit read in place from S3 by ES|QL data federation (experimental). Synthetic data.",
             time=("now-1y", "now"))
    d.panels.append(md("## Act 3a: four months of silence, then the blip\n**Federation, experimental.** A year of raw store audit, "
                       "read in place from S3 and never ingested, and the live blip from today's indexed audit. The history takes about 75 seconds. "
                       "Each bar is the number of stores per week: the attacker's first login to a store, and the stores whose "
                       "setpoints were then changed to +50. The chart has its own one-year range, so the time picker does not matter here.", h=5, d=d))
    d.row(5)
    title = "Stores the attacker logged into for the first time, and stores whose setpoints changed"
    layers = [{"type": "bar", "data_source": esql(q), "x": {"column": "week"}, "y": [{"column": "stores"}],
               "breakdown_by": {"column": "kind"}} for q in (HISTORY, BLIP)]
    d.add(title, {"type": "xy", "layers": layers, "axis": {"x": {"title": {"visible": False}},
                                                           "y": {"title": {"text": "stores per week", "visible": True}}},
                  "legend": {"visibility": "visible", "placement": "outside", "position": "bottom"},
                  "time_range": {"from": "now-1y", "to": "now"}}, 48, 16, query=HISTORY)
    d.queries.append((title + " (blip layer)", BLIP, {}))
    d.row(16)
    d.panels.append(md("### The query behind the history layer\nOne language, any source: this is the whole question, in ES|QL. Change only the "
                       "`FROM` line and it runs on the frozen copy (Act 3b) or on the live index.\n\n```\n" + HISTORY + "\n```", h=11, d=d))
    d.row(11)
    return d


# --- Act 5b: the same history, ingested and kept on the frozen tier -----------------------------------------------

from .sources import QUESTION  # noqa: E402

QUESTION_TEXT = QUESTION.format(src="<source>").replace(" | ", "\n| ")

OUTSIDE_FROZEN = ('WHERE event.action == "logged-in" AND NOT CIDR_MATCH(source.ip, "198.51.100.0/24") '
                  'AND NOT CIDR_MATCH(source.ip, "10.0.0.0/8")')
HISTORY_FROZEN = f"""FROM cc-history-audit
| {OUTSIDE_FROZEN}
| STATS first_seen = MIN(@timestamp) BY store = retail.store.id
| EVAL kind = "Attacker logs in (first time per store)"
| STATS stores = COUNT(*) BY week = BUCKET(first_seen, 1 week), kind
| SORT week"""


def act5b() -> Dash:
    d = Dash("coldchain-act5b-history-frozen", "CC Act 3b: The history ingested at a predictable price",
             "The same year of store audit as Act 3a, ingested once and kept on the frozen tier. Synthetic data.",
             time=("now-1y", "now"))
    d.panels.append(md("## Act 3b: the same year, ingested, on the frozen tier\n**Your choice.** Act 3a reads the files in place: "
                       "nothing ingested, about 75 seconds a question (federation, experimental). Here the same history is indexed once, "
                       "stored as a searchable snapshot in object storage and served from the frozen tier: about a second the first time, "
                       "a tenth of a second after that. The spend stays controlled because it is fixed by the size of the frozen node and "
                       "the object storage under it, not by how often you ask.", h=5, d=d))
    d.row(5)
    metric(d, "Events in the frozen index", "FROM cc-history-audit | STATS events = COUNT(*)", "events", w=16)
    metric(d, "Days of history", "FROM cc-history-audit | STATS days = DATE_DIFF(\"days\", MIN(@timestamp), MAX(@timestamp))", "days", w=16, x=16)
    metric(d, "Stores with an outside first login",
           f"FROM cc-history-audit | {OUTSIDE_FROZEN} | STATS stores = COUNT_DISTINCT(retail.store.id)", "stores", w=16, x=32)
    d.row(6)
    title = "Stores the attacker logged into for the first time, and stores whose setpoints changed"
    layers = [{"type": "bar", "data_source": esql(q), "x": {"column": "week"}, "y": [{"column": "stores"}],
               "breakdown_by": {"column": "kind"}} for q in (HISTORY_FROZEN, BLIP)]
    d.add(title, {"type": "xy", "layers": layers, "axis": {"x": {"title": {"visible": False}},
                                                           "y": {"title": {"text": "stores per week", "visible": True}}},
                  "legend": {"visibility": "visible", "placement": "outside", "position": "bottom"}}, 48, 14, query=HISTORY_FROZEN)
    d.queries.append((title + " (blip layer)", BLIP, {}))
    d.row(14)
    table(d, "First outside login per store",
          f'FROM cc-history-audit | {OUTSIDE_FROZEN} | STATS first_seen = MIN(@timestamp), logins = COUNT(*) BY store = retail.store.id, '
          "source = source.ip | SORT first_seen | EVAL first_seen = DATE_FORMAT(\"yyyy-MM-dd HH:mm\", first_seen) "
          "| KEEP first_seen, store, source, logins", ["first_seen", "store", "source", "logins"], h=9)
    d.row(9)
    d.panels.append(md("## One question, three places\nThe same ES|QL, word for word, asked of three places: only the `FROM` changes. "
                       "The live index holds 35 days, so it cannot see the attacker's first visits. The frozen tier and the raw files can, "
                       "at very different speed and cost. Measured with `make sources`; repeat runs on the frozen tier come from its cache.\n\n"
                       "```\n" + QUESTION_TEXT + "\n```", h=9, d=d))
    d.row(9)
    q = "FROM cc-esql-moment | SORT order | EVAL seconds = ROUND(seconds, 1) | KEEP place, ask_with, seconds, stores_found, answer"
    d.add("The same question, three places", {"type": "data_table", "time_range": ALL_TIME, "data_source": esql(q), "metrics": [
        {"column": c, "width": w} for c, w in (("place", 150), ("ask_with", 330), ("seconds", 90), ("stores_found", 120), ("answer", 600))]},
        28, 8, query=q)
    q = "FROM cc-esql-moment | SORT order | KEEP place, seconds"
    lines(d, "Seconds to answer", q, "place", ["seconds"], w=20, h=8, x=28, kind="bar", ytitle="seconds")
    d.panels[-1]["config"]["time_range"] = ALL_TIME
    d.row(8)
    for p in d.panels:  # these panels have their own one-year range: the time picker does not matter
        if p["type"] == "vis":
            p["config"]["time_range"] = {"from": "now-1y", "to": "now"}
    return d


def hunt() -> Dash:
    d = Dash("coldchain-hunt-findings", "CC Act 4: Hunting agent - the agent that keeps looking",
             "Findings of the scheduled hunt by the SOC agent (an Elastic Workflow every 30 minutes). Synthetic data.", time=("now-24h", "now"))
    d.panels.append(md("## The hunt: an agent that keeps looking\nNo alert fired for these. Every 30 minutes a workflow asks the SOC agent to sweep the "
                       "estate (live data, a year of raw history read in place, device profiles, exposure) and records what is abnormal, "
                       "with evidence and a proposed action. It proposes, it runs nothing. **AlertZero is not offered on this deployment "
                       "(9.5.6 Cloud Hosted), so this is the same pattern built from Elastic Workflows and Agent Builder (preview).**\n\n"
                       "**A lead worth following:** among the findings, a TV box in store S07 is talking to the system manager. Nothing "
                       "alerted on that. Next, Act 5 looks at what the TV boxes are doing.", h=7, d=d))
    d.row(7)
    tiles = (("critical", "Critical findings", RED), ("high", "High findings", AMBER), ("medium", "Medium findings", "#6092C0"))
    for i, (sev, title, color) in enumerate(tiles):
        metric(d, title, f'FROM cc-hunt-findings | WHERE severity == "{sev}" | STATS findings = COUNT(*)', "findings", w=12, x=12 * i)
        d.panels[-1]["config"]["metrics"][0]["color"] = {"type": "dynamic", "range": "absolute", "steps": [
            {"lt": 1, "color": GREEN}, {"gte": 1, "color": color}]}
    metric(d, "Stores involved", "FROM cc-hunt-findings | STATS stores = COUNT_DISTINCT(stores)", "stores", w=12, x=36)
    d.row(6)
    # Risk is the colour carrier: red from 85 (critical), amber from 60 (high), blue below. Column widths keep the text readable.
    risk = {"type": "dynamic", "range": "absolute", "steps": [
        {"lt": 60, "color": "#6092C0"}, {"gte": 60, "lt": 85, "color": AMBER}, {"gte": 85, "color": RED}]}
    q = ("FROM cc-hunt-findings | SORT risk DESC, @timestamp DESC | EVAL seen = DATE_FORMAT(\"HH:mm\", @timestamp) "
         "| KEEP seen, risk, severity, stores, title, tools, proposed_action")
    cols = [("seen", 70), ("risk", 70), ("severity", 90), ("stores", 220), ("title", 440), ("tools", 230), ("proposed_action", 610)]
    d.add("Findings, most severe first", {"type": "data_table", "data_source": esql(q), "metrics": [
        {"column": c, "width": w, **({"apply_color_to": "background", "color": risk} if c == "risk" else {})} for c, w in cols]},
        48, 12, query=q)
    d.row(12)
    for col, title in (("why_abnormal", "Why it is abnormal"), ("evidence", "The evidence")):
        q = f"FROM cc-hunt-findings | SORT risk DESC, @timestamp DESC | KEEP risk, stores, {col}"
        cols = [("risk", 70), ("stores", 260), (col, 1400)]
        d.add(title, {"type": "data_table", "data_source": esql(q), "metrics": [
            {"column": c, "width": w, **({"apply_color_to": "background", "color": risk} if c == "risk" else {})} for c, w in cols]},
            48, 10, query=q)
        d.row(10)
    from .agent import TOOLS  # the questions the agent can ask: each one is an ES|QL query over the same data

    def tool_md(tools: list[dict]) -> str:
        return "".join(f"**`{t['id']}`**: {t['description']}\n\n```\n{t['query'].strip()}\n```\n\n" for t in tools)
    d.panels.append(md("## What the agent asks: ES|QL, over every source\nThe agent has no private access to the data. Each tool is one ES|QL "
                       "query over the indexed data, the raw history read in place and the knowledge base: the same language an analyst "
                       "would type. The `tools` column above says which of these each finding came from.", h=4, d=d))
    d.row(4)
    half = (len(TOOLS) + 1) // 2
    d.panels.append(md(tool_md(TOOLS[:half]), w=24, h=30, d=d))
    d.panels.append(md(tool_md(TOOLS[half:]), w=24, h=30, d=d, x=24))
    d.row(30)
    return d


# Ids are listed, not read from the builders: `hunt` imports the agent, which imports this module.
DASHBOARDS = {"coldchain-act0-sources": act0, "coldchain-act1a-cabinet": act1a, "coldchain-act1b-estate": act1,
              "coldchain-act5a-history": act5, "coldchain-act5b-history-frozen": act5b, "coldchain-hunt-findings": hunt,
              "coldchain-epilogue-edge": epilogue}


# --- push / check ------------------------------------------------------------------------------------------------

def kibana() -> tuple[str, requests.Session]:
    e = env()
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
