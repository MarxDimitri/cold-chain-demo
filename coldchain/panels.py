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

SEC, OBS, KBC = "#F04E98", "#00BFB3", "#FEC514"  # realm colours: Security, Observability, Knowledge base

LAMP_SVG = """
<svg viewBox="0 0 1000 196" width="100%" role="img" aria-label="A streetlight over three realms">
  <defs>
    <linearGradient id="beam" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#F04E98" stop-opacity=".85"/><stop offset="1" stop-color="#F04E98" stop-opacity=".12"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="330" height="150" rx="8" fill="#00BFB3" fill-opacity=".14"/>
  <rect x="670" y="0" width="330" height="150" rx="8" fill="#FEC514" fill-opacity=".16"/>
  <rect x="330" y="0" width="340" height="150" fill="#F04E98" fill-opacity=".07"/>
  <polygon points="488,42 512,42 664,150 336,150" fill="url(#beam)"/>
  <rect x="496" y="46" width="8" height="104" rx="3" fill="#69707D"/>
  <path d="M496 52 Q496 26 536 24" stroke="#69707D" stroke-width="8" fill="none" stroke-linecap="round"/>
  <rect x="518" y="14" width="44" height="16" rx="6" fill="#343741"/>
  <ellipse cx="540" cy="34" rx="15" ry="5" fill="#FFE9A8"/>
  <g fill="#00BFB3" fill-opacity=".55"><rect x="34" y="86" width="38" height="52" rx="4"/><rect x="82" y="86" width="38" height="52" rx="4"/>
    <rect x="130" y="86" width="38" height="52" rx="4"/><rect x="178" y="86" width="38" height="52" rx="4"/><rect x="226" y="86" width="38" height="52" rx="4"/></g>
  <text x="34" y="68" font-size="13" fill="currentColor" opacity=".8">cabinets, probes, POS terminals</text>
  <g fill="#FEC514" fill-opacity=".7"><rect x="720" y="86" width="130" height="14" rx="5"/><rect x="720" y="108" width="130" height="14" rx="5"/>
    <rect x="720" y="130" width="130" height="14" rx="5"/></g>
  <text x="720" y="68" font-size="13" fill="currentColor" opacity=".8">inventory, limits, profiles, manuals</text>
  <rect x="0" y="150" width="1000" height="4" fill="currentColor" opacity=".35"/>
  <text x="165" y="172" text-anchor="middle" font-size="13" font-weight="700" fill="#00857c">OBSERVABILITY REALM</text>
  <text x="165" y="188" text-anchor="middle" font-size="11" fill="currentColor" opacity=".8">in the dark</text>
  <text x="500" y="172" text-anchor="middle" font-size="13" font-weight="700" fill="#C2327A">SECURITY REALM</text>
  <text x="500" y="188" text-anchor="middle" font-size="11" fill="currentColor" opacity=".8">the crown jewels in the light, the rest in the dark</text>
  <text x="835" y="172" text-anchor="middle" font-size="13" font-weight="700" fill="#946b00">KNOWLEDGE BASE REALM</text>
  <text x="835" y="188" text-anchor="middle" font-size="11" fill="currentColor" opacity=".8">in the dark</text>
</svg>
"""

# Act 0: the streetlight over three realms, and under each realm the sources it holds, lit or in the dark.
# Query: kb-sources (tier, zone, label, what, rows_txt).
CARD = """<div class="card{% if row["zone"].value == "lit" %} lit{% else %} dark{% endif %}" style="border-left-color:REALM_COLOR">
  <span class="zone">{% if row["zone"].value == "lit" %}under the light{% else %}in the dark{% endif %}</span>
  <b>{{ row["label"].value }}</b>
  <div class="num">{{ row["rows_txt"].value }}</div>
  <div class="muted">{{ row["what"].value }}</div>
</div>"""

