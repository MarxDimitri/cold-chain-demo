"""The agent's tools are well formed and the agent only uses tools that exist."""
import re

from coldchain import agent


def test_tools_declare_every_parameter_they_use():
    ids = [t["id"] for t in agent.TOOLS]
    assert len(ids) == len(set(ids))
    for t in agent.TOOLS:
        used = set(re.findall(r"\?([a-z_]+)", t["query"]))
        assert used == set(t["params"]), t["id"]
        assert t["query"].lstrip().startswith("FROM") and t["description"]


def test_agent_uses_existing_tools_and_labels_federation():
    body = agent.agent_body()
    assert set(body["configuration"]["tools"][0]["tool_ids"]) == {t["id"] for t in agent.TOOLS}
    for t in agent.TOOLS:
        if "raw_" in t["query"]:
            assert "FEDERATION (experimental)" in t["description"], t["id"]
    assert "never run containment" in agent.INSTRUCTIONS and "experimental" in agent.INSTRUCTIONS
    assert agent.DEFAULT_QUESTION
