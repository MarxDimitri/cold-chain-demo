from coldchain import dashboards


def test_every_act_has_a_quiet_strip_with_its_neighbours_and_nothing_overlaps():
    ids = [a[0] for a in dashboards.ACTS]
    assert [k for k in dashboards.DASHBOARDS if k in ids] == ids and "coldchain-act0-lit" in dashboards.DASHBOARDS
    for i, did in enumerate(ids):
        body = dashboards.DASHBOARDS[did]().body()
        strip = body["panels"][0]
        assert strip["type"] == "custom_content" and strip["grid"]["y"] == 0 and strip["grid"]["h"] == dashboards.NAV_HEIGHT == 2
        html = strip["config"]["template"]
        assert "<script" not in html.lower()
        for j in (i - 1, i + 1):
            if 0 <= j < len(ids):
                assert f"/app/dashboards#/view/{ids[j]}" in html
        dots = html.count('class="step"') + html.count('class="step cur"')
        assert dots == len(ids) and html.count('class="step cur"') == 1  # one dot per act, the current one marked
        assert ("\u2039" in html) == (i > 0) and ("\u203a" in html) == (i < len(ids) - 1)
        assert min(p["grid"]["y"] for p in body["panels"][1:]) >= dashboards.NAV_HEIGHT


def test_the_light_switch_links_the_two_versions_of_act_0():
    dark = dashboards.DASHBOARDS["coldchain-act0-sources"]().body()["panels"][1]["config"]["template"]
    lit = dashboards.DASHBOARDS["coldchain-act0-lit"]().body()["panels"][1]["config"]["template"]
    assert "#/view/coldchain-act0-lit" in dark and "Switch on the light" in dark
    assert "#/view/coldchain-act0-sources" in lit and "Switch off the light" in lit
    nav = dashboards.DASHBOARDS["coldchain-act0-lit"]().body()["panels"][0]["config"]["template"]
    assert nav.count('class="step cur"') == 1 and "#/view/coldchain-act1a-cabinet" in nav  # the lit page is Act 0 in the strip
