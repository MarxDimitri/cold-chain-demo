"""Generate the knowledge-base seed files in elastic/lookup/*.ndjson.

Lookup indices are created with "index.mode": "lookup" (single shard) by the setup step.
"""
from __future__ import annotations

import json

from . import osquery
from .chain import LOOKUP_DIR, cabinets, devices, load_chain
from .defrost import config as defrost_config

MODEL = "EKC 202C"
DOC_REF = "Danfoss EKC 202 instructions RI8KL45J, p.3"


def limits_rows() -> list[dict]:
    """kb.doc = documented range; kb.factory = factory setting; kb.expected = curated normal for the application.

    Documented ranges and factory settings are from the manual (config/defrost.yaml, p.3). The curated ranges are
    this chain's configuration: the defrost ones come from config/defrost.yaml, the others are seed assumptions.
    """
    rows = []

    def row(code, app, doc, expected, rule=None, factory=None, unit=None, basis="demo assumption"):
        key = f"{MODEL}:{code}:{app}"
        r = {"kb": {"key": key,
                    "doc": {"min": doc[0], "max": doc[1], "ref": DOC_REF},
                    "expected": {"min": expected[0], "max": expected[1], "basis": basis}},
             "device": {"model": {"identifier": MODEL}},
             "coldchain": {"parameter": {"code": code}, "application": app}}
        if factory is not None:
            r["kb"]["factory"] = factory
        if unit:
            r["coldchain"]["parameter"]["unit"] = unit
        if rule:
            r["kb"]["rule"] = {"ref": rule}
        rows.append(r)

    row("setpoint", "frozen", (-50, 50), (-28, -18), "EU quick-frozen food rules: -18 °C or colder", factory=2, unit="°C")
    row("setpoint", "chilled", (-50, 50), (0, 5), factory=2, unit="°C")
    row("A13", "frozen", (-50, 50), (-20, -10), factory=8, unit="°C")
    row("A13", "chilled", (-50, 50), (5, 15), factory=8, unit="°C")
    for app in ("frozen", "chilled"):
        row("A03", app, (0, 240), (0, 60), factory=30, unit="min")
    cfg = defrost_config()
    for code, (lo, hi) in cfg["chain"]["expected"].items():  # defrost parameters apply to the frozen cabinets
        m = cfg["manual"][code]
        row(code, "frozen", (m["min"], m["max"]), (lo, hi), factory=m["factory"], unit=m.get("unit"),
            basis="chain configuration (config/defrost.yaml)")
    return rows


def profile_rows() -> list[dict]:
    """Allowed TLS server names per device role (MUD-style). The back-office POS may NOT reach sync.example-cdn.net."""
    allowed = {
        "pos-lane": ["pay.gateway.example", "ntp.example"],
        "pos-backoffice": ["updates.pos-vendor.example", "ntp.example"],
        "system-manager": ["telemetry.vendor-cloud.example", "ntp.example"],
        "store-server": ["telemetry.vendor-cloud.example", "ntp.example"],
        "camera": ["ntp.example"],
    }
    return [{"retail": {"device": {"role": role}}, "tls": {"client": {"server_name": name}},
             "profile": {"allowed": True}}
            for role, names in allowed.items() for name in names]


