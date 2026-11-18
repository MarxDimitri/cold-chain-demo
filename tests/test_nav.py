from coldchain import dashboards


def test_every_act_has_a_quiet_strip_with_its_neighbours_and_nothing_overlaps():
    assert list(dashboards.DASHBOARDS) == [a[0] for a in dashboards.ACTS]
    ids = [a[0] for a in dashboards.ACTS]
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
