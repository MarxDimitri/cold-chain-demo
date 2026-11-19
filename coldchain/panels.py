"""HTML, CSS and Liquid templates for the custom panels of the dashboards (Kibana Serverless, `custom_content` panels).

A custom panel runs one ES|QL query and fills a template with its rows: `rows`, `row["column"].value`, `.pct` (0 to 100 of the
column's maximum), `max["column"]`, the `round` filter. No JavaScript and no external resources; inline SVG is fine. The colours
are fixed hex values with a neutral frame, so the panels read on a light and a dark theme.
"""
from __future__ import annotations

BASE_CSS = """
<style>
.cc{font-family:inherit;line-height:1.35}
.cc *{box-sizing:border-box}
.cc .muted{opacity:.7;font-size:12px}
.cc .card{border:1px solid rgba(128,128,128,.35);border-left:6px solid #6092C0;border-radius:6px;padding:8px 12px}
.cc .num{font-size:22px;font-weight:700}
.cc .chip{display:inline-block;border-radius:10px;padding:0 8px;margin:0 4px 2px 0;font-size:12px;background:rgba(128,128,128,.22)}
.cc .tag{display:inline-block;border-radius:4px;padding:1px 8px;font-size:11px;font-weight:700;color:#fff;text-transform:uppercase}
</style>
"""

LIGHT, DARK, STRIPE_DARK = "#FEC514", "#2c2f38", "#69707D"  # yellow is the light, black is the dark

# Act 0: four switches (security realm, observability realm, knowledge base realm, the light). The light implies the other three, so
# there are nine states: eight combinations of the realms with the light off, and one with the light on.
def _act0_id(sec: int, obs: int, kb: int) -> str:
    names = [n for n, on in (("security", sec), ("observability", obs), ("knowledge", kb)) if on]
    return "coldchain-act0-" + ("-".join(names) if names else "sources")


ACT0_IDS = {(s_, o_, k_, 0): _act0_id(s_, o_, k_) for s_ in (0, 1) for o_ in (0, 1) for k_ in (0, 1)}
ACT0_IDS[(1, 1, 1, 1)] = "coldchain-act0-lit"
DARK_PAGE = ACT0_IDS[(0, 0, 0, 0)]
LIT_PAGE = ACT0_IDS[(1, 1, 1, 1)]

_OBS_ICONS = """<g fill="none" stroke="@@SHAPE@@" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" opacity=".9" transform="translate(0,40)">
    <g transform="translate(30,80)"><rect x="2" y="8" width="42" height="40" rx="3"/><line x1="2" y1="22" x2="44" y2="22"/><line x1="2" y1="35" x2="44" y2="35"/><path d="M23 0v6M19 3l4 3 4-3"/></g>
    <g transform="translate(88,80)"><rect x="2" y="4" width="38" height="26" rx="3"/><path d="M21 30v8M10 46h22M14 38h14v8"/><line x1="8" y1="12" x2="34" y2="12"/><line x1="8" y1="19" x2="24" y2="19"/></g>
    <g transform="translate(142,78)"><rect x="6" y="2" width="30" height="52" rx="4"/><line x1="6" y1="22" x2="36" y2="22"/><line x1="12" y1="10" x2="12" y2="16"/><line x1="12" y1="28" x2="12" y2="38"/></g>
    <g transform="translate(196,78)"><rect x="16" y="2" width="10" height="34" rx="5"/><circle cx="21" cy="44" r="9"/><line x1="21" y1="12" x2="21" y2="44"/></g>
    <g transform="translate(244,82)"><rect x="2" y="4" width="46" height="38" rx="3"/><circle cx="12" cy="14" r="2.5"/><circle cx="22" cy="14" r="2.5"/><circle cx="32" cy="14" r="2.5"/><rect x="9" y="24" width="32" height="10" rx="2"/><path d="M10 42v6M20 42v6M30 42v6M40 42v6"/></g>
  </g>
  <text x="34" y="184" font-size="11" fill="@@INK@@" opacity=".85">display case · POS · fridge · probe · OT controller</text>"""
_KB_ICONS = """<g fill="none" stroke="@@SHAPE@@" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" opacity=".9" transform="translate(0,40)">
    <g transform="translate(700,82)"><path d="M3 14l18-9 18 9v22l-18 9-18-9z"/><path d="M3 14l18 9 18-9M21 23v22"/></g>
    <g transform="translate(748,82)"><path d="M4 38a20 20 0 1 1 34 0"/><line x1="21" y1="36" x2="30" y2="18"/><circle cx="21" cy="36" r="2.5"/><line x1="4" y1="44" x2="38" y2="44"/></g>
    <g transform="translate(796,82)"><rect x="2" y="6" width="40" height="34" rx="4"/><circle cx="14" cy="19" r="5"/><path d="M6 33c1-6 11-6 16 0M28 17h10M28 25h10"/></g>
    <g transform="translate(846,82)"><path d="M21 12c-4-4-12-5-18-3v32c6-2 14-1 18 3 4-4 12-5 18-3V9c-6-2-14-1-18 3z"/><line x1="21" y1="12" x2="21" y2="44"/></g>
    <g transform="translate(896,82)"><rect x="2" y="10" width="40" height="28" rx="4"/><line x1="2" y1="28" x2="42" y2="28"/><circle cx="34" cy="33" r="1.8"/><line x1="9" y1="33" x2="20" y2="33"/></g>
    <g transform="translate(944,80)"><ellipse cx="22" cy="10" rx="16" ry="6"/><path d="M6 10v28c0 3 7 6 16 6s16-3 16-6V10M6 24c0 3 7 6 16 6s16-3 16-6"/></g>
  </g>
  <text x="720" y="184" font-size="11" fill="@@INK@@" opacity=".85">inventory · limits · profiles · manuals · drives · ERP</text>"""
_CROWNS = """<g fill="#FFF3C4" stroke="#8A6A00" stroke-width="2" stroke-linejoin="round">
    <g transform="translate(446,122)"><path d="M0 26L3 6l9 9 8-13 8 13 9-9 3 20z"/><line x1="0" y1="26" x2="40" y2="26"/><circle cx="3" cy="5" r="2.2"/><circle cx="20" cy="1.5" r="2.2"/><circle cx="37" cy="5" r="2.2"/></g>
    <g transform="translate(518,122)"><path d="M0 26L3 6l9 9 8-13 8 13 9-9 3 20z"/><line x1="0" y1="26" x2="40" y2="26"/><circle cx="3" cy="5" r="2.2"/><circle cx="20" cy="1.5" r="2.2"/><circle cx="37" cy="5" r="2.2"/></g>
  </g>"""


