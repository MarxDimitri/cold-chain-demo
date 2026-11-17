from coldchain import dashboards


def test_every_act_has_a_strip_with_its_neighbours_and_nothing_overlaps():
    assert list(dashboards.DASHBOARDS) == [a[0] for a in dashboards.ACTS]
    ids = [a[0] for a in dashboards.ACTS]
    for i, did in enumerate(ids):
        body = dashboards.DASHBOARDS[did]().body()
        strip = body["panels"][0]["config"]["content"]
        assert body["panels"][0]["grid"]["y"] == 0
        for j in (i - 1, i + 1):
            if 0 <= j < len(ids):
                assert f"/app/dashboards#/view/{ids[j]}" in strip
        if i == 0:
            assert "\u25C0" not in strip
        if i == len(ids) - 1:
            assert "\u25B6" not in strip
        assert min(p["grid"]["y"] for p in body["panels"][1:]) >= dashboards.NAV_HEIGHT
