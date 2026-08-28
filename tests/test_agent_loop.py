from __future__ import annotations

from pathlib import Path
from typing import Any

from qrest_agent.agent.agent import QrestAgent
from qrest_agent.resources import qrest_examples_root
from qrest_agent.state.evidence import Evidence
from tests.conftest import write_json


def _evidence(source_id: str = "test") -> list[Evidence]:
    return [Evidence(source_id=source_id, text="证据")]


class PlanClient:
    """两步规划 mock：第一次 intent+skill 选择，第二次 action planning。"""

    model = "plan"

    def __init__(self, intent_payload: dict[str, Any], action_payload: dict[str, Any]) -> None:
        self.intent_payload = intent_payload
        self.action_payload = action_payload
        self.requests: list[list[dict[str, str]]] = []

    def complete_json(self, messages: list[dict[str, str]], schema_hint: dict[str, Any] | None = None) -> dict[str, Any]:
        self.requests.append(messages)
        if len(self.requests) == 1:
            return self.intent_payload
        return self.action_payload


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
    assert elevation_num.evidence and elevation_num.evidence[0].tool == "derive_counts"
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


def test_rule_planning_falls_back_to_collect_metadata() -> None:
    agent = QrestAgent()
    plan = agent.planner.plan("项目名称为 Demo。", agent.build_turn_context("项目名称为 Demo。", []), None)
    assert plan.intent == "collect_metadata"
    assert plan.actions[0].type == "extract"
    assert plan.source == "rule"


def test_llm_planning_executes_tool_actions() -> None:
    client = PlanClient(
        {"intent": "question", "skills": [], "need_user_input": False, "reason": "frequency"},
        {"actions": [{"type": "tool", "tool": "calculate_frequency", "arguments": {"dt": 0.02}}], "reason": "frequency"},
    )
    agent = QrestAgent(llm_client=client)

    result = agent.run_turn("采样间隔 0.02s，帮我算频率")

    assert result.action_results["tool:calculate_frequency"]["frequency"] == 50.0
    assert client.requests
    assert "available_skills" in client.requests[0][1]["content"]


def test_llm_planning_with_unknown_tool_is_sanitized() -> None:
    client = PlanClient(
        {"intent": "question", "skills": [], "need_user_input": False, "reason": ""},
        {"actions": [{"type": "tool", "tool": "hack_tool", "arguments": {"x": 1}}], "reason": "invalid"},
    )
    agent = QrestAgent(llm_client=client)

    plan = agent.planner.plan("随便", agent.build_turn_context("随便", []), client)
    assert plan.actions == [plan.actions[0]]
    assert plan.actions[0].type == "extract"
    # run_turn 不抛异常
    agent.run_turn("随便")


def test_skill_selection_loads_full_skill_content_into_planning(artifact_dir: Path) -> None:
    """设计文档 §7 / 验收 Test 1：选中的 Skill 完整内容注入规划上下文。"""
    client = PlanClient(
        {"intent": "collect_metadata", "skills": ["building_info"], "need_user_input": False, "reason": "building"},
        {"actions": [{"type": "extract"}], "reason": "extract building info"},
    )
    agent = QrestAgent(llm_client=client)

    agent.run_turn("建筑共14层，结构为RC框架。")

    write_json(artifact_dir / "agent" / "skill_selection.json", {"requests": client.requests})
    # 完整回合：intent 选择 → action 规划 → LLM 提取 → LLM 回复
    assert len(client.requests) == 4
    planning_content = client.requests[1][1]["content"]
    assert '"name": "building_info"' in planning_content
    assert "必须询问" in planning_content or "禁止猜测" in planning_content
    assert "ElevationNum" in planning_content
    # 提取请求也携带了完整资料文本
    assert "结构为RC框架" in client.requests[2][1]["content"]


def test_read_document_plan_feeds_extraction_loop(artifact_dir: Path) -> None:
    metadata_path = qrest_examples_root() / "kunming2" / "metadata.json"
    client = PlanClient(
        {"intent": "collect_metadata", "skills": ["metadata"], "need_user_input": False, "reason": "parse file"},
        {
            "actions": [
                {"type": "tool", "tool": "read_document", "arguments": {"path": str(metadata_path)}},
                {"type": "extract"},
            ],
            "reason": "read then extract",
        },
    )
    agent = QrestAgent(llm_client=client)

    result = agent.run_turn("解析这个文件")

    write_json(artifact_dir / "agent" / "agent_loop_read_document.json", result.to_dict())

    assert result.action_results["tool:read_document"]["chunk_count"] >= 1
    assert "BuildingInfo.ProjectName" in agent.working_state.records
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


class EvidenceClient:
    model = "evidence"

    def __init__(self, candidates: list[dict[str, Any]]) -> None:
        self.candidates = candidates

    def complete_json(self, messages: list[dict[str, str]], schema_hint: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"candidates": self.candidates}


def test_llm_candidate_without_evidence_is_rejected() -> None:
    """验收 Test 4：value 非空但 evidence 为空 → 候选被拒绝。"""
    client = EvidenceClient(
        [
            {
                "field_path": "BuildingInfo.StructuralType",
                "value": "RCFrame",
                "status": "extracted",
                "confidence": 0.9,
                "evidence": [],
            }
        ]
    )
    agent = QrestAgent(llm_client=client)
    # 英文表述：规则提取器（fallback）也无法从文本中提取，隔离 LLM 候选
    result = agent.run_turn("The structure consists of reinforced-concrete moment frames.")

    assert result.candidates == []
    assert agent.working_state.get("BuildingInfo.StructuralType") is None


def test_llm_candidate_with_unverifiable_evidence_downgraded_to_uncertain() -> None:
    """验收 Test 5：evidence 文本在来源中不存在 → 降为 uncertain，禁止进入最终数据。"""
    client = EvidenceClient(
        [
            {
                "field_path": "BuildingInfo.StructuralType",
                "value": "RCFrame",
                "status": "extracted",
                "confidence": 0.9,
                "evidence": [{"source_id": "user_message", "text": "这段文本并不存在于资料中"}],
            }
        ]
    )
    agent = QrestAgent(llm_client=client)
    result = agent.run_turn("结构类型为 RCFrame。")

    record = agent.working_state.get("BuildingInfo.StructuralType")
    assert record is not None
    assert record.status == "uncertain"
    assert "StructuralType" not in agent.to_metadata().get("BuildingInfo", {})
    assert len(result.candidates) == 1
