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

LAMP_SVG = """
<svg viewBox="0 0 250 300" width="100%" style="max-width:300px" role="img" aria-label="A streetlight">
  <defs>
    <linearGradient id="beam" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#F5A700" stop-opacity=".75"/><stop offset="1" stop-color="#F5A700" stop-opacity=".08"/>
    </linearGradient>
  </defs>
  <polygon points="115,66 135,66 215,270 35,270" fill="url(#beam)"/>
  <ellipse cx="125" cy="272" rx="92" ry="12" fill="#F5A700" fill-opacity=".25"/>
  <rect x="121" y="50" width="8" height="222" rx="3" fill="#69707D"/>
  <path d="M121 56 Q121 22 160 20" stroke="#69707D" stroke-width="8" fill="none" stroke-linecap="round"/>
  <rect x="112" y="46" width="42" height="16" rx="6" fill="#343741"/>
  <ellipse cx="133" cy="66" rx="13" ry="5" fill="#FFE9A8"/>
  <text x="125" y="226" text-anchor="middle" font-size="12" font-weight="700" fill="currentColor">endpoints, firewalls, identity</text>
  <text x="125" y="244" text-anchor="middle" font-size="11" fill="currentColor" opacity=".75">what you usually watch</text>
  <text x="8" y="294" font-size="11" fill="currentColor" opacity=".8">in the dark: the cold chain, the POS, a year of history</text>
</svg>
"""

# Act 0: the streetlight and the realms the demo reads. Query: kb-sources (tier, label, what, rows, days).
REALMS = BASE_CSS + """
<style>
.cc-top{display:flex;gap:28px;align-items:flex-start;flex-wrap:wrap}
.cc-lamp{flex:0 0 290px}
.cc-grid{flex:1;min-width:360px;display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}
</style>
<div class="cc"><div class="cc-top">
<div class="cc-lamp">""" + LAMP_SVG + """</div>
<div class="cc-grid">
{% for row in rows %}
<div class="card" style="border-left-color:{% if row["tier"].value == "Live data" %}#6092C0{% elsif row["tier"].value == "Knowledge base" %}#F5A700{% else %}#D36086{% endif %}">
  <div class="muted">{{ row["tier"].value }}</div>
  <b>{{ row["label"].value }}</b>
  <div class="num">{{ row["rows"].value }}</div>
  <div class="muted">{{ row["what"].value }}</div>
</div>
{% endfor %}
</div></div></div>
"""

# Act 2: one tile per store. Query: per store, the cabinets whose setpoint was raised, and the warm ones now.
STORE_GRID = BASE_CSS + """
<style>
.cc-stores{display:grid;grid-template-columns:repeat(10,1fr);gap:8px}
.cc-store{border-radius:6px;padding:8px 6px;text-align:center;color:#fff;background:#54B399}
.cc-store b{display:block;font-size:16px}
.cc-store span{font-size:11px;opacity:.95}
.cc-bad{background:#BD271E}
.cc-warn{background:#F5A700;color:#1a1c21}
</style>
<div class="cc"><div class="cc-stores">
{% for row in rows %}
<div class="cc-store{% if row["attacked"].value > 0 %} cc-bad{% elsif row["warm"].value > 0 %} cc-warn{% endif %}">
  <b>{{ row["store"].value }}</b>
  <span>{% if row["attacked"].value > 0 %}{{ row["attacked"].value }} cabinets at +50 &deg;C{% else %}all cabinets normal{% endif %}</span>
</div>
{% endfor %}
</div>
<p class="muted">Green: normal. Red: setpoints raised in the window. Amber: warm and not defrosting.</p></div>
"""

# Act 3: when the attacker's address first logged in to each store. Query: store, first_seen, days_ago, logins.
FIRST_VISITS = BASE_CSS + """
<style>
.cc-row{display:flex;align-items:center;gap:10px;margin:6px 0}
.cc-store-id{flex:0 0 46px;font-weight:700}
.cc-track{flex:1;background:rgba(128,128,128,.18);border-radius:4px;height:22px;position:relative}
.cc-bar{height:22px;border-radius:4px;background:#BD271E;min-width:6px}
.cc-days{flex:0 0 190px;font-size:13px}
</style>
<div class="cc">
{% if rows.size == 0 %}<p>No outside logins in the history.</p>{% endif %}
{% for row in rows %}
<div class="cc-row">
  <div class="cc-store-id">{{ row["store"].value }}</div>
  <div class="cc-track"><div class="cc-bar" style="width:{{ row["days_ago"].pct }}%"></div></div>
  <div class="cc-days"><b>{{ row["days_ago"].value }} days ago</b> <span class="muted">{{ row["first_seen_txt"].value }}</span></div>
</div>
{% endfor %}
<p class="muted">The same internet address, first successful login per store. Nothing changed then, so no alert could exist.</p></div>
"""

# Act 4: the findings of the hunting agent as cards. Query: severity, title, stores_txt, why_abnormal, proposed_action, tools_txt.
FINDINGS = BASE_CSS + """
<style>
.cc-find{margin:0 0 10px 0}
.cc-find h4{margin:2px 0 4px 0;font-size:15px}
.cc-find p{margin:2px 0;font-size:13px}
</style>
<div class="cc">
{% if rows.size == 0 %}<p>No findings yet. The hunt runs every 30 minutes.</p>{% endif %}
{% for row in rows %}
<div class="card cc-find" style="border-left-color:{% if row["severity"].value == "critical" %}#BD271E{% elsif row["severity"].value == "high" %}#F5A700{% else %}#6092C0{% endif %}">
  <span class="tag" style="background:{% if row["severity"].value == "critical" %}#BD271E{% elsif row["severity"].value == "high" %}#c98a00{% else %}#6092C0{% endif %}">{{ row["severity"].value }}</span>
  <span class="chip">{{ row["stores_txt"].value }}</span>
  <h4>{{ row["title"].value }}</h4>
  <p>{{ row["why_abnormal"].value }}</p>
  <p><b>Proposed:</b> {{ row["proposed_action"].value }}</p>
</div>
{% endfor %}
</div>
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