def manual_rows() -> list[dict]:
    """Short paraphrased facts from the public EKC 202A/B/C instructions RI8KL45J, with page references.

    Every row was checked against the manual text (p.3 parameter survey, p.4 readings and status codes).
    Never store manual text beyond a short paraphrase.
    """
    base = {"device": {"model": {"identifier": MODEL}}, "doc": {"title": "Danfoss EKC 202 instructions RI8KL45J"}}
    facts = [
        ("Temperature (set point) can be set from -50 °C to 50 °C; the factory setting is 2 °C.", 3, "setpoint"),
        ("A13 is the high alarm limit for the air temperature (factory 8 °C); A14 is the low limit (factory -30 °C).", 3, "A13"),
        ("A03 is the delay before a temperature alarm is raised, 0 to 240 min; the factory setting is 30 min.", 3, "A03"),
        ("A12 holds back the temperature alarm after a defrost, 0 to 240 min; the factory setting is 90 min. "
         "A defrost therefore does not raise a temperature alarm on its own.", 3, "A12"),
        ("d01 selects the defrost method: none, electric (EL) or gas. The factory setting is electric.", 3, "d01"),
        ("d03 is the interval between defrost starts, 0 to 48 hours; the factory setting is 8 hours, "
         "which gives three defrosts a day.", 3, "d03"),
        ("d04 is the maximum defrost duration, 0 to 180 min; the factory setting is 45 min.", 3, "d04"),
        ("d02 is the defrost stop temperature, 0 to 25 °C, factory 6 °C. d10 chooses what ends a defrost: "
         "time (factory), the S5 sensor, or the air sensor.", 3, "d02"),
        ("d06 is the drip-off time and d07 the fan start delay after a defrost, both 0 to 60 min and 0 at the factory.",
         3, "d06"),
        ("d18 limits the refrigeration time between two defrosts, 0 to 48 hours; 0 switches it off (factory).", 3, "d18"),
        ("The controller's clock can start a defrost at up to six set times a day (t01 to t06 for hours, t11 to t16 "
         "for minutes).", 3, "t01"),
        ("The readout u60 shows the state of the defrost relay, so a running defrost is visible to the network.", 4, "u60"),
    ]
    return [{**base, "doc": {**base["doc"], "page": page}, "content": text,
             "coldchain": {"parameter": {"code": code}}, "kb": {"verified": True}}
            for text, page, code in facts]


def regulation_rows() -> list[dict]:
    """Short paraphrased facts from public food-safety rules. `kb.verified` says whether the primary text was read.

    These are context for the demo, not legal advice. Re-check against the current text before quoting.
    """
    eur = "https://eur-lex.europa.eu/eli"
    facts = [
        ("EU", "quick-frozen food", "Directive 89/108/EEC, Art. 1 and 5", f"{eur}/dir/1989/108/oj/eng", True,
         "Quick-frozen food is kept at -18 °C or colder throughout. Brief upward fluctuations of up to 3 K are tolerated "
         "in transport, and good practice tolerates up to 3 K in local distribution and retail display cabinets."),
        ("EU", "quick-frozen food", "Directive 89/108/EEC, Art. 5", f"{eur}/dir/1989/108/oj/eng", True,
         "Member States may allow up to 6 K in retail display cabinets if they tell the Commission. Check the national "
         "rule of the country in question."),
        ("EU", "monitoring", "Regulation (EC) 37/2005, Art. 2", f"{eur}/reg/2005/37/oj/eng", True,
         "Transport, warehousing and storage of quick-frozen food must have recording instruments that measure the air "
         "temperature at regular intervals. Instruments follow EN 12830, EN 13485 and EN 13486. Records are kept "
         "at least one year."),
        ("EU", "monitoring", "Regulation (EC) 37/2005, Art. 3", f"{eur}/reg/2005/37/oj/eng", True,
         "Retail display cabinets and local distribution may use one easily visible thermometer instead of recording. "
         "On open cabinets it reads the return air at the marked maximum load line."),
        ("EU", "cold chain", "Regulation (EC) 852/2004, Annex II ch. IX", f"{eur}/reg/2004/852/oj", False,
         "The cold chain must not be interrupted, but limited periods outside temperature control are allowed when "
         "handling requires it and there is no risk to health. Thawing must limit the growth of pathogens. "
         "Read from a UK copy of the text: confirm on EUR-Lex."),
        ("EU", "cybersecurity", "NIS2 Directive (EU) 2022/2555, Annex II", f"{eur}/dir/2022/2555/oj", False,
         "Annex II covers food businesses in wholesale distribution and in industrial production and processing, "
         "generally as important entities when medium-sized or larger. Retail is not listed, according to Finnish "
         "authority guidance: the distribution centres of the chain may be in scope, the stores are not. "
         "Check the national transposition."),
        ("FR", "quick-frozen food", "Arrêté du 21 décembre 2009 (summaries)", "https://www.legifrance.gouv.fr", False,
         "French guidance gives -18 °C as the ceiling for frozen food in retail. The +3 °C figure in the arrêté is for "
         "pre-prepared culinary dishes, not frozen food: do not quote a frozen-food tolerance without checking Légifrance."),
        ("ISO", "display cabinets", "EN ISO 23953-2", "https://www.iso.org/standard/23953.html", False,
         "Display cabinets are classified by the temperature of test packages during a test that includes defrost "
         "cycles. The exact class limits were not verified here."),
        ("US", "cold holding", "FDA Food Code, as applied in state guidance (non-EU, informational)",
         "https://www.fda.gov/food/retail-food-protection/fda-food-code", False,
         "State guidance commonly says cold food held above 41 °F (5 °C) for more than 4 hours is discarded unless a "
         "written plan applies. Rules vary by jurisdiction."),
    ]
    return [{"kb": {"jurisdiction": j, "topic": topic, "source": {"ref": ref, "url": url}, "verified": ok},
             "content": text} for j, topic, ref, url, ok, text in facts]


