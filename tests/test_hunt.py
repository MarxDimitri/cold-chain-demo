import yaml

from coldchain.hunt import EVERY, INDEX, NAME, SCHEMA, workflow_yaml


def test_workflow_yaml_parses_and_wires_the_agent_to_the_index():
    w = yaml.safe_load(workflow_yaml())
    assert w["name"] == NAME
    assert [t["type"] for t in w["triggers"]] == ["manual", "scheduled"] and w["triggers"][1]["with"]["every"] == EVERY
    hunt, record = w["steps"]
    assert hunt["type"] == "ai.agent" and hunt["agent-id"] == "cc-soc-hunter" and hunt["with"]["schema"] == SCHEMA
    write = record["steps"][0]
    assert write["with"]["index"] == INDEX and write["with"]["id"] == "{{ foreach.item.key }}"
    assert "steps.hunt.output.structured_output.findings" in record["foreach"]
