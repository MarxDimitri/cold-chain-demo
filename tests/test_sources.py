from coldchain.sources import SOURCES, TIER_ORDER


def test_every_source_has_a_known_tier_and_a_unique_name():
    names = [s[0] for s in SOURCES]
    assert len(names) == len(set(names))
    assert all(tier in TIER_ORDER for _, tier, _, _ in SOURCES)
