from coldchain.sources import LABELS, LIT, SOURCES, TIER_ORDER


def test_every_source_has_a_known_tier_and_a_unique_name():
    names = [s[0] for s in SOURCES]
    assert len(names) == len(set(names))
    assert all(tier in TIER_ORDER for _, tier, _, _ in SOURCES)


def test_every_source_has_a_label():
    assert set(LABELS) == {s[0] for s in SOURCES}


def test_only_known_sources_are_lit_and_only_in_the_security_realm():
    realm = {s[0]: s[1] for s in SOURCES}
    assert LIT <= set(realm) and all(realm[s] == "Security realm" for s in LIT)


def test_act_0_counts_every_source_live_and_joins_only_the_editorial_catalog():
    from coldchain.sources import live_query
    q = live_query("TO_STRING({col})")
    for src, _, _, timed in SOURCES:
        assert f"FROM {src} | STATS n = COUNT(*)" in q
        assert (f"MIN(@timestamp)" in q) if timed else True
    assert "LOOKUP JOIN kb-sources ON source" in q and q.count("FROM (") == 1  # subqueries are not nested
    assert "rows" not in q.split("LOOKUP JOIN")[1].split("KEEP")[0].replace("rows_txt", "")  # no stored counts are used
