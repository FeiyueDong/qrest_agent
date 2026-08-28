from __future__ import annotations

from pathlib import Path
from typing import Any

from qrest_agent.agent.agent import QrestAgent
from qrest_agent.resources import qrest_examples_root
from qrest_agent.state.evidence import Evidence
from tests.conftest import write_json


def _evidence(source_id: str = "test") -> list[Evidence]:
    return [Evidence(source_id=source_id, text="证据")]


class PlanToolClient:
    model = "plan-tool"

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.requests: list[list[dict[str, str]]] = []

    def complete_json(self, messages: list[dict[str, str]], schema_hint: dict[str, Any] | None = None) -> dict[str, Any]:
        self.requests.append(messages)
        return self.payload


def test_derivation_tools_auto_apply_counts_from_arrays() -> None:
    agent = QrestAgent()
    agent.working_state.set("BuildingInfo.Elevation", [0.0, 4.5, 7.8], evidence=_evidence())
    agent.working_state.set("InstrumentInfo.Channels", [{"ChannelNo": 1}, {"ChannelNo": 2}], evidence=_evidence())

    result = agent.run_turn()

    elevation_num = agent.working_state.get("BuildingInfo.ElevationNum")
    channel_num = agent.working_state.get("InstrumentInfo.ChannelNum")
    assert elevation_num is not None
    assert elevation_num.value == 3
    assert elevation_num.status == "derived"
    assert elevation_num.derived_from == ["BuildingInfo.Elevation"]
    assert channel_num is not None
    assert channel_num.value == 2
    assert channel_num.derived_from == ["InstrumentInfo.Channels"]
    tools = {item["tool"] for item in result.tool_results}
    assert "derive_counts" in tools


def test_frequency_is_computed_via_tool_not_model_reasoning() -> None:
    agent = QrestAgent()
    result = agent.run_turn("采样间隔为 0.02s。")

    freq_results = [item for item in result.tool_results if item["tool"] == "calculate_frequency"]
    assert freq_results
    assert freq_results[0]["value"] == 50.0
    assert "50" in result.response
    assert "Frequency" in result.response


def test_skill_guidance_informs_missing_field_decision() -> None:
    agent = QrestAgent()
    result = agent.run_turn("项目名称为 DemoBuilding。")

    assert result.decision.action == "ask_missing"
    assert result.decision.guidance
    joined = " ".join(result.decision.guidance)
    assert "building_info" in joined or "instrument_info" in joined or "data_info" in joined
    assert "禁止" in joined or "不能" in joined or "询问" in joined
    assert "参考 Skill" in result.response


def test_rule_planning_falls_back_to_extract() -> None:
    agent = QrestAgent()
    plan = agent.plan("项目名称为 Demo。")
    assert plan.action == "extract"
    assert plan.source == "rule"


def test_llm_planning_can_call_tool_and_execute_it() -> None:
    client = PlanToolClient(
        {
            "action": "tool",
            "tool": "calculate_frequency",
            "arguments": {"dt": 0.02},
            "skills": [],
            "reason": "user asks for sampling frequency",
        }
    )
    agent = QrestAgent(llm_client=client)

    plan = agent.plan("采样间隔 0.02s，帮我算频率")
    assert plan.action == "tool"
    assert plan.tool_name == "calculate_frequency"
    assert plan.source == "llm"

    result = agent.execute_plan(plan)
    assert result["ok"] is True
    assert result["output"]["frequency"] == 50.0
    assert client.requests
    assert "known_fields" in client.requests[0][1]["content"]


def test_llm_planning_with_unknown_tool_is_sanitized() -> None:
    client = PlanToolClient(
        {
            "action": "tool",
            "tool": "hack_tool",
            "arguments": {"x": 1},
            "skills": [],
            "reason": "invalid",
        }
    )
    agent = QrestAgent(llm_client=client)

    plan = agent.plan("随便")
    assert plan.action == "extract"
    assert plan.tool_name is None


def test_read_document_plan_feeds_extraction_loop(artifact_dir: Path) -> None:
    metadata_path = qrest_examples_root() / "kunming2" / "metadata.json"
    client = PlanToolClient(
        {
            "action": "tool",
            "tool": "read_document",
            "arguments": {"path": str(metadata_path)},
            "skills": [],
            "reason": "user wants to parse the metadata file",
        }
    )
    agent = QrestAgent(llm_client=client)

    result = agent.run_turn("解析这个文件")

    write_json(artifact_dir / "agent" / "agent_loop_read_document.json", result.to_dict())

    assert any(item.get("tool") == "read_document" and item.get("ok") for item in result.tool_results)
    assert "BuildingInfo.ProjectName" in agent.working_state.fields
    assert "工具读取" in result.response
    assert result.report.ready


def test_confirmed_counts_are_not_overwritten_by_derivation() -> None:
    agent = QrestAgent()
    agent.working_state.set("BuildingInfo.Elevation", [0.0, 4.5, 7.8, 11.1], evidence=_evidence())
    agent.working_state.confirm("BuildingInfo.ElevationNum", 5, _evidence("user"))

    result = agent.run_turn()

    record = agent.working_state.get("BuildingInfo.ElevationNum")
    assert record is not None
    assert record.value == 5
    assert record.status == "confirmed"
    assert not any(item.get("field_path") == "BuildingInfo.ElevationNum" for item in result.tool_results)
