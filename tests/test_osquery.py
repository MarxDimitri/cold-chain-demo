"""The advisory lens: advisories are data, the agent's prompts name none, and the answers are checked per advisory."""
import json

from coldchain import agent, hunt, osquery


def test_advisories_are_rows_from_the_yaml_file_with_numeric_versions_and_join_keys():
    rows = osquery.advisory_rows()
    assert len(rows) == 4 and {r["advisory"]["id"] for r in rows} == {"CVE-2026-114938"}
    r17 = next(r for r in rows if r["osquery"]["branch"] == "17")
    assert r17["kb"]["key"] == "CVE-2026-114938:OpenJDK:17" and r17["osquery"]["name"] == "OpenJDK"
    assert r17["advisory"]["affected_from_num"] == 17000006000 and r17["advisory"]["fixed_in_num"] == 17000021001
    assert r17["advisory"]["requires_cpu_flag"] == "avx512vbmi" and r17["advisory"]["mitigation_arg_2"] == "-XX:UseAVX=2"


def test_version_numbers_sort_like_versions():
    v = osquery.version_num
    assert v("17.0.6") < v("17.0.8") < v("17.0.21") < v("17.0.21.1") < v("21.0.0") < v("21.0.13.1")


def test_the_answers_are_generic_software_cpu_and_process_rows_and_offline_stores_are_silent():
    docs = [json.loads(line) for _, line in osquery.results("2026-11-19T09:00:00Z", "a")]
    assert {d["action_data"]["id"] for d in docs} == {"software", "cpu", "process"}
    assert {d["retail"]["store"]["id"] for d in docs}.isdisjoint(osquery.OFFLINE)
    sw = next(d for d in docs if d["host"]["name"] == "S07-POS-BO-01" and d["action_data"]["id"] == "software")
    assert sw["osquery"]["version"] == "17.0.8" and sw["osquery"]["branch"] == "17" and sw["osquery"]["version_num"] == 17000008000


def test_no_prompt_or_tool_description_names_a_vulnerability():
    texts = [agent.INSTRUCTIONS, hunt.MESSAGE] + [t["description"] for t in agent.TOOLS]
    for text in texts:
        for word in ("CVE-", "Java4Shell", "OpenJDK", "BSI", "AVX", "Base64"):
            assert word not in text, word


def test_the_exposure_tool_takes_the_advisory_id_as_a_parameter_and_names_no_product():
    tool = next(t for t in agent.TOOLS if t["id"] == "cc_advisory_exposure")
    assert set(tool["params"]) == {"advisory"} and "?advisory" in tool["query"]
    for word in ("OpenJDK", "java", "avx512", "CVE-"):
        assert word not in tool["query"]
    assert "kb-advisories" in tool["query"] and "CONTAINS(cpu, advisory.requires_cpu_flag)" in tool["query"]
    assert any(t["id"] == "cc_list_advisories" for t in agent.TOOLS)
