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


def test_act_0_has_three_switches_and_five_states_that_link_to_each_other():
    ids = dashboards.panels.ACT0_IDS
    assert set(ids.values()) <= set(dashboards.DASHBOARDS) and len(ids) == 5

    def tpl(state):
        return dashboards.DASHBOARDS[ids[state]]().body()["panels"][1]["config"]["template"]

    start = tpl((0, 0, 0))
    assert "Switch on Observability realm" in start and "Switch on Security realm" in start and "Switch on the light" in start
    assert start.index("Observability realm") < start.index("Security realm") < start.index("the light")  # the light is the last switch
    assert f"#/view/{ids[(0, 1, 0)]}" in start and f"#/view/{ids[(1, 0, 0)]}" in start and f"#/view/{ids[(1, 1, 1)]}" in start
    lit = tpl((1, 1, 1))
    assert "Switch off the light" in lit and f"#/view/{ids[(1, 1, 0)]}" in lit  # the light off keeps both realms on
    assert "Switch off Observability realm" in lit and f"#/view/{ids[(1, 0, 0)]}" in lit
    assert f"#/view/{ids[(0, 1, 0)]}" in lit  # the security realm off keeps the observability realm on
    for state in ids:
        nav = dashboards.DASHBOARDS[ids[state]]().body()["panels"][0]["config"]["template"]
        assert nav.count('class="step cur"') == 1 and 'class="step cur" title="Act 0' in nav


def test_what_each_state_of_act_0_shows():
    ids = dashboards.panels.ACT0_IDS

    def tpl(state):
        return dashboards.DASHBOARDS[ids[state]]().body()["panels"][1]["config"]["template"]

    assert "Everything is dark" in tpl((0, 0, 0)) and "SECURITY REALM" not in tpl((0, 0, 0)) and "OBSERVABILITY REALM" not in tpl((0, 0, 0))
    assert "SECURITY REALM" in tpl((1, 0, 0)) and "OBSERVABILITY REALM" not in tpl((1, 0, 0)) and "KNOWLEDGE BASE REALM" not in tpl((1, 0, 0))
    assert "OBSERVABILITY REALM" in tpl((0, 1, 0)) and "SECURITY REALM" not in tpl((0, 1, 0))
    assert "KNOWLEDGE BASE REALM" not in tpl((1, 1, 0))  # the knowledge base only appears with the light
    assert "KNOWLEDGE BASE REALM" in tpl((1, 1, 1)) and "OBSERVABILITY REALM" in tpl((1, 1, 1))