def _lamp_svg(sec: int, obs: int, kb: int, light: int) -> str:
    """The streetlight. Only the realms that are switched on are drawn; the light switches on everything and lights it yellow."""
    show_sec, show_obs, show_kb = bool(sec or light), bool(obs or light), bool(kb or light)
    zone = (lambda x: f'<rect x="{x}" y="0" width="330" height="190" rx="8" fill="#FEC514" fill-opacity=".13"/>') if light else \
           (lambda x: f'<rect x="{x}" y="0" width="330" height="190" rx="8" fill="#2c2f38"/>')
    sides = (zone(0) if show_obs else "") + (zone(670) if show_kb else "")
    centre = '<rect x="330" y="0" width="340" height="190" fill="#FEC514" fill-opacity=".10"/>' if show_sec else ""
    beam = ('<polygon points="488,82 512,82 1000,190 0,190" fill="url(#beam)"/>' if light else
            '<polygon points="488,82 512,82 664,190 336,190" fill="url(#beam)"/>' if sec else "")
    ink, shape = ("currentColor", "#69707D") if light else ("#c3c8d4", "#8C97A8")
    bulb = "#FFE9A8" if show_sec else "#8B919C"

    def label(cx: float, title: str, sub: str, pill: bool) -> str:
        t, u = ("#1d1e24", "#3b3d46") if pill else ("#f2f4f8", "#c3c8d4")
        box = f'<rect x="{cx - 100}" y="8" width="200" height="40" rx="8" fill="#FEC514"/>' if pill else ""
        return (f'{box}<text x="{cx}" y="26" text-anchor="middle" font-size="13" font-weight="700" fill="{t}">{title}</text>'
                f'<text x="{cx}" y="41" text-anchor="middle" font-size="11" fill="{u}">{sub}</text>')

    labels = ((label(165, "OBSERVABILITY REALM", "in the light" if light else "in the dark", bool(light)) if show_obs else "")
              + (label(835, "KNOWLEDGE BASE REALM", "in the light" if light else "in the dark", bool(light)) if show_kb else "")
              + (label(500, "SECURITY REALM", "everything in the light" if light else "crown jewels in the light", True) if show_sec else ""))
    hint = "" if (show_sec or show_obs or show_kb) else '<text x="500" y="140" text-anchor="middle" font-size="16" fill="currentColor" opacity=".55">Everything is dark. Switch on a realm, or the light.</text>'
    return f"""
<svg viewBox="0 0 1000 196" width="100%" role="img" aria-label="A streetlight over the realms that are switched on">
  <defs>
    <linearGradient id="beam" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FEC514" stop-opacity=".9"/><stop offset="1" stop-color="#FEC514" stop-opacity=".15"/>
    </linearGradient>
  </defs>
  {sides}{centre}{beam}
  <rect x="496" y="86" width="8" height="104" rx="3" fill="#69707D"/>
  {_CROWNS if show_sec else ""}
  <path d="M496 92 Q496 66 536 64" stroke="#69707D" stroke-width="8" fill="none" stroke-linecap="round"/>
  <rect x="518" y="54" width="44" height="16" rx="6" fill="#343741"/>
  <ellipse cx="540" cy="74" rx="15" ry="5" fill="{bulb}"/>
  {_OBS_ICONS.replace("@@SHAPE@@", shape).replace("@@INK@@", ink) if show_obs else ""}
  {_KB_ICONS.replace("@@SHAPE@@", shape).replace("@@INK@@", ink) if show_kb else ""}
  {hint}
{labels}
</svg>
"""


def _toggle(href: str, label: str, on: bool) -> str:
    track, knob_x = ("#FEC514", 32) if on else ("#69707D", 12)
    return (f'<a class="cc-switch" href="/app/dashboards#/view/{href}">'
            f'<svg viewBox="0 0 44 24" width="44" height="24"><rect x="0" y="0" width="44" height="24" rx="12" fill="{track}"/>'
            f'<circle cx="{knob_x}" cy="12" r="9" fill="#fff"/></svg><span>{label}</span></a>')


def _toggles(sec: int, obs: int, kb: int, light: int) -> str:
    """Four switches: the security, observability and knowledge base realms and, last, the light. Each links to the page with that switch
    flipped (custom panels cannot run code). Switching a realm off while the light is on keeps the other realms on."""
    def flip(which: int) -> tuple:
        if light:
            st = [1, 1, 1]
            st[which] = 0
            return (*st, 0)
        st = [sec, obs, kb]
        st[which] = 1 - st[which]
        return (*st, 0)

    t_light = (1, 1, 1, 0) if light else (1, 1, 1, 1)
    on = (bool(sec or light), bool(obs or light), bool(kb or light))
    word = lambda is_on: "off" if is_on else "on"
    return ('<div class="cc-switchbar">'
            + _toggle(ACT0_IDS[flip(0)], f"Switch {word(on[0])} Security realm", on[0])
            + _toggle(ACT0_IDS[flip(1)], f"Switch {word(on[1])} Observability realm", on[1])
            + _toggle(ACT0_IDS[flip(2)], f"Switch {word(on[2])} Knowledge base realm", on[2])
            + _toggle(ACT0_IDS[t_light], f"Switch {word(bool(light))} the light", bool(light)) + '</div>')


_CARD_DARK = """<div class="card{% if row["zone"].value == "lit" %} lit{% else %} dark{% endif %}">
  <span class="zone">{% if row["zone"].value == "lit" %}under the light{% else %}in the dark{% endif %}</span>
  <b>{{ row["label"].value }}</b>
  <div class="num">{{ row["rows_txt"].value }}</div>
  <div class="muted">{{ row["what"].value }}</div>
</div>"""
_CARD_LIT = """<div class="card lit">
  <span class="zone">in the light</span>
  <b>{{ row["label"].value }}</b>
  <div class="num">{{ row["rows_txt"].value }}</div>
  <div class="muted">{{ row["what"].value }}</div>
</div>"""

_TILES = """<div class="card lit"><span class="zone">under the light</span><b>Endpoints</b>
  <div class="muted">EDR telemetry per host: process starts, file and registry changes, logons, network connections. Usually the first source a SIEM ingests.</div></div>
<div class="card lit"><span class="zone">under the light</span><b>Firewalls</b>
  <div class="muted">Border firewall and VPN logs: allowed and denied connections, threat and URL events. Bulk allow logs often go to cheaper storage.</div></div>
<div class="card lit" style="grid-column:1/-1"><span class="zone">under the light</span><b>Identity</b>
  <div class="muted">Sign-ins and directory changes from Active Directory, Entra ID or Okta: MFA, privileged use, service accounts. Often the highest-value single source.</div></div>
"""


def realms(sec: int = 0, obs: int = 0, kb: int = 0, light: int = 0) -> str:
    """Act 0 template for one state of the switches. Query: the live source counts (tier, zone, label, what, rows_txt)."""
    show_sec, show_obs, show_kb = bool(sec or light), bool(obs or light), bool(kb or light)
    card = _CARD_LIT if light else _CARD_DARK
    css = """
<style>
.cc-switchbar{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px;margin:0 8px 8px 0}
.cc-switch{display:inline-flex;align-items:center;gap:8px;padding:4px 12px 4px 6px;border:1px solid rgba(128,128,128,.45);border-radius:18px;
  color:inherit;text-decoration:none;font-size:12px;opacity:.85}
.cc-switch:hover{opacity:1;background:rgba(128,128,128,.15)}
.cc-cols{display:grid;grid-template-columns:33fr 34fr 33fr;margin-top:12px}
.cc-col{padding:0 8px}
.cc-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.cc .card{position:relative}
.cc .card b{display:block;padding-right:70px}
.cc .card.lit{background:rgba(254,197,20,.16);border-left-color:#FEC514}
.cc .card.dark{background:#2c2f38;color:#e8eaf0;border-color:#3d414c;border-left-color:#69707D}
.cc .card.dark .muted{color:#c3c8d4;opacity:.85}
.cc .zone{position:absolute;top:6px;right:8px;font-size:10px;opacity:.7}
.cc .card.dark .zone{color:#c3c8d4}
</style>"""

    def tier(name: str) -> str:
        return '{% for row in rows %}{% if row["tier"].value == "' + name + '" %}' + card + '{% endif %}{% endfor %}'

    obs_col = tier("Observability realm") if show_obs else ""
    sec_col = (_TILES + tier("Security realm")) if show_sec else ""
    kb_col = tier("Knowledge base realm") if show_kb else ""
    return (BASE_CSS + css + '<div class="cc">' + _toggles(sec, obs, kb, light) + _lamp_svg(sec, obs, kb, light) + '\n<div class="cc-cols">\n'
            '<div class="cc-col"><div class="cc-cards">\n' + obs_col + '\n</div></div>\n<div class="cc-col"><div class="cc-cards">\n' + sec_col +
            '\n</div></div>\n<div class="cc-col"><div class="cc-cards">\n' + kb_col + '\n</div></div>\n</div></div>\n')


REALMS = realms(0, 0, 0, 0)
REALMS_LIT = realms(1, 1, 1, 1)

