from __future__ import annotations

from pathlib import Path
from typing import Any

from qrest_agent.agent.agent import QrestAgent
from qrest_agent.agent.planner import TurnPlan
from qrest_agent.core.models import Candidate
from qrest_agent.core.validator import validate_state
from qrest_agent.state.evidence import Evidence
from tests.conftest import write_json


class ScriptedClient:
    """按调用序号返回响应的 LLM mock（回合内调用顺序：intent→plan→extract→respond）。"""

    model = "scripted"

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.requests: list[list[dict[str, str]]] = []

    def complete_json(self, messages: list[dict[str, str]], schema_hint: dict[str, Any] | None = None) -> dict[str, Any]:
        self.requests.append(messages)
        index = len(self.requests) - 1
        if index < len(self.responses):
            return self.responses[index]
        return {"candidates": []}


def _candidate(field_path: str, value: Any, evidence_text: str, status: str = "extracted") -> dict[str, Any]:
    return {
        "field_path": field_path,
        "value": value,
        "status": status,
        "confidence": 0.9,
        "evidence": [{"source_id": "user_message", "text": evidence_text}],
    }


def _four_call_client(candidates: list[dict[str, Any]], response: str = "done") -> ScriptedClient:
    return ScriptedClient(
        [
            {"intent": "collect_metadata", "skills": ["building_info"], "need_user_input": False, "reason": "building"},
            {"actions": [{"type": "extract"}], "reason": "extract"},
            {"candidates": candidates},
            {"response": response},
        ]
    )


def test_a_skill_instructions_injected_into_extraction(artifact_dir: Path) -> None:
    """§61 Test A：Skill 内容真正进入 Extraction LLM 请求（不只是 Planner）。"""
    client = _four_call_client([])
    agent = QrestAgent(llm_client=client)

    agent.run_turn("建筑共14层，结构为RC框架。")

    write_json(artifact_dir / "round3" / "test_a_skill_into_extraction.json", {"requests": client.requests})
    extraction_content = client.requests[2][1]["content"]
    assert "Intent:" in extraction_content
    assert "Relevant skills:" in extraction_content
    assert "- building_info" in extraction_content
    assert "Skill instructions:" in extraction_content
    # building_info SKILL.md 的正文片段
    assert "BuildingInfo" in extraction_content
    assert "Source:" in extraction_content
    assert "结构为RC框架" in extraction_content


def test_b_correction_intent_reaches_extraction_and_confirms(artifact_dir: Path) -> None:
    """§61 Test B：intent=correction 传入 Extraction，且用户消息中的替代值 → confirmed。"""
    text = "前面的长度不对，改为46.9m。"
    client = ScriptedClient(
        [
            {"intent": "correction", "skills": ["building_info"], "need_user_input": False, "reason": "user correction"},
            {"actions": [{"type": "extract"}], "reason": ""},
            {
                "candidates": [
                    _candidate(
                        "BuildingInfo.StructuralFootprint.Parameters",
                        {"Length": 46.9, "Width": 25.2},
                        text,
                        status="extracted",
                    )
                ]
            },
            {"response": "已按你的更正更新。"},
        ]
    )
    agent = QrestAgent(llm_client=client)

    result = agent.run_turn(text)

    write_json(artifact_dir / "round3" / "test_b_correction_confirmed.json", result.to_dict())
    extraction_content = client.requests[2][1]["content"]
    assert "Intent:\ncorrection" in extraction_content
    record = agent.working_state.get("BuildingInfo.StructuralFootprint.Parameters")
    assert record is not None
    assert record.value == {"Length": 46.9, "Width": 25.2}
    assert record.status == "confirmed"
    assert result.candidates[0].status == "confirmed"


