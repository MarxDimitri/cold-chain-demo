from coldchain.sources import PLACES, QUESTION, SOURCES, TIER_ORDER


def test_every_source_has_a_known_tier_and_a_unique_name():
    names = [s[0] for s in SOURCES]
    assert len(names) == len(set(names))
    assert all(tier in TIER_ORDER for _, tier, _, _ in SOURCES)


def test_the_question_is_identical_for_every_place_except_the_from():
    texts = {QUESTION.format(src=src).replace(src, "<source>") for _, _, src in PLACES}
    assert len(texts) == 1
    assert "TO_IP(source.ip)" in QUESTION  # federated IPs are text, indexed ones are ip: the cast makes one text work for both