# Act 2: one tile per store. Query: per store, the cabinets whose setpoint was raised, and the warm ones now.
# Act 2: four estate tiles with a coloured stripe, like Act 1. Query rows: ord, label, value, normal, delta, state (green, amber, red).
ESTATE_TILES = BASE_CSS + """
<style>
.cc{container-type:inline-size}
.cc .est{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.cc .et{border:1px solid rgba(128,128,128,.35);border-left:10px solid #54B399;border-radius:8px;padding:clamp(4px,.7cqw,10px) clamp(8px,1.3cqw,16px)}
.cc .et.amber{border-left-color:#F5A700}
.cc .et.red{border-left-color:#BD271E}
.cc .et .lbl{font-size:clamp(10px,1.05cqw,13px);font-weight:700;letter-spacing:.03em;text-transform:uppercase;opacity:.8}
.cc .et .big{font-size:clamp(24px,2.8cqw,40px);font-weight:700;line-height:1.1}
.cc .et.red .big{color:#BD271E}
.cc .et.amber .big{color:#B77A00}
.cc .et .norm{font-size:clamp(10px,1.05cqw,13px);opacity:.85}
.cc .et .state{font-size:clamp(10px,1cqw,12px);font-weight:700;color:#00857c}
.cc .et.red .state{color:#BD271E}
.cc .et.amber .state{color:#B77A00}
</style>
<div class="cc"><div class="est">
{% for row in rows %}
<div class="et {{ row["state"].value }}">
  <div class="lbl">{{ row["label"].value }}</div>
  <div class="big">{{ row["value"].value }}</div>
  <div class="norm">Normal: {{ row["normal"].value }}</div>
  <div class="state">{% if row["delta"].value > 0 %}&#9650; +{{ row["delta"].value }} above normal{% elsif row["delta"].value < 0 %}&#9660; {{ row["delta"].value }} below normal{% else %}= normal{% endif %}</div>
</div>
{% endfor %}
</div></div>
"""


# Act 2: a map of the 20 stores. The base map (borders, regions, the Rhine) is real vector data from Natural Earth, baked into SVG paths
# (coldchain/mapdata.py): custom panels cannot load map tiles. Rows: store, attacked, warm, x, y, town.
def base_map() -> tuple[str, float, float]:
    """The SVG paths of the Upper Rhine base map (borders, regions, the Rhine) and its size."""
    from .mapdata import COUNTRIES, REGIONS, RIVERS, VIEWBOX
    w, h = VIEWBOX
    land = {"France": "#6092C0", "Germany": "#F5A700", "Switzerland": "#9170B8"}
    countries = "".join(f'<path d="{d}" fill="{land[n]}" fill-opacity=".10" stroke="currentColor" stroke-opacity=".55" stroke-width="1.6"/>'
                        for n, d in COUNTRIES.items())
    regions = "".join(f'<path d="{d}" fill="none" stroke="currentColor" stroke-opacity=".28" stroke-width="1" stroke-dasharray="4 3"/>'
                      for d in REGIONS.values())
    rivers = "".join(f'<path d="{d}" fill="none" stroke="#6092C0" stroke-opacity=".8" stroke-width="{4 if n in ("Rhin", "Rhine") else 1.6}" '
                     'stroke-linecap="round" stroke-linejoin="round"/>' for n, d in RIVERS.items())
    return countries + regions + rivers, w, h


def store_map(selected: str | None = None, town: str = "") -> str:
    from .trucks import BAD_CABINETS
    base, w, h = base_map()
    if selected:
        head = (f'<div class="zbar"><b>{selected} {town}</b> <span class="muted">the whole page shows this store</span>'
                '<a href="/app/dashboards#/view/coldchain-act1b-estate">All stores</a></div>')
    else:
        head = '<div class="zbar"><span class="muted">Click a store to filter the page to it.</span></div>'
    return (STORE_MAP_TPL.replace("@@HEAD@@", head).replace("@@SEL@@", selected or "-").replace("@@W@@", str(w / 100)).replace("@@H@@", str(h / 100))
            .replace("@@VB@@", f"0 0 {w} {h}").replace("@@BASE@@", base).replace("@@LEGY@@", str(round(h - 32))).replace("@@LEGBOX@@", str(round(h - 46))).replace("@@BAD@@", str(BAD_CABINETS)))


# Act 3: which stores did an unknown address log in to as admin, and which of them has the warming attack hit? One dot per store:
# red = hit (a setpoint raised by a non-contractor address), amber = visited but not hit yet (might be next), grey = no unknown login in the period.
# Rows: store, status, outside, hit_cabs, lead_days, first_outside_txt, first_hit_txt, from_ip, x, y, town, from_lbl, to_lbl.
HISTORY_MAP = BASE_CSS + """
<style>
.cc .map{max-width:540px;margin:0 auto;position:relative}
.cc .zbar{font-size:13px;margin:0 8px 6px 8px}
.cc .map svg{display:block}
.cc .bub{cursor:default}
.cc .bub:hover circle{stroke-width:4}
</style>
<div class="cc"><div class="zbar"><span class="muted">Where an unknown address logged in as admin, {% for row in rows %}{% if forloop.first %}{{ row["from_lbl"].value }} to {{ row["to_lbl"].value }}{% endif %}{% endfor %}. Red: already hit. Amber: might be next.</span></div><div class="map">
<svg viewBox="@@VB@@" width="100%" role="img" aria-label="Stores visited by an unknown address">
  @@BASE@@
  <text x="14" y="28" font-size="13" font-weight="700" fill="currentColor" opacity=".55" letter-spacing="2">FRANCE</text>
  <text x="490" y="28" font-size="13" font-weight="700" fill="currentColor" opacity=".55" letter-spacing="2" text-anchor="end">GERMANY</text>
  <text x="14" y="590" font-size="13" font-weight="700" fill="#9170B8" letter-spacing="2" stroke="#fff" stroke-width="3" paint-order="stroke" stroke-opacity=".7">SWITZERLAND</text>
  {% for row in rows %}
  <g class="bub">
    {% if row["status"].value == "visited" %}<circle cx="{{ row["x"].value }}" cy="{{ row["y"].value }}" r="19" fill="none" stroke="#F5A700" stroke-width="2.5" stroke-dasharray="4 3"/>{% endif %}
    <circle cx="{{ row["x"].value }}" cy="{{ row["y"].value }}" r="{% if row["status"].value == "clear" %}8{% else %}12{% endif %}" stroke="#fff" stroke-width="2.5"
      fill="{% if row["status"].value == "hit" %}#BD271E{% elsif row["status"].value == "visited" %}#F5A700{% else %}#9AA7B8{% endif %}">
      <title>{{ row["store"].value }} {{ row["town"].value }}: {% if row["status"].value == "hit" %}HIT. {{ row["hit_cabs"].value }} cabinets raised to +50 C. An unknown address logged in as admin {{ row["outside"].value }} time(s) from {{ row["from_ip"].value }}, first in this period on {{ row["first_outside_txt"].value }}{% if row["lead_days"].value > 0 %}, {{ row["lead_days"].value }} days before the first setpoint change on {{ row["first_hit_txt"].value }}{% endif %}.{% elsif row["status"].value == "visited" %}Might be next. An unknown address logged in as admin {{ row["outside"].value }} time(s) from {{ row["from_ip"].value }}, first on {{ row["first_outside_txt"].value }}. No setpoint change yet.{% else %}No admin login from an unknown address in this period ({{ row["logins"].value }} admin logins in total).{% endif %}</title></circle>
    {% if row["status"].value != "clear" %}<text x="{{ row["x"].value }}" y="{{ row["y"].value | plus: 3.5 }}" text-anchor="middle" font-size="10" font-weight="700" fill="#fff" pointer-events="none">{{ row["store"].value | slice: 1, 2 }}</text>{% endif %}
  </g>
  {% endfor %}
  <rect x="8" y="@@LEGBOX@@" width="430" height="28" rx="7" fill="#1d1e24" fill-opacity=".86"/>
  <g font-size="13" fill="#f2f4f8"><circle cx="24" cy="@@LEGY@@" r="7" fill="#BD271E" stroke="#fff" stroke-width="1.5"/><text x="38" y="@@LEGY@@" dy="4.5">hit</text>
    <circle cx="82" cy="@@LEGY@@" r="7" fill="#F5A700" stroke="#fff" stroke-width="1.5"/><text x="96" y="@@LEGY@@" dy="4.5">visited, not hit yet</text>
    <circle cx="250" cy="@@LEGY@@" r="6" fill="#9AA7B8" stroke="#fff" stroke-width="1.5"/><text x="264" y="@@LEGY@@" dy="4.5">no unknown login</text></g>
  <text x="496" y="674" font-size="10" fill="currentColor" opacity=".6" text-anchor="end">Base map: Natural Earth (public domain).</text>
</svg></div></div>
"""