def test_c_trusted_context_status_filtering(artifact_dir: Path) -> None:
    """§61 Test C：accepted_facts 只含可导出状态；uncertain/inferred/conflict 单独分类。"""
    agent = QrestAgent()
    ws = agent.working_state
    ws.set("BuildingInfo.ProjectName", "Demo", status="extracted", evidence=[Evidence(source_id="doc", text="demo")])
    ws.set("BuildingInfo.StructuralType", "RCFrame", status="extracted", evidence=[Evidence(source_id="doc", text="rc")])
    ws.set("BuildingInfo.GeoLocation.NorthAngle", 15.0, status="uncertain", evidence=[Evidence(source_id="doc", text="angle")])
    ws.set("BuildingInfo.StructuralFootprint.Shape", "Rect", status="inferred", evidence=[Evidence(source_id="doc", text="shape")])
    ws.set("BuildingInfo.ElevationNum", 3, status="derived", evidence=[Evidence(source_id="tool", tool="derive_counts", text="count")])
    ws.submit(Candidate("BuildingInfo.Elevation", [0.0, 4.5], evidence=[Evidence(source_id="doc", text="elev")]))
    ws.submit(Candidate("BuildingInfo.Elevation", [0.0, 9.9], evidence=[Evidence(source_id="doc2", text="elev2")]))
    report = validate_state(ws)

    trusted = agent.build_trusted_context("", [], report, {}, [], TurnPlan(intent="collect_metadata"))

    write_json(artifact_dir / "round3" / "test_c_trusted_context.json", trusted)
    accepted_fields = {item["field"] for item in trusted["accepted_facts"]}
    assert "BuildingInfo.ProjectName" in accepted_fields
    assert "BuildingInfo.StructuralType" in accepted_fields
    assert "BuildingInfo.ElevationNum" in accepted_fields
    assert "BuildingInfo.GeoLocation.NorthAngle" not in accepted_fields
    assert "BuildingInfo.StructuralFootprint.Shape" not in accepted_fields
    assert {item["field"] for item in trusted["uncertain"]} == {"BuildingInfo.GeoLocation.NorthAngle"}
    assert {item["field"] for item in trusted["inferred"]} == {"BuildingInfo.StructuralFootprint.Shape"}
    assert "BuildingInfo.Elevation" in trusted["conflicts"]


def test_d_file_only_planning_sees_input_sources(tmp_path: Path, artifact_dir: Path) -> None:
    """§61 Test D：纯文件上传时 Planner 上下文包含 input_sources（知道本轮收到什么资料）。"""
    source = tmp_path / "building_report.txt"
    source.write_text("项目名称为 KunmingTower。\n建筑共14层，结构为RC框架。", encoding="utf-8")
    client = _four_call_client([])
    agent = QrestAgent(llm_client=client)

    agent.run_turn(files=[source])

    write_json(artifact_dir / "round3" / "test_d_input_sources.json", {"requests": client.requests})
    selection_content = client.requests[0][1]["content"]
    assert "input_sources" in selection_content
    assert "building_report.txt" in selection_content
    assert "chunk_count" in selection_content
    assert "preview" in selection_content
    # 第二阶段规划也携带 input_sources
    assert "input_sources" in client.requests[1][1]["content"]


def test_e_ask_action_creates_requested_inputs(artifact_dir: Path) -> None:
    """§61 Test E：缺 data.txt 时 ask Action 结构化，并进入 action_results/requested_inputs。"""
    agent = QrestAgent()
    result = agent.run_turn("用当前项目状态生成 qREST")

    ask = result.action_results.get("ask")
    write_json(artifact_dir / "round3" / "test_e_ask_action.json", result.to_dict())
    assert ask is not None
    assert ask["reason"] == "missing_data_txt"
    assert "data.txt" in ask["request"]
    assert ask["expected"] == "path_or_attachment"
    # Trusted Context 中 requested_inputs 非空
    trusted = agent.build_trusted_context(
        "用当前项目状态生成 qREST",
        result.candidates,
        result.report,
        result.action_results,
        [],
        result.plan or TurnPlan(intent="qrest_task"),
    )
    assert trusted["requested_inputs"] == [ask]
    # 模板 fallback 回复直接使用 ask 的 request
    assert "data.txt" in result.response


def test_f_responder_receives_recent_conversation(artifact_dir: Path) -> None:
    """§61 Test F：recent_conversation 真正送入 Responder（多轮指代能力）。"""
    client = _four_call_client([_candidate("BuildingInfo.ProjectName", "Demo", "项目名称为 Demo。")], "已记录。")
    agent = QrestAgent(llm_client=client)

    agent.run_turn("项目名称为 Demo。")
    agent.run_turn("采样间隔为 0.02s。")

    write_json(artifact_dir / "round3" / "test_f_responder_history.json", {"requests": client.requests})
    assert len(client.requests) == 8
    responder_content = client.requests[7][1]["content"]
    assert "recent_conversation" in responder_content
    assert "项目名称为 Demo。" in responder_content
    assert "BuildingInfo.ProjectName" in responder_content
    # 对话历史只用于理解指代，不是工程事实来源（prompt 明确声明）
    assert "对话历史" in responder_content or "recent_conversation" in responder_content
