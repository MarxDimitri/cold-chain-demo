"""The custom panel templates are well formed Liquid and HTML (no engine needed: tags and elements must balance)."""
import re

import pytest

from coldchain import panels

TEMPLATES = {name: getattr(panels, name) for name in ("REALMS", "REALMS_LIT", "STORE_MAP", "FIRST_VISITS", "FINDINGS", "POS_EVIDENCE")}


@pytest.mark.parametrize("name", TEMPLATES)
def test_liquid_blocks_balance(name):
    t = TEMPLATES[name]
    for opener, closer in (("for", "endfor"), ("if", "endif")):
        opened = re.findall(r"\{%-?\s*" + opener + r"\b", t)
        closed = re.findall(r"\{%-?\s*" + closer + r"\b", t)
        assert len(opened) == len(closed), (name, opener)
    assert t.count("{{") == t.count("}}") and t.count("{%") == t.count("%}")


@pytest.mark.parametrize("name", TEMPLATES)
def test_html_elements_balance_and_nothing_executes(name):
    t = TEMPLATES[name]
    assert "<script" not in t.lower() and "onclick" not in t.lower()  # no JavaScript in custom panels
    for tag in ("div", "style", "svg", "h4", "p"):
        assert len(re.findall(r"<%s[\s>]" % tag, t)) == len(re.findall(r"</%s>" % tag, t)), (name, tag)


def test_templates_read_only_columns_the_queries_return():
    from coldchain import dashboards
    for d in dashboards.build(None, None):
        for p in d.panels:
            if p["type"] != "custom_content":
                continue
            used = set(re.findall(r'row\["([a-z_]+)"\]', p["config"]["template"]))
            q = p["config"]["esql_query"][0]
            for col in used:
                assert re.search(r"\b%s\b" % col, q), (p["config"]["title"], col)