def history_map() -> str:
    base, w, h = base_map()
    return (HISTORY_MAP.replace("@@BASE@@", base).replace("@@VB@@", f"0 0 {w} {h}").replace("@@LEGY@@", str(round(h - 32)))
            .replace("@@LEGBOX@@", str(round(h - 46))))


# Act 3: four cards with a coloured stripe, from one row: visited, hit_stores, next_stores, outside_logins, all_logins, first_txt.
HISTORY_TILES = BASE_CSS + """
<style>
.cc{container-type:inline-size}
.cc .est{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.cc .et{border:1px solid rgba(128,128,128,.35);border-left:10px solid #54B399;border-radius:8px;padding:clamp(4px,.7cqw,10px) clamp(8px,1.3cqw,16px)}
.cc .et.red{border-left-color:#BD271E}
.cc .et.amber{border-left-color:#F5A700}
.cc .et .lbl{font-size:clamp(10px,1.05cqw,13px);font-weight:700;letter-spacing:.03em;text-transform:uppercase;opacity:.8}
.cc .et .big{font-size:clamp(24px,2.8cqw,40px);font-weight:700;line-height:1.1}
.cc .et.red .big{color:#BD271E}
.cc .et.amber .big{color:#B77A00}
.cc .et .norm{font-size:clamp(10px,1.05cqw,13px);opacity:.85}
</style>
{% for row in rows %}
{% assign out = row["outside_logins"].value | default: 0 %}{% assign all = row["all_logins"].value | default: 0 %}
{% assign vis = row["visited"].value | default: 0 %}{% assign hit = row["hit_stores"].value | default: 0 %}{% assign nxt = row["next_stores"].value | default: 0 %}
<div class="cc"><div class="est">
<div class="et{% if out > 0 %} red{% endif %}"><div class="lbl">Admin logins from unknown addresses</div><div class="big">{{ out }}</div>
  <div class="norm">of {{ all }} admin logins in the period. Normal: 0</div></div>
<div class="et{% if vis > 0 %} red{% endif %}"><div class="lbl">Stores an unknown address logged in to</div><div class="big">{{ vis }}</div>
  <div class="norm">{% if vis > 0 %}first on {{ row["first_txt"].value }}. {% endif %}Normal: 0</div></div>
<div class="et{% if hit > 0 %} red{% endif %}"><div class="lbl">Already hit by the warming attack</div><div class="big">{{ hit }}</div>
  <div class="norm">a setpoint raised by a non-contractor address</div></div>
<div class="et{% if nxt > 0 %} amber{% endif %}"><div class="lbl">Visited, not hit yet: might be next</div><div class="big">{{ nxt }}</div>
  <div class="norm">an unknown address logged in, nothing changed</div></div>
</div></div>
{% endfor %}
"""


# Act 4: the agent's view of the estate on the same map. One dot per store, coloured by the worst finding there.
# Rows: store, n (findings), worst (0 critical, 1 high, 2 medium, 3 none), titles, x, y, town.
HUNT_MAP = BASE_CSS + """
<style>
.cc .map{max-width:540px;margin:0 auto;position:relative}
.cc .zbar{font-size:13px;margin:0 8px 6px 8px}
.cc .map svg{display:block}
.cc .bub{cursor:default}
.cc .bub:hover circle{stroke-width:4}
</style>
<div class="cc"><div class="zbar"><span class="muted">The worst finding of the hunting agent per store; the number is how many findings name the store.</span></div><div class="map">
<svg viewBox="@@VB@@" width="100%" role="img" aria-label="Findings of the hunting agent per store">
  @@BASE@@
  <text x="14" y="28" font-size="13" font-weight="700" fill="currentColor" opacity=".55" letter-spacing="2">FRANCE</text>
  <text x="490" y="28" font-size="13" font-weight="700" fill="currentColor" opacity=".55" letter-spacing="2" text-anchor="end">GERMANY</text>
  <text x="14" y="590" font-size="13" font-weight="700" fill="#9170B8" letter-spacing="2" stroke="#fff" stroke-width="3" paint-order="stroke" stroke-opacity=".7">SWITZERLAND</text>
  {% for row in rows %}
  <g class="bub">
    {% if row["worst"].value == 0 %}<circle cx="{{ row["x"].value }}" cy="{{ row["y"].value }}" r="19" fill="none" stroke="#BD271E" stroke-width="2.5" stroke-dasharray="4 3"/>{% endif %}
    <circle cx="{{ row["x"].value }}" cy="{{ row["y"].value }}" r="{% if row["worst"].value == 3 %}8{% else %}12{% endif %}" stroke="#fff" stroke-width="2.5"
      fill="{% if row["worst"].value == 0 %}#BD271E{% elsif row["worst"].value == 1 %}#F5A700{% elsif row["worst"].value == 2 %}#6092C0{% else %}#9AA7B8{% endif %}">
      <title>{{ row["store"].value }} {{ row["town"].value }}: {% if row["n"].value > 0 %}{{ row["n"].value }} finding(s). {{ row["titles"].value }}{% else %}no finding names this store{% endif %}</title></circle>
    {% if row["n"].value > 0 %}<text x="{{ row["x"].value }}" y="{{ row["y"].value | plus: 3.5 }}" text-anchor="middle" font-size="10" font-weight="700" fill="#fff" pointer-events="none">{{ row["n"].value }}</text>{% endif %}
  </g>
  {% endfor %}
  <rect x="8" y="@@LEGBOX@@" width="430" height="28" rx="7" fill="#1d1e24" fill-opacity=".86"/>
  <g font-size="13" fill="#f2f4f8"><circle cx="24" cy="@@LEGY@@" r="7" fill="#BD271E" stroke="#fff" stroke-width="1.5"/><text x="38" y="@@LEGY@@" dy="4.5">critical</text>
    <circle cx="106" cy="@@LEGY@@" r="7" fill="#F5A700" stroke="#fff" stroke-width="1.5"/><text x="120" y="@@LEGY@@" dy="4.5">high</text>
    <circle cx="176" cy="@@LEGY@@" r="7" fill="#6092C0" stroke="#fff" stroke-width="1.5"/><text x="190" y="@@LEGY@@" dy="4.5">medium</text>
    <circle cx="272" cy="@@LEGY@@" r="6" fill="#9AA7B8" stroke="#fff" stroke-width="1.5"/><text x="286" y="@@LEGY@@" dy="4.5">no finding</text></g>
  <text x="496" y="674" font-size="10" fill="currentColor" opacity=".6" text-anchor="end">Base map: Natural Earth (public domain).</text>
</svg></div></div>
"""


def hunt_map() -> str:
    base, w, h = base_map()
    return (HUNT_MAP.replace("@@BASE@@", base).replace("@@VB@@", f"0 0 {w} {h}").replace("@@LEGY@@", str(round(h - 32)))
            .replace("@@LEGBOX@@", str(round(h - 46))))