REALMS = BASE_CSS + """
<style>
.cc-cols{display:grid;grid-template-columns:33fr 34fr 33fr;margin-top:12px}
.cc-col{padding:0 8px}
.cc-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.cc-sub{grid-column:1/-1;font-size:12px;font-weight:700;margin:6px 0 0 0;opacity:.85}
.cc .card{position:relative}
.cc .card.dark{background:#1b1d23;color:#e8eaf0;border-color:#3a3f4b}
.cc .card.dark .muted{color:#c3c8d4;opacity:.85}
.cc .card.dark .zone{color:#c3c8d4;opacity:.8}
.cc .card.lit{background:rgba(240,78,152,.07)}
.cc .zone{position:absolute;top:6px;right:8px;font-size:10px;opacity:.65}
.cc .card b{display:block;padding-right:70px}
</style>
<div class="cc">""" + LAMP_SVG + """
<div class="cc-cols">
<div class="cc-col"><div class="cc-cards">
{% for row in rows %}{% if row["tier"].value == "Observability realm" %}""" + CARD.replace("REALM_COLOR", "#00BFB3") + """{% endif %}{% endfor %}
</div></div>
<div class="cc-col"><div class="cc-cards">
<div class="card lit" style="grid-column:1/-1;border-left-color:#F04E98"><span class="zone">under the light</span><b>Endpoints, firewalls, identity</b>
  <div class="muted">The crown jewels. Your SIEM and EDR already cover them: not part of this demo.</div></div>
{% for row in rows %}{% if row["tier"].value == "Security realm" and row["zone"].value == "lit" %}""" + CARD.replace("REALM_COLOR", "#F04E98") + """{% endif %}{% endfor %}
<div class="cc-sub">In the dark: security data the usual tools do not cover</div>
{% for row in rows %}{% if row["tier"].value == "Security realm" and row["zone"].value == "dark" %}""" + CARD.replace("REALM_COLOR", "#F04E98") + """{% endif %}{% endfor %}
</div></div>
<div class="cc-col"><div class="cc-cards">
{% for row in rows %}{% if row["tier"].value == "Knowledge base realm" %}""" + CARD.replace("REALM_COLOR", "#FEC514") + """{% endif %}{% endfor %}
</div></div>
</div></div>
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

# Act 1: the store from above, with the aggregates of every system rendered where that system sits in the store.
# Query: one union of four kinds of rows (cabinet, audit, flows, asset, assets); see STORE_QUERY in dashboards.py.
STORE_LAYOUT = BASE_CSS + """
<style>
.cc-store-wrap{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap}
.cc-store-svg{flex:1 1 760px;min-width:520px}
.cc-legend{flex:0 0 250px}
.cc-legend .item{display:flex;gap:10px;align-items:flex-start;margin:0 0 12px 0}
.cc-legend .sw{flex:0 0 18px;height:18px;border-radius:3px;margin-top:2px}
</style>
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
<div class="cc"><div class="cc-store-wrap">
<div class="cc-store-svg">
<svg viewBox="0 0 1250 640" width="100%" role="img" aria-label="Store 07 from above">
  <rect x="10" y="40" width="1090" height="590" rx="6" fill="none" stroke="currentColor" stroke-width="3"/>

  {% assign ci = 0 %}
  {% for row in rows %}{% if row["kind"].value == "cabinet" %}
    {% assign col = ci | modulo: 12 %}{% assign line = ci | divided_by: 12 | floor %}
    {% assign x = col | times: 50 | plus: 30 %}{% assign y = line | times: 52 | plus: 84 %}
    {% if row["setpoint"].value > 5 %}{% assign fill = "#BD271E" %}{% assign stroke = "#7a1b15" %}{% assign ink = "#ffffff" %}
    {% elsif ci > 15 %}{% assign fill = "#D7E8F7" %}{% assign stroke = "#6092C0" %}{% assign ink = "#1a1c21" %}
    {% else %}{% assign fill = "#CDEFEA" %}{% assign stroke = "#00BFB3" %}{% assign ink = "#1a1c21" %}{% endif %}
    <rect x="{{ x }}" y="{{ y }}" width="44" height="44" rx="4" fill="{{ fill }}" stroke="{{ stroke }}" stroke-width="{% if row["cab"].value == "S07-C05" %}5{% else %}2{% endif %}">
      <title>{{ row["cab"].value }}: setpoint {{ row["setpoint"].value }} C, {{ row["readings"].value }} readings</title></rect>
    <text x="{{ x | plus: 22 }}" y="{{ y | plus: 27 }}" text-anchor="middle" font-size="13" font-weight="700" fill="{{ ink }}">{{ row["cab"].value | slice: 5, 2 }}</text>
    {% assign ci = ci | plus: 1 %}
  {% endif %}{% endfor %}
  <text x="30" y="204" font-size="12" fill="currentColor">C05 (heavy outline): the one cabinet the contractor sees.</text>
  <text x="30" y="224" font-size="13" font-weight="700" fill="{% if attacked > 0 %}#BD271E{% else %}#00857c{% endif %}">{{ readings }} readings in the window{% if attacked > 0 %}, {{ attacked }} cabinets at +50 C{% endif %}</text>

  <rect x="660" y="56" width="200" height="200" rx="6" fill="none" stroke="currentColor" stroke-width="2"/>
  <text x="760" y="76" text-anchor="middle" font-size="13" font-weight="700" fill="currentColor">Plant room</text>
  <rect x="672" y="86" width="176" height="28" rx="6" fill="#343741"/>
  <text x="760" y="105" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">Compressor rack</text>
  <rect x="672" y="124" width="176" height="124" rx="6" fill="{% if changes > 0 %}#BD271E{% else %}#00A79D{% endif %}"/>
  <text x="760" y="144" text-anchor="middle" font-size="13" font-weight="700" fill="#fff">AK-SM 800A system manager</text>
  <text x="760" y="166" text-anchor="middle" font-size="12" fill="#fff">{{ events }} audit events</text>
  <text x="760" y="184" text-anchor="middle" font-size="12" fill="#fff">{{ changes }} parameter changes</text>
  <text x="760" y="202" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">{{ logins }} outside logins</text>
  <text x="760" y="222" text-anchor="middle" font-size="12" fill="#fff">firmware {{ firmware }} · {{ f_sm }} flows</text>
  <text x="760" y="240" text-anchor="middle" font-size="11" fill="#fff" opacity=".9">default account, {% if internet == true %}internet-facing{% else %}not exposed{% endif %}</text>
  <line x1="600" y1="150" x2="660" y2="150" stroke="#00BFB3" stroke-width="3" stroke-dasharray="8 6"/>

  <rect x="880" y="56" width="200" height="200" rx="6" fill="#CDEFEA" stroke="#00BFB3" stroke-width="2"/>
  <text x="980" y="160" text-anchor="middle" font-size="14" font-weight="700" fill="#1a1c21">Cold room</text>

  {% if internet == true %}
  <path d="M1115 100 a24 24 0 0 1 8 -46 a34 34 0 0 1 64 8 a24 24 0 0 1 10 38 z" fill="#E7664C"/>
  <text x="1170" y="84" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">contractor</text>
  <text x="1170" y="98" text-anchor="middle" font-size="11" fill="#fff">{{ contractor }}</text>
  <path d="M1170 110 L1170 160 L850 160" fill="none" stroke="#BD271E" stroke-width="3" stroke-dasharray="9 7"/>
  <text x="1110" y="180" text-anchor="middle" font-size="11" fill="#BD271E">logins from the internet</text>
  <text x="1110" y="194" text-anchor="middle" font-size="11" fill="#BD271E">reach the manager directly</text>
  {% endif %}

  <text x="30" y="300" font-size="12" font-weight="700" fill="currentColor" opacity=".6">SALES FLOOR</text>
  <rect x="40" y="316" width="70" height="170" fill="rgba(128,128,128,.25)"/><rect x="150" y="316" width="70" height="170" fill="rgba(128,128,128,.25)"/>
  <rect x="260" y="316" width="70" height="170" fill="rgba(128,128,128,.25)"/><rect x="370" y="316" width="70" height="170" fill="rgba(128,128,128,.25)"/>
  <rect x="480" y="316" width="70" height="170" fill="rgba(128,128,128,.25)"/>

  <text x="30" y="520" font-size="12" font-weight="700" fill="currentColor">CHECKOUT LANES</text>
  <rect x="30" y="530" width="78" height="40" rx="5" fill="#8C97A8"/><rect x="118" y="530" width="78" height="40" rx="5" fill="#8C97A8"/>
  <rect x="206" y="530" width="78" height="40" rx="5" fill="#8C97A8"/><rect x="294" y="530" width="78" height="40" rx="5" fill="#8C97A8"/>
  <text x="69" y="555" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">POS 1</text><text x="157" y="555" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">POS 2</text>
  <text x="245" y="555" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">POS 3</text><text x="333" y="555" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">POS 4</text>
  <text x="30" y="592" font-size="12" fill="currentColor">{{ f_lane }} flows · {{ mb_lane }} MB to the store server and the payment gateway</text>
  <text x="400" y="624" font-size="11" fill="currentColor" opacity=".7">entrance</text><rect x="390" y="628" width="90" height="4" fill="currentColor" opacity=".4"/>

  <rect x="660" y="290" width="410" height="300" rx="6" fill="none" stroke="currentColor" stroke-width="2"/>
  <text x="865" y="312" text-anchor="middle" font-size="13" font-weight="700" fill="currentColor">Back office · network cabinet</text>
  <rect x="676" y="326" width="378" height="56" rx="6" fill="#1a1c21"/>
  <text x="865" y="350" text-anchor="middle" font-size="13" font-weight="700" fill="#fff">SD-WAN router / firewall</text>
  <text x="865" y="370" text-anchor="middle" font-size="12" fill="#fff">{{ f_total }} flows · {{ mb_total | round: 1 }} MB seen in the window</text>
  <rect x="676" y="394" width="184" height="64" rx="6" fill="#8C97A8"/>
  <text x="768" y="418" text-anchor="middle" font-size="13" font-weight="700" fill="#fff">Store server</text>
  <text x="768" y="438" text-anchor="middle" font-size="12" fill="#fff">{{ f_srv }} flows · {{ mb_srv }} MB</text>
  <rect x="870" y="394" width="184" height="64" rx="6" fill="#8C97A8"/>
  <text x="962" y="418" text-anchor="middle" font-size="13" font-weight="700" fill="#fff">Back-office POS</text>
  <text x="962" y="438" text-anchor="middle" font-size="12" fill="#fff">{{ f_bo }} flows · {{ mb_bo }} MB</text>
  <text x="865" y="486" text-anchor="middle" font-size="12" fill="currentColor" opacity=".8">run by central IT: {{ devices }} devices in the inventory</text>
  <text x="865" y="508" text-anchor="middle" font-size="12" fill="currentColor" opacity=".8">one flat store network: nothing separates these</text>
  <text x="865" y="526" text-anchor="middle" font-size="12" fill="currentColor" opacity=".8">boxes from the refrigeration controller</text>

  <g fill="#69707D"><rect x="570" y="300" width="26" height="16" rx="3"/><polygon points="596,304 608,298 608,318 596,312"/>
  <rect x="570" y="470" width="26" height="16" rx="3"/><polygon points="596,474 608,468 608,488 596,482"/>
  <rect x="20" y="468" width="0" height="0"/></g>
  <text x="560" y="336" font-size="11" fill="currentColor" opacity=".7">3 cameras</text>
</svg>
</div>
<div class="cc-legend">
  <div class="muted" style="font-weight:700;letter-spacing:.04em;margin-bottom:10px">WHAT WE COLLECT FOR THIS STORE</div>
  <div class="item"><div class="sw" style="background:#00BFB3"></div><div><b>Cabinet telemetry</b><div class="muted">{{ readings }} readings: temperature, setpoint, defrost</div></div></div>
  <div class="item"><div class="sw" style="background:#E7664C"></div><div><b>System manager audit</b><div class="muted">{{ events }} events: logins, commands, firmware</div></div></div>
  <div class="item"><div class="sw" style="background:#1a1c21"></div><div><b>Network flows</b><div class="muted">{{ f_total }} flows summarised per device pair</div></div></div>
  <div class="item"><div class="sw" style="background:#8C97A8"></div><div><b>Asset inventory</b><div class="muted">{{ devices }} devices, owner, contractor, exposure</div></div></div>
</div>
</div></div>
"""