def asset_rows(chain) -> tuple[list[dict], list[dict]]:
    """kb-assets (by device.id) and kb-assets-by-ip (by host.ip).

    Cabinets sit behind the system manager, so only SM800 rows carry exposure.internet = true.
    That keeps the act 6 query (06b section 4) counting controllers per store, not cabinets.
    """
    assets, by_ip = [], []
    for store in chain.stores:
        fw = chain.firmware(store)
        common = {"retail": {"store": {"id": store.id}, "owner": {"id": store.owner}},
                  "contractor": {"account": {"id": store.contractor_account}}}
        for cab in cabinets(chain, store):
            assets.append({**common, "device": {"id": cab.id, "manufacturer": "Danfoss",
                                                "model": {"identifier": chain.per_store.cabinet_model}},
                           "coldchain": {"application": cab.application,
                                         "controller": {"firmware": fw},
                                         "exposure": {"internet": False}}})
        for dev in devices(chain, store):
            is_sm = dev.role == "system-manager"
            doc = {**common, "device": {"id": dev.name,
                                        "manufacturer": "Danfoss" if is_sm else "generic"},
                   "retail": {**common["retail"], "device": {"role": dev.role}}}
            if is_sm:
                doc["device"]["model"] = {"identifier": dev.model}
                doc["coldchain"] = {"controller": {"firmware": fw},
                                    "exposure": {"internet": store.internet_facing}}
            assets.append(doc)
            if is_sm:  # the independent temperature logger: own battery and cellular uplink, no store-LAN address
                assets.append({**common, "device": {"id": f"{store.id}-LOGGER", "manufacturer": "generic"},
                               "retail": {**common["retail"], "device": {"role": "temperature-logger"}},
                               "coldchain": {"independent": True, "uplink": "own cellular gateway"}})
            by_ip.append({"host": {"ip": dev.ip, "name": dev.name},
                          "retail": {"store": {"id": store.id}, "owner": {"id": store.owner},
                                     "device": {"role": dev.role}}})
    return assets, by_ip


def _write(name: str, rows: list[dict]) -> None:
    LOOKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = LOOKUP_DIR / f"{name}.ndjson"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    print(f"{path.relative_to(LOOKUP_DIR.parent.parent)}: {len(rows)} rows")


def main() -> None:
    chain = load_chain()
    assets, by_ip = asset_rows(chain)
    _write("kb-controller-limits", limits_rows())
    _write("kb-device-profiles", profile_rows())
    _write("kb-manuals", manual_rows())
    _write("kb-regulations", regulation_rows())
    _write("kb-assets", assets)
    _write("kb-assets-by-ip", by_ip)
    _write("kb-advisories", osquery.advisory_rows())  # BSI warning on OpenJDK "Java4Shell", paraphrased
    _write("kb-erp-deliveries", [])  # the delivery plan is loaded by the replay (times are relative to T0)


if __name__ == "__main__":
    main()