# Act 4: four cards from one row: crit, high, medium, total, stores, tools, tools_total, last_min.
HUNT_TILES = BASE_CSS + """
<style>
.cc{container-type:inline-size}
.cc .est{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.cc .et{border:1px solid rgba(128,128,128,.35);border-left:10px solid #54B399;border-radius:8px;padding:clamp(4px,.7cqw,10px) clamp(8px,1.3cqw,16px)}
.cc .et.red{border-left-color:#BD271E}
.cc .et.amber{border-left-color:#F5A700}
.cc .et .lbl{font-size:clamp(10px,1.05cqw,13px);font-weight:700;letter-spacing:.03em;text-transform:uppercase;opacity:.8}
.cc .et .big{font-size:clamp(24px,2.8cqw,40px);font-weight:700;line-height:1.1}
.cc .et.red .big{color:#BD271E}
.cc .et.amber .big{color:#B77A00}
.cc .et .norm{font-size:clamp(10px,1.05cqw,13px);opacity:.85}
</style>
{% for row in rows %}
{% assign crit = row["crit"].value | default: 0 %}{% assign high = row["high"].value | default: 0 %}{% assign med = row["medium"].value | default: 0 %}
{% assign serious = crit | plus: high %}
<div class="cc"><div class="est">
<div class="et{% if crit > 0 %} red{% elsif high > 0 %} amber{% endif %}"><div class="lbl">Critical and high findings</div><div class="big">{{ serious }}</div>
  <div class="norm">{{ crit }} critical, {{ high }} high, {{ med }} medium. Normal: 0</div></div>
<div class="et{% if row["stores"].value > 0 %} red{% endif %}"><div class="lbl">Stores named by a finding</div><div class="big">{{ row["stores"].value | default: 0 }}</div>
  <div class="norm">of 20 stores. Normal: 0</div></div>
<div class="et"><div class="lbl">Tools the agent used</div><div class="big">{{ row["tools"].value | default: 0 }}</div>
  <div class="norm">of {{ row["tools_total"].value }}: audit, network, cabinets, trucks, ERP, POS</div></div>
<div class="et{% if row["last_min"].value > 35 %} amber{% endif %}"><div class="lbl">Last hunt</div><div class="big">{{ row["last_min"].value | default: 0 }} min</div>
  <div class="norm">ago. Every 30 minutes; it proposes and runs nothing</div></div>
</div></div>
{% endfor %}
"""


STORE_MAP_TPL = BASE_CSS + """
<style>
.cc .map{max-width:540px;margin:0 auto;position:relative}
.cc .zbar{font-size:13px;margin:0 8px 6px 8px;display:flex;gap:14px;align-items:center}
.cc .zbar a{color:#0B64DD;text-decoration:underline}
.cc a.sd{position:absolute;width:28px;height:28px;margin:-14px 0 0 -14px;border-radius:50%;display:block;cursor:pointer}
.cc a.sd:hover{outline:3px solid #0B64DD}
.cc .map svg{display:block}
.cc .dot{cursor:default}
.cc .dot:hover circle{stroke-width:4}
@keyframes ccpulse{
  0%{r:12;opacity:.55}
  100%{r:30;opacity:0}
}
.cc .pulse{animation:ccpulse 1.8s ease-out infinite}
</style>
<div class="cc">@@HEAD@@<div class="map">
<svg viewBox="@@VB@@" width="100%" role="img" aria-label="The 20 stores on the Upper Rhine">
  @@BASE@@
  <text x="14" y="28" font-size="13" font-weight="700" fill="currentColor" opacity=".55" letter-spacing="2">FRANCE</text>
  <text x="14" y="46" font-size="11" fill="currentColor" opacity=".5">Alsace</text>
  <text x="490" y="28" font-size="13" font-weight="700" fill="currentColor" opacity=".55" letter-spacing="2" text-anchor="end">GERMANY</text>
  <text x="490" y="46" font-size="11" fill="currentColor" opacity=".5" text-anchor="end">Baden</text>
  <text x="14" y="590" font-size="13" font-weight="700" fill="#9170B8" letter-spacing="2" stroke="#fff" stroke-width="3" paint-order="stroke" stroke-opacity=".7">SWITZERLAND</text>
  {% for row in rows %}{% if row["kind"].value == "truck" %}
    {% assign risk = 0 %}{% assign dx = row["tx"].value %}{% assign dy = row["ty"].value %}{% assign dtown = "" %}
    {% for st in rows %}{% if st["kind"].value == "store" and st["store"].value == row["dest"].value %}{% assign risk = st["bad_now"].value %}{% assign dx = st["x"].value %}{% assign dy = st["y"].value %}{% assign dtown = st["town"].value %}{% endif %}{% endfor %}
    {% assign trouble = false %}{% if row["cargo"].value == "frozen" and risk >= @@BAD@@ %}{% assign trouble = true %}{% endif %}
    <line x1="{{ row["tx"].value }}" y1="{{ row["ty"].value }}" x2="{{ dx }}" y2="{{ dy }}" stroke="{% if trouble %}#BD271E{% else %}#6092C0{% endif %}" stroke-width="{% if trouble %}2.5{% else %}1.4{% endif %}" stroke-dasharray="{% if trouble %}6 4{% else %}3 4{% endif %}" opacity="{% if trouble %}.95{% else %}.6{% endif %}"/>
  {% endif %}{% endfor %}
  {% for row in rows %}{% if row["kind"].value == "store" %}
  <g class="dot">
    {% if row["store"].value == "@@SEL@@" %}<circle cx="{{ row["x"].value }}" cy="{{ row["y"].value }}" r="18" fill="none" stroke="currentColor" stroke-width="3"/>{% endif %}
    {% if row["attacked"].value > 0 %}<circle class="pulse" cx="{{ row["x"].value }}" cy="{{ row["y"].value }}" r="12" fill="#BD271E"/>{% endif %}
    <circle cx="{{ row["x"].value }}" cy="{{ row["y"].value }}" r="11" stroke="#fff" stroke-width="2.5"
      fill="{% if row["attacked"].value > 0 %}#BD271E{% elsif row["warm"].value > 0 %}#F5A700{% else %}#54B399{% endif %}">
      <title>{{ row["store"].value }} {{ row["town"].value }}: {% if row["attacked"].value > 0 %}{{ row["attacked"].value }} cabinets at +50 C{% else %}all cabinets normal{% endif %}</title></circle>
    <text x="{{ row["x"].value }}" y="{{ row["y"].value | plus: 3.5 }}" text-anchor="middle" font-size="10" font-weight="700" fill="#fff" pointer-events="none">{{ row["store"].value | slice: 1, 2 }}</text>
  </g>
  {% endif %}{% endfor %}
  {% for row in rows %}{% if row["kind"].value == "truck" %}
    {% assign risk = 0 %}{% assign dtown = "" %}
    {% for st in rows %}{% if st["kind"].value == "store" and st["store"].value == row["dest"].value %}{% assign risk = st["bad_now"].value %}{% assign dtown = st["town"].value %}{% endif %}{% endfor %}
    {% assign trouble = false %}{% if row["cargo"].value == "frozen" and risk >= @@BAD@@ %}{% assign trouble = true %}{% endif %}
  <g class="truck" transform="translate({{ row["tx"].value }},{{ row["ty"].value }})">
    {% if trouble %}<circle class="pulse" r="14" fill="#BD271E"/>{% endif %}
    <rect x="-12" y="-7" width="17" height="12" rx="2" fill="{% if trouble %}#BD271E{% elsif row["cargo"].value == "frozen" %}#2E6DA4{% elsif row["cargo"].value == "chilled" %}#00BFB3{% else %}#8C97A8{% endif %}" stroke="#fff" stroke-width="1.5"/>
    <path d="M5 -4 H10 L13 0 V5 H5 Z" fill="#343741" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/>
    <circle cx="-6" cy="6" r="2.4" fill="#343741" stroke="#fff" stroke-width="1"/><circle cx="8" cy="6" r="2.4" fill="#343741" stroke="#fff" stroke-width="1"/>
    <text x="0" y="-12" text-anchor="middle" font-size="10" font-weight="700" fill="{% if trouble %}#BD271E{% else %}currentColor{% endif %}" stroke="#fff" stroke-width=".4" paint-order="stroke">{{ row["truck"].value | remove: "TRK-" }}</text>
    <title>{{ row["truck"].value }} ({{ row["cargo"].value }}, cargo {{ row["cargo_temp"].value }} C, {{ row["pallets"].value }} pallets, EUR {{ row["value"].value }}), {{ row["status"].value }}. Next stop {{ row["dest"].value }} {{ dtown }}: planned in {{ row["eta"].value }} min (ERP {{ row["delivery"].value }}){% if trouble %}. The frozen cabinets there are not safe to load: {{ risk }} bad.{% endif %}</title>
  </g>
  {% endif %}{% endfor %}
  <rect x="8" y="@@LEGBOX@@" width="372" height="28" rx="7" fill="#1d1e24" fill-opacity=".86"/>
  <g font-size="13" fill="#f2f4f8"><circle cx="24" cy="@@LEGY@@" r="7" fill="#54B399" stroke="#fff" stroke-width="1.5"/><text x="38" y="@@LEGY@@" dy="4.5">normal</text>
    <circle cx="108" cy="@@LEGY@@" r="7" fill="#BD271E" stroke="#fff" stroke-width="1.5"/><text x="122" y="@@LEGY@@" dy="4.5">setpoints raised</text>
    <circle cx="250" cy="@@LEGY@@" r="7" fill="#F5A700" stroke="#fff" stroke-width="1.5"/><text x="264" y="@@LEGY@@" dy="4.5">warm, no defrost</text></g>
  <text x="496" y="674" font-size="10" fill="currentColor" opacity=".6" text-anchor="end">Base map: Natural Earth (public domain). Hover a dot or a truck.</text>
</svg>
  {% for row in rows %}{% if row["kind"].value == "store" %}
  <a class="sd" style="left:{{ row["x"].value | divided_by: @@W@@ }}%;top:{{ row["y"].value | divided_by: @@H@@ }}%" title="Filter to {{ row["store"].value }} {{ row["town"].value }}"
     href="/app/dashboards#/view/coldchain-act1b-{{ row["store"].value | downcase }}"></a>
  {% endif %}{% endfor %}
</div></div>
"""


