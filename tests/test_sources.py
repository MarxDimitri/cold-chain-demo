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
