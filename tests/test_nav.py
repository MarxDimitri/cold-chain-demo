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


def test_act_0_has_four_switches_and_nine_states_that_link_to_each_other():
    ids = dashboards.panels.ACT0_IDS
    assert set(ids.values()) <= set(dashboards.DASHBOARDS) and len(ids) == 9 and len(set(ids.values())) == 9

    def tpl(state):
        return dashboards.DASHBOARDS[ids[state]]().body()["panels"][1]["config"]["template"]

    start = tpl((0, 0, 0, 0))
    labels = ["Switch on Observability realm", "Switch on Security realm", "Switch on Knowledge base realm", "Switch on the light"]
    assert all(lab in start for lab in labels)
    assert [start.index(lab) for lab in labels] == sorted(start.index(lab) for lab in labels)  # the light is the last switch
    for target in ((0, 1, 0, 0), (1, 0, 0, 0), (0, 0, 1, 0), (1, 1, 1, 1)):
        assert f"#/view/{ids[target]}" in start
    lit = tpl((1, 1, 1, 1))
    assert "Switch off the light" in lit and f"#/view/{ids[(1, 1, 1, 0)]}" in lit  # the light off keeps every realm on
    assert "Switch off Knowledge base realm" in lit and f"#/view/{ids[(1, 1, 0, 0)]}" in lit  # a realm off keeps the others on
    for state in ids:
        nav = dashboards.DASHBOARDS[ids[state]]().body()["panels"][0]["config"]["template"]
        assert nav.count('class="step cur"') == 1 and 'class="step cur" title="Act 0' in nav


def test_what_each_state_of_act_0_shows():
    ids = dashboards.panels.ACT0_IDS

    def tpl(state):
        return dashboards.DASHBOARDS[ids[state]]().body()["panels"][1]["config"]["template"]

    realm = lambda state: {n for n in ("SECURITY", "OBSERVABILITY", "KNOWLEDGE BASE") if f"{n} REALM" in tpl(state)}
    assert "Everything is dark" in tpl((0, 0, 0, 0)) and realm((0, 0, 0, 0)) == set()
    assert realm((1, 0, 0, 0)) == {"SECURITY"} and realm((0, 1, 0, 0)) == {"OBSERVABILITY"} and realm((0, 0, 1, 0)) == {"KNOWLEDGE BASE"}
    assert realm((1, 1, 0, 0)) == {"SECURITY", "OBSERVABILITY"} and realm((1, 1, 1, 0)) == {"SECURITY", "OBSERVABILITY", "KNOWLEDGE BASE"}
    assert realm((1, 1, 1, 1)) == {"SECURITY", "OBSERVABILITY", "KNOWLEDGE BASE"}