STORE_MAP = store_map()

# Act 3: when the attacker's address first logged in to each store. Query: store, first_seen, days_ago, logins.
# Act 4: the findings of the hunting agent as cards. Query: severity, title, stores_txt, why_abnormal, proposed_action, tools_txt.
FINDINGS = BASE_CSS + """
<style>
.cc .fh{font-size:13px;margin:0 8px 8px 8px}
.cc .cat{grid-column:1/-1;font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;opacity:.75;margin:10px 4px 0 4px}
.cc .fgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.cc .fnd{border:1px solid rgba(128,128,128,.35);border-left:10px solid #6092C0;border-radius:8px;padding:8px 14px}
.cc .fnd.critical{border-left-color:#BD271E}
.cc .fnd.high{border-left-color:#F5A700}
.cc .fnd h4{margin:3px 0 4px 0;font-size:15px}
.cc .fnd p{margin:2px 0;font-size:13px}
.cc .src{display:inline-block;border-radius:10px;padding:0 8px;margin:2px 4px 0 0;font-size:11px;background:rgba(96,146,192,.2)}
.cc .fnd .tag.critical{background:#BD271E}
.cc .fnd .tag.high{background:#c98a00}
.cc .fnd .tag.medium,.cc .fnd .tag.low{background:#6092C0}
</style>
<div class="cc"><div class="fh"><b>Nobody asked.</b> Every 30 minutes a workflow asks the SOC agent to sweep the estate. It proposes, it runs nothing (Agent Builder and Workflows, preview).</div>
{% if rows.size == 0 %}<p>No findings yet. The hunt runs every 30 minutes.</p>{% endif %}
<div class="fgrid">
{% assign prev = "" %}
{% for row in rows %}
{% if row["cat_label"].value != prev %}<div class="cat">{{ row["cat_label"].value }}</div>{% assign prev = row["cat_label"].value %}{% endif %}
<div class="fnd {{ row["severity"].value }}">
  <span class="tag {{ row["severity"].value }}">{{ row["severity"].value }}</span>
  <span class="chip">{{ row["stores_txt"].value }}</span>
  <h4>{{ row["title"].value }}</h4>
  <p>{{ row["why_abnormal"].value }}</p>
  <p><b>Proposed:</b> {{ row["proposed_action"].value }}</p>
  <div>{% assign srcs = row["tools_txt"].value | split: ", " %}{% for sr in srcs %}<span class="src">{{ sr | remove: "cc_" | replace: "_", " " }}</span>{% endfor %}</div>
</div>
{% endfor %}
</div></div>
"""


# Act 5: the evidence on the back-office POS. Query: server, received_gb, chunks, nights, ja3, first_seen_txt.
POS_EVIDENCE = BASE_CSS + """
<style>
.cc-ev{display:flex;gap:12px;flex-wrap:wrap}
.cc-ev .card{flex:1;min-width:150px;border-left-color:#BD271E}
</style>
<div class="cc">
{% if rows.size == 0 %}<p>No traffic outside the device profile.</p>{% endif %}
{% for row in rows %}
<p><b>{{ row["host"].value }}</b> talked to <b>{{ row["server"].value }}</b>, a server its profile does not allow.</p>
<div class="cc-ev">
  <div class="card"><div class="muted">Received</div><div class="num">{{ row["received_gb"].value }} GB</div></div>
  <div class="card"><div class="muted">Chunks</div><div class="num">{{ row["chunks"].value }}</div></div>
  <div class="card"><div class="muted">Nights</div><div class="num">{{ row["nights"].value }}</div></div>
  <div class="card"><div class="muted">First seen</div><div class="num" style="font-size:16px">{{ row["first_seen_txt"].value }}</div></div>
</div>
<p class="muted">TLS fingerprint (JA3): {{ row["ja3"].value }}, not the one this device uses for its vendor.</p>
{% endfor %}
</div>
"""

# Act 1: the store from above, with the aggregates of every system rendered where that system sits in the store.
# Query: one union of four kinds of rows (cabinet, audit, flows, asset, assets); see STORE_QUERY in dashboards.py.
# Act 1: three state tiles beside the store layout. Query: one row kind "now" (setpoint, air) and one "changes".
_TILES_TPL = BASE_CSS + """
<style>
.cc .tiles{display:flex;flex-direction:column;gap:12px;height:100%}
.cc .tile{flex:1;min-height:150px;border:1px solid rgba(128,128,128,.35);border-left:10px solid #54B399;border-radius:8px;padding:12px 16px;
  display:flex;flex-direction:column;justify-content:center}
.cc .tile.bad{border-left-color:#BD271E}
.cc .back{font-size:13px}.cc .back a{color:#0B64DD;text-decoration:underline}
.cc .tile .lbl{font-size:13px;font-weight:700;letter-spacing:.03em;text-transform:uppercase;opacity:.8}
.cc .tile .big{font-size:46px;font-weight:700;line-height:1.1;margin:4px 0}
.cc .tile.bad .big{color:#BD271E}
.cc .tile .unit{font-size:20px;font-weight:400;opacity:.7}
.cc .tile .norm{font-size:13px;opacity:.85}
.cc .tile .state{font-size:12px;font-weight:700;margin-top:4px;color:#00857c}
.cc .tile.bad .state{color:#BD271E}
</style>
{% assign setpoint = 0 %}{% assign air = 0 %}{% assign changes = 0 %}{% assign have = false %}
{% for row in rows %}
  {% if row["kind"].value == "now" %}{% assign setpoint = row["setpoint"].value %}{% assign air = row["air"].value %}{% assign have = true %}
  {% elsif row["kind"].value == "changes" %}{% assign changes = row["changes"].value %}{% endif %}
{% endfor %}
<div class="cc"><div class="tiles">
@@BACK@@
  <div class="tile{% if setpoint > @@SP@@ %} bad{% endif %}">
    <div class="lbl">Setpoint now · @@CAB@@</div>
    <div class="big">{{ setpoint }}<span class="unit"> °C</span></div>
    <div class="norm">Normal: @@NORMAL@@ (documented maximum: +50 °C)</div>
    <div class="state">{% if setpoint > @@SP@@ %}outside the normal range{% else %}in range{% endif %}</div>
  </div>
  <div class="tile{% if air > @@AIR@@ %} bad{% endif %}">
    <div class="lbl">Air temperature now · @@CAB@@</div>
    <div class="big">{{ air }}<span class="unit"> °C</span></div>
    <div class="norm">Normal: within about 1 K of the setpoint; up to +14 K during a 40 minute defrost</div>
    <div class="state">{% if air > @@AIR@@ %}too warm for @@KIND@@ food{% else %}in range{% endif %}</div>
  </div>
  <div class="tile{% if changes > 0 %} bad{% endif %}">
    <div class="lbl">Parameter changes · @@CAB@@</div>
    <div class="big">{{ changes }}</div>
    <div class="norm">Normal: none on most days; a contractor change stays within the normal range</div>
    <div class="state">{% if changes > 0 %}changed in this window{% else %}no changes{% endif %}</div>
  </div>
</div></div>
"""


