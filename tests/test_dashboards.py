"""Dashboard and rule definitions are well formed (no cluster needed). `make dashboards-check` runs the queries."""
from coldchain import dashboards, rules


def test_dashboards_are_well_formed():
    ids = set()
    for d in dashboards.build(None, None):
        assert d.id not in ids
        ids.add(d.id)
        assert d.panels and d.queries
        for p in d.panels:
            g = p["grid"]
            assert g["x"] >= 0 and g["y"] >= 0 and g["w"] > 0 and g["h"] > 0 and g["x"] + g["w"] <= 48
            if p["type"] == "vis":
                assert p["config"]["title"]
        body = d.body()
        assert body["title"] and body["time_range"]["from"] and len(d.panels) < 1000


def test_federated_and_hypothetical_panels_are_labelled():
    epi = dashboards.epilogue()
    text = " ".join(p["config"].get("content", "") for p in epi.panels if p["type"] == "markdown")
    assert "Hypothetical" in text and "experimental" in text
    assert "raw_store_tls" in dashboards.EVIDENCE and "TO_STRING(source.ip)" in dashboards.EVIDENCE  # text columns cast before the join


def test_rules_carry_the_store_and_are_esql():
    for rid, r in rules.RULES.items():
        b = rules.body(rid, False)
        assert b["type"] == "esql" and b["language"] == "esql" and b["enabled"] is False
        assert "retail.store.id" in r["query"]