def cabinet_tiles(cab: str = "S07-C05") -> str:
    """The three state tiles for one cabinet. Cabinets 17 to 24 are chilled (0 to +5 °C), the rest frozen (-28 to -18 °C)."""
    chilled = int(cab[-2:]) > 16
    return (_TILES_TPL.replace("@@CAB@@", "C" + cab[-2:]).replace("@@SP@@", "5" if chilled else "-18")
            .replace("@@AIR@@", "8" if chilled else "-18").replace("@@KIND@@", "chilled" if chilled else "frozen")
            .replace("@@BACK@@", "" if cab == "S07-C05" else '<div class="back"><a href="/app/dashboards#/view/coldchain-act1a-cabinet">\u2039 Back to C05, the contractor\'s cabinet</a></div>')
            .replace("@@NORMAL@@", "0 to +5 °C for a chilled cabinet" if chilled else "-28 to -18 °C for a frozen cabinet"))


CABINET_TILES = cabinet_tiles()


def _person(x: int, y: int, color: str, basket: bool = False) -> str:
    """A small shopper seen from the front (head, body, legs), top-left of its 26 px tall box at (x, y)."""
    b = (f'<rect x="{x + 8}" y="{y + 15}" width="9" height="7" rx="1.5" fill="none" stroke="{color}" stroke-width="1.6"/>' if basket else "")
    return (f'<g><circle cx="{x}" cy="{y + 4}" r="4.6" fill="#E9C9A5"/>'
            f'<rect x="{x - 6}" y="{y + 9}" width="12" height="11" rx="5" fill="{color}"/>'
            f'<path d="M{x - 2.5} {y + 20}v6M{x + 2.5} {y + 20}v6" stroke="#4A4F5C" stroke-width="2.4" stroke-linecap="round"/>{b}</g>')


def _shoppers() -> str:
    """People on the sales floor: in the aisles, at the shelves and queueing at the checkout."""
    col = ["#E7664C", "#6092C0", "#54B399", "#9170B8", "#F5A700", "#D36086"]
    spots = [(190, 374, 0, 1), (318, 374, 1, 0), (452, 374, 2, 1), (590, 374, 3, 0),
             (250, 190, 4, 0), (520, 190, 5, 1),
             (452, 424, 0, 0), (486, 424, 1, 1), (520, 424, 2, 0), (554, 424, 3, 0)]
    return "<g>" + "".join(_person(x, y, col[c], bool(b)) for x, y, c, b in spots) + "</g>"


_LAYOUT_TPL = BASE_CSS + """
{% assign changes = 0 %}{% assign logins = 0 %}{% assign events = 0 %}{% assign readings = 0 %}{% assign attacked = 0 %}
{% assign f_sm = 0 %}{% assign f_srv = 0 %}{% assign f_lane = 0 %}{% assign f_bo = 0 %}{% assign f_total = 0 %}
{% assign mb_srv = 0 %}{% assign mb_lane = 0 %}{% assign mb_bo = 0 %}{% assign mb_total = 0 %}
{% assign internet = false %}{% assign firmware = "" %}{% assign contractor = "" %}{% assign devices = 0 %}
{% for row in rows %}
  {% if row["kind"].value == "audit" %}
    {% assign changes = row["changes"].value %}{% assign logins = row["logins"].value %}{% assign events = row["events"].value %}
  {% elsif row["kind"].value == "flows" %}
    {% assign f_total = f_total | plus: row["flows"].value %}{% assign mb_total = mb_total | plus: row["mb"].value %}
    {% if row["role"].value == "system-manager" %}{% assign f_sm = row["flows"].value %}{% endif %}
    {% if row["role"].value == "store-server" %}{% assign f_srv = row["flows"].value %}{% assign mb_srv = row["mb"].value %}{% endif %}
    {% if row["role"].value == "pos-lane" %}{% assign f_lane = row["flows"].value %}{% assign mb_lane = row["mb"].value %}{% endif %}
    {% if row["role"].value == "pos-backoffice" %}{% assign f_bo = row["flows"].value %}{% assign mb_bo = row["mb"].value %}{% endif %}
  {% elsif row["kind"].value == "asset" %}
    {% assign internet = row["internet"].value %}{% assign firmware = row["firmware"].value %}{% assign contractor = row["contractor"].value %}
  {% elsif row["kind"].value == "assets" %}
    {% assign devices = row["devices"].value %}
  {% elsif row["kind"].value == "cabinet" %}
    {% assign readings = readings | plus: row["readings"].value %}
    {% if row["setpoint"].value > 5 %}{% assign attacked = attacked | plus: 1 %}{% endif %}
  {% endif %}
{% endfor %}
<style>.cc a.cab{position:absolute;display:block;width:4.5%;height:6.79%;border-radius:6px;cursor:pointer}.cc a.cab:hover{outline:3px solid #0B64DD}</style>
<div class="cc" style="max-width:1280px;margin:0 auto;position:relative">
<svg style="display:block" viewBox="0 0 1200 560" width="100%" role="img" aria-label="Store 07 from above" font-family="inherit">
  <rect x="5" y="5" width="1190" height="550" rx="14" fill="none" stroke="currentColor" stroke-width="2.5" opacity=".8"/>

  {% assign ci = 0 %}
  {% for row in rows %}{% if row["kind"].value == "cabinet" %}
    {% assign col = ci | modulo: 12 %}{% assign line = ci | divided_by: 12 | floor %}
    {% assign x = col | times: 60 | plus: 24 %}{% assign y = line | times: 44 | plus: 22 %}
    {% if row["setpoint"].value > 5 %}{% assign fill = "#9C3B26" %}{% assign stroke = "#6e2414" %}{% assign ink = "#ffffff" %}
    {% elsif ci > 15 %}{% assign fill = "#E4EAF7" %}{% assign stroke = "#9FB3D8" %}{% assign ink = "#1a1c21" %}
    {% else %}{% assign fill = "#CDEFEA" %}{% assign stroke = "#00BFB3" %}{% assign ink = "#1a1c21" %}{% endif %}
    <rect x="{{ x }}" y="{{ y }}" width="54" height="38" rx="6" fill="{{ fill }}" stroke="{% if row["cab"].value == "@@SEL@@" %}#1a1c21{% else %}{{ stroke }}{% endif %}" stroke-width="{% if row["cab"].value == "@@SEL@@" %}4{% else %}1.5{% endif %}">
      <title>{{ row["cab"].value }}: setpoint {{ row["setpoint"].value }} C, {{ row["readings"].value }} readings</title></rect>
    <text x="{{ x | plus: 27 }}" y="{{ y | plus: 25 }}" text-anchor="middle" font-size="13" font-weight="700" fill="{{ ink }}">{{ row["cab"].value | slice: 5, 2 }}</text>
    {% assign ci = ci | plus: 1 %}
  {% endif %}{% endfor %}
  <line x1="738" y1="95" x2="782" y2="95" stroke="#00BFB3" stroke-width="3" stroke-dasharray="7 5"/>
  @@CAPTION@@
  <text x="24" y="148" font-size="13" font-weight="700" fill="{% if attacked > 0 %}#BD271E{% else %}#00857c{% endif %}">{% if attacked > 0 %}{{ attacked }} cabinets at +50 °C{% else %}{{ readings }} readings in the window, all cabinets in band{% endif %}</text>
  {% if attacked > 0 %}
  <text x="440" y="148" font-size="11" font-weight="700" letter-spacing="1.5" fill="#BD271E">AT RISK</text>
  <g font-size="26"><text x="510" y="152">🍦</text><text x="556" y="152">🐟</text><text x="602" y="152">🥦</text><text x="648" y="152">❄️</text></g>
  {% endif %}

  <rect x="770" y="18" width="200" height="198" rx="8" fill="none" stroke="currentColor" stroke-width="2" opacity=".8"/>
  <text x="870" y="40" text-anchor="middle" font-size="13" font-weight="700" fill="currentColor">Plant room</text>
  <rect x="782" y="48" width="176" height="26" rx="6" fill="#2a2d35"/>
  <text x="870" y="66" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">Compressor rack</text>
  <rect x="782" y="84" width="176" height="120" rx="6" fill="{% if changes > 0 %}#9C3B26{% else %}#00A79D{% endif %}"/>
  <text x="870" y="106" text-anchor="middle" font-size="13" font-weight="700" fill="#fff">AK-SM 800A</text>
  <text x="870" y="126" text-anchor="middle" font-size="12" fill="#fff">{{ events }} audit events</text>
  <text x="870" y="143" text-anchor="middle" font-size="12" fill="#fff">{{ changes }} parameter changes</text>
  <text x="870" y="160" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">{{ logins }} outside login{% if logins != 1 %}s{% endif %}</text>
  <text x="870" y="177" text-anchor="middle" font-size="12" fill="#fff">default account</text>
  <text x="870" y="195" text-anchor="middle" font-size="10" fill="#fff" opacity=".85">firmware {{ firmware }} · {{ f_sm }} flows</text>

  <rect x="985" y="18" width="200" height="198" rx="8" fill="#DCF1EE" stroke="#7BC4BB" stroke-width="2"/>
  <text x="1085" y="122" text-anchor="middle" font-size="14" font-weight="700" fill="#1a1c21">Cold room</text>

  <text x="24" y="206" font-size="12" font-weight="700" letter-spacing="1" fill="currentColor" opacity=".6">SALES FLOOR</text>
  <g fill="rgba(128,128,128,.10)" stroke="rgba(128,128,128,.55)" stroke-width="1.5">
    <rect x="24" y="218" width="118" height="152" rx="8"/><rect x="152" y="218" width="118" height="152" rx="8"/>
    <rect x="280" y="218" width="118" height="152" rx="8"/><rect x="408" y="218" width="118" height="152" rx="8"/>
    <rect x="536" y="218" width="118" height="152" rx="8"/>
  </g>
  <g font-size="12" font-weight="700" text-anchor="middle" fill="currentColor" opacity=".85">
    <text x="83" y="240">Fruit</text><text x="211" y="240">Vegetables</text><text x="339" y="240">Bakery</text><text x="467" y="240">Dairy</text><text x="595" y="240">Drinks</text>
  </g>
  <g font-size="27" text-anchor="middle">
    <text x="55" y="285">🍌</text><text x="110" y="285">🍍</text><text x="83" y="335">🍎</text>
    <text x="183" y="285">🍅</text><text x="238" y="285">🥕</text><text x="211" y="335">🥬</text>
    <text x="311" y="285">🥖</text><text x="366" y="285">🥐</text><text x="339" y="335">🧁</text>
    <text x="439" y="285">🥛</text><text x="494" y="285">🧀</text><text x="467" y="335">🥚</text>
    <text x="567" y="285">🍷</text><text x="622" y="285">🥫</text><text x="595" y="335">💧</text>
  </g>

  @@PEOPLE@@
  <g fill="#69707D"><rect x="672" y="248" width="26" height="16" rx="3"/><polygon points="698,252 710,246 710,266 698,260"/>
  <rect x="672" y="332" width="26" height="16" rx="3"/><polygon points="698,336 710,330 710,350 698,344"/></g>
  <text x="682" y="286" font-size="11" fill="currentColor" opacity=".75">3 cameras</text>

  <text x="24" y="402" font-size="12" font-weight="700" letter-spacing="1" fill="currentColor" opacity=".6">CHECKOUT LANES</text>
  <g fill="#8F96A8"><rect x="24" y="414" width="90" height="40" rx="6"/><rect x="124" y="414" width="90" height="40" rx="6"/>
  <rect x="224" y="414" width="90" height="40" rx="6"/><rect x="324" y="414" width="90" height="40" rx="6"/></g>
  <g font-size="12" font-weight="700" fill="#fff" text-anchor="middle"><text x="69" y="439">POS 1</text><text x="169" y="439">POS 2</text><text x="269" y="439">POS 3</text><text x="369" y="439">POS 4</text></g>
  <text x="24" y="482" font-size="12" fill="currentColor" opacity=".85">{{ f_lane }} flows · {{ mb_lane }} MB to the store server and the payment gateway</text>
  <text x="330" y="534" text-anchor="middle" font-size="11" fill="currentColor" opacity=".7">entrance</text><rect x="270" y="542" width="120" height="5" rx="2" fill="currentColor" opacity=".4"/>

  <rect x="770" y="232" width="415" height="290" rx="8" fill="none" stroke="currentColor" stroke-width="2" opacity=".8"/>
  <text x="977" y="258" text-anchor="middle" font-size="13" font-weight="700" fill="currentColor">Back office · network cabinet</text>
  <rect x="786" y="272" width="383" height="54" rx="6" fill="#1a1c21"/>
  <text x="977" y="295" text-anchor="middle" font-size="13" font-weight="700" fill="#fff">SD-WAN router / firewall</text>
  <text x="977" y="314" text-anchor="middle" font-size="12" fill="#fff">{{ f_total }} flows · {{ mb_total | round: 1 }} MB seen in the window</text>
  <rect x="786" y="338" width="185" height="58" rx="6" fill="#8F96A8"/>
  <text x="878" y="361" text-anchor="middle" font-size="13" font-weight="700" fill="#fff">Store server</text>
  <text x="878" y="381" text-anchor="middle" font-size="12" fill="#fff">{{ f_srv }} flows · {{ mb_srv }} MB</text>
  <rect x="984" y="338" width="185" height="58" rx="6" fill="#8F96A8"/>
  <text x="1076" y="361" text-anchor="middle" font-size="13" font-weight="700" fill="#fff">Back-office POS</text>
  <text x="1076" y="381" text-anchor="middle" font-size="12" fill="#fff">{{ f_bo }} flows · {{ mb_bo }} MB</text>
  <g font-size="12" text-anchor="middle" fill="currentColor" opacity=".85">
    <text x="977" y="428">run by central IT: {{ devices }} devices in the inventory</text>
    <text x="977" y="450">one flat store network: nothing separates these boxes from the</text>
    <text x="977" y="468">refrigeration controller</text>
  </g>
</svg>
  {% assign ci = 0 %}
  {% for row in rows %}{% if row["kind"].value == "cabinet" %}
    {% assign col = ci | modulo: 12 %}{% assign line = ci | divided_by: 12 | floor %}
    {% assign left = col | times: 60 | plus: 24 | divided_by: 12.0 %}{% assign top = line | times: 44 | plus: 22 | times: 100 | divided_by: 560.0 %}
    <a class="cab" style="left:{{ left }}%;top:{{ top }}%" title="Open {{ row["cab"].value }}" href="/app/dashboards#/view/{% if row["cab"].value == "S07-C05" %}coldchain-act1a-cabinet{% else %}coldchain-act1a-{{ row["cab"].value | downcase }}{% endif %}"></a>
    {% assign ci = ci | plus: 1 %}
  {% endif %}{% endfor %}
</div>
"""


def store_layout(cab: str = "S07-C05") -> str:
    """The store from above with CAB outlined; every cabinet number links to that cabinet's own Act 1 dashboard."""
    n = "C" + cab[-2:]
    if cab == "S07-C05":
        cap = (f'<text x="24" y="128" font-size="12" fill="currentColor" opacity=".85">{n} (heavy outline): the one cabinet the contractor sees. '
               'Click a cabinet number to look at it.</text>')
    else:
        cap = (f'<text x="24" y="128" font-size="12" fill="currentColor" opacity=".85">{n} (heavy outline) selected.</text>')
    return _LAYOUT_TPL.replace("@@PEOPLE@@", _shoppers()).replace("@@SEL@@", cab).replace("@@CAPTION@@", cap)


STORE_LAYOUT = store_layout()
