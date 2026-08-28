from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from qrest_agent.agent.agent import QrestAgent
from qrest_agent.resources import qrest_examples_root, skills_root
from qrest_agent.skills import SkillRegistry
from qrest_agent.state.evidence import Evidence
from qrest_agent.state.working_state import WorkingState
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


class ContentDrivenClient:
    """依据 Skill 内容决定行为的 mock（验收 Test 2：Skill 改变 Agent 行为）。"""

    model = "content-driven"

    def __init__(self) -> None:
        self.requests: list[list[dict[str, str]]] = []

    def complete_json(self, messages: list[dict[str, str]], schema_hint: dict[str, Any] | None = None) -> dict[str, Any]:
        self.requests.append(messages)
        if len(self.requests) == 1:
            return {"intent": "collect_metadata", "skills": ["building_info"], "need_user_input": False, "reason": ""}
        if len(self.requests) == 2:
            planning = messages[1]["content"]
            if "必须向用户确认" in planning:
                return {"actions": [{"type": "ask"}], "reason": "skill requires confirmation"}
            return {"actions": [{"type": "extract"}], "reason": "extract"}
        if len(self.requests) == 3:
            return {"candidates": []}
        return {"response": "done"}


def _candidate(field_path: str, value: Any, evidence_text: str, status: str = "extracted") -> dict[str, Any]:
    return {
        "field_path": field_path,
        "value": value,
        "status": status,
        "confidence": 0.9,
        "evidence": [{"source_id": "user_message", "text": evidence_text}],
    }


def test_1_skill_dynamic_selection(artifact_dir: Path) -> None:
    """§26 Test 1：LLM 选择 building_info，完整 SKILL.md 注入规划上下文。"""
    client = ScriptedClient(
        [
            {"intent": "collect_metadata", "skills": ["building_info"], "need_user_input": False, "reason": "building"},
            {"actions": [{"type": "extract"}], "reason": "extract"},
            {"candidates": []},
            {"response": "已按建筑信息 Skill 处理。"},
        ]
    )
    agent = QrestAgent(llm_client=client)
    result = agent.run_turn("建筑共14层，地下一层，结构为RC框架。")

    write_json(artifact_dir / "acceptance" / "architecture_t1_skill_selection.json", {"requests": client.requests, "response": result.response})

    planning = client.requests[1][1]["content"]
    assert '"name": "building_info"' in planning
    assert "必须询问" in planning
    assert result.response == "已按建筑信息 Skill 处理。"


def test_2_skill_changes_agent_behavior(tmp_path: Path, artifact_dir: Path) -> None:
    """§26 Test 2：修改 Skill 内容 → Agent 行为随之变化（Skill 不是装饰）。"""
    # 修改版 Skill：要求 StructuralType 必须向用户确认
    modified_root = tmp_path / "skills"
    shutil.copytree(skills_root() / "building_info", modified_root / "building_info")
    skill_path = modified_root / "building_info" / "SKILL.md"
    skill_path.write_text(skill_path.read_text(encoding="utf-8") + "\n## 强制规则\nStructuralType 必须向用户确认，不允许直接采用文档信息。\n", encoding="utf-8")

    default_client = ContentDrivenClient()
    default_agent = QrestAgent(llm_client=default_client)
    default_plan = default_agent.planner.plan(
        "结构类型为 RC 框架。", default_agent.build_turn_context("结构类型为 RC 框架。", []), default_client
    )

    modified_client = ContentDrivenClient()
    modified_agent = QrestAgent(llm_client=modified_client, skill_registry=SkillRegistry(root=modified_root))
    modified_plan = modified_agent.planner.plan(
        "结构类型为 RC 框架。", modified_agent.build_turn_context("结构类型为 RC 框架。", []), modified_client
    )

    write_json(
        artifact_dir / "acceptance" / "architecture_t2_skill_behavior.json",
        {
            "default_plan": default_plan.to_dict(),
            "modified_plan": modified_plan.to_dict(),
            "default_planning_content_tail": default_client.requests[1][1]["content"][-200:],
            "modified_planning_content_tail": modified_client.requests[1][1]["content"][-200:],
        },
    )

    # 关键：Skill 内容真正进入规划输入，且规划结果随 Skill 内容改变
    assert "必须向用户确认" in modified_client.requests[1][1]["content"]
    assert "必须向用户确认" not in default_client.requests[1][1]["content"]
    assert default_plan.actions[0].type == "extract"
    assert modified_plan.actions[0].type == "ask"


def test_3_extraction_without_regex_english_expression(artifact_dir: Path) -> None:
    """§26 Test 3：从未编写过规则的新表述，LLM 仍能语义提取。"""
    text = "The structure consists primarily of reinforced-concrete moment frames."
    client = ScriptedClient(
        [
            {"intent": "collect_metadata", "skills": [], "need_user_input": False, "reason": ""},
            {"actions": [{"type": "extract"}], "reason": ""},
            {"candidates": [_candidate("BuildingInfo.StructuralType", "RCFrame", text)]},
            {"response": "已确认结构类型为 RCFrame。"},
        ]
    )
    agent = QrestAgent(llm_client=client)
    result = agent.run_turn(text)

    write_json(artifact_dir / "acceptance" / "architecture_t3_no_regex.json", result.to_dict())

    record = agent.working_state.get("BuildingInfo.StructuralType")
    assert record is not None
    assert record.value == "RCFrame"
    assert record.status == "extracted"
    assert result.extractor == "llm"


def test_4_fake_evidence_rejected(artifact_dir: Path) -> None:
    """§26 Test 4：value 非空 + evidence 为空 → 候选被拒绝。"""
    client = ScriptedClient(
        [
            {"intent": "collect_metadata", "skills": [], "need_user_input": False, "reason": ""},
            {"actions": [{"type": "extract"}], "reason": ""},
            {"candidates": [_candidate("BuildingInfo.StructuralType", "RCFrame", "irrelevant", status="extracted")]},
            {"response": "done"},
        ]
    )
    # 去除 evidence：直接构造无证据候选
    client.responses[2] = {"candidates": [{"field_path": "BuildingInfo.StructuralType", "value": "RCFrame", "status": "extracted", "confidence": 0.9, "evidence": []}]}
    agent = QrestAgent(llm_client=client)
    result = agent.run_turn("The structure is RC.")

    write_json(artifact_dir / "acceptance" / "architecture_t4_no_evidence.json", result.to_dict())

    assert agent.working_state.get("BuildingInfo.StructuralType") is None


def test_5_forged_evidence_downgraded_to_uncertain(artifact_dir: Path) -> None:
    """§26 Test 5：evidence 文本不存在于来源 → 拒绝或降为 uncertain（此处降级）。"""
    client = ScriptedClient(
        [
            {"intent": "collect_metadata", "skills": [], "need_user_input": False, "reason": ""},
            {"actions": [{"type": "extract"}], "reason": ""},
            {"candidates": [_candidate("BuildingInfo.StructuralType", "RCFrame", "这段引文并不存在于资料中")]},
            {"response": "done"},
        ]
    )
    agent = QrestAgent(llm_client=client)
    result = agent.run_turn("The structure is RC.")

    write_json(artifact_dir / "acceptance" / "architecture_t5_forged_evidence.json", result.to_dict())

    record = agent.working_state.get("BuildingInfo.StructuralType")
    assert record is not None
    assert record.status == "uncertain"
    assert "StructuralType" not in agent.to_metadata().get("BuildingInfo", {})


def test_6_missing_info_not_invented(artifact_dir: Path) -> None:
    """§26 Test 6：仅"14层建筑"→ 不生成 Elevation/StructuralType/NorthAngle。"""
    agent = QrestAgent()
    result = agent.run_turn("这是一个14层建筑。")

    write_json(artifact_dir / "acceptance" / "architecture_t6_missing.json", result.to_dict())

    for path in ("BuildingInfo.Elevation", "BuildingInfo.StructuralType", "BuildingInfo.GeoLocation.NorthAngle"):
        record = agent.working_state.get(path)
        assert record is None or record.value is None, path
    metadata = agent.to_metadata()
    building = metadata.get("BuildingInfo", {})
    assert "Elevation" not in building
    assert "StructuralType" not in building


def test_7_true_derived_counts(artifact_dir: Path) -> None:
    """§26 Test 7：Elevation 存在 → ElevationNum 自动 derived。"""
    agent = QrestAgent()
    agent.working_state.set("BuildingInfo.Elevation", [0.0, 4.5, 7.8], evidence=[Evidence(source_id="doc1")])
    agent.run_turn()

    write_json(artifact_dir / "acceptance" / "architecture_t7_derived.json", agent.working_state.to_audit_dict())

    record = agent.working_state.get("BuildingInfo.ElevationNum")
    assert record is not None
    assert record.value == 3
    assert record.status == "derived"
    assert record.derived_from == ["BuildingInfo.Elevation"]
    assert record.evidence[0].tool == "derive_counts"


def test_8_engineering_assumption_not_derived(artifact_dir: Path) -> None:
    """§26 Test 8：只有长宽与每层3个传感器 → 不得自动产生测点坐标。"""
    agent = QrestAgent()
    result = agent.run_turn("建筑长度方向约42m，宽度方向约25.2m，每层布置3个传感器。")

    write_json(artifact_dir / "acceptance" / "architecture_t8_no_assumption.json", result.to_dict())

    assert agent.working_state.get("InstrumentInfo.Channels") is None
    assert agent.working_state.get("InstrumentInfo.ChannelNum") is None
    assert "Channels" not in agent.to_metadata().get("InstrumentInfo", {})


def test_9_natural_language_response(artifact_dir: Path) -> None:
    """§26 Test 9：缺 NorthAngle 时由 LLM 生成自然解释，而不是字段列表。"""
    client = ScriptedClient(
        [
            {"intent": "collect_metadata", "skills": [], "need_user_input": False, "reason": ""},
            {"actions": [{"type": "extract"}], "reason": ""},
            {"candidates": []},
            {"response": "目前建筑朝向（局部 Y 轴与正北方向的夹角）还没有可靠来源，这一项不能根据建筑所在地推测。如果有设计图或测点坐标说明，可以继续上传；也可以直接告诉我夹角数值。"},
        ]
    )
    agent = QrestAgent(llm_client=client)
    result = agent.run_turn("这是一栋昆明的建筑。")

    write_json(artifact_dir / "acceptance" / "architecture_t9_response.json", result.to_dict())

    assert "局部 Y 轴与正北方向的夹角" in result.response
    assert "不能根据建筑所在地推测" in result.response
    # 模板 fallback 与 LLM 回复不同（rule 模式输出字段列表）
    rule_agent = QrestAgent()
    rule_response = rule_agent.run_turn("这是一栋昆明的建筑。").response
    assert rule_response != result.response


def test_10_user_correction_by_main_agent(artifact_dir: Path) -> None:
    """§26 Test 10：用户修正由主 Agent 直接完成，无第二套 Action Agent。"""
    text = "前面的长度不对，改为46.9m。"
    client = ScriptedClient(
        [
            {"intent": "correction", "skills": [], "need_user_input": False, "reason": "user correction"},
            {"actions": [{"type": "extract"}], "reason": ""},
            {"candidates": [_candidate("BuildingInfo.StructuralFootprint.Parameters", {"Length": 46.9, "Width": 25.2}, text, status="confirmed")]},
            {"response": "已按你的更正更新建筑尺寸。"},
        ]
    )
    agent = QrestAgent(llm_client=client)
    result = agent.run_turn(text)

    write_json(artifact_dir / "acceptance" / "architecture_t10_correction.json", result.to_dict())

    record = agent.working_state.get("BuildingInfo.StructuralFootprint.Parameters")
    assert record is not None
    assert record.value == {"Length": 46.9, "Width": 25.2}
    assert record.status == "confirmed"
    assert any(item.source_id == "user_message" for item in record.evidence)
    assert result.response == "已按你的更正更新建筑尺寸。"


def test_11_qrest_generation_via_skill_and_tools(tmp_path: Path, artifact_dir: Path) -> None:
    """§26 Test 11：qREST 生成 = Agent 选择 qrest_data → export → generate Tool → 回复。"""
    from qrest_agent.agent.tool_registry import ToolRegistry

    agent = QrestAgent(
        tool_registry=ToolRegistry(artifact_root=tmp_path / "artifacts"),
        session_id="acceptance-11",
    )
    example_dir = qrest_examples_root() / "kunming2"
    agent.run_turn(files=[example_dir / "metadata.json"])

    result = agent.run_turn(f"用当前工程信息和 {example_dir / 'data.txt'} 生成 qREST")

    write_json(
        artifact_dir / "acceptance" / "architecture_t11_generate.json",
        {"result": result.to_dict(), "artifacts": agent.tools.artifacts.list("acceptance-11")},
    )

    assert result.plan is not None
    assert result.plan.intent == "qrest_task"
    assert "qrest_data" in result.plan.skills
    assert result.action_results["export"]["ok"]
    assert result.action_results["tool:generate_qrest"]["ok"]
    artifacts = agent.tools.artifacts.list("acceptance-11")
    assert any(item["name"] == "metadata.json" for item in artifacts)
    assert any(item["name"] == "generated.qrest" for item in artifacts)
    assert "工具 generate_qrest 执行成功" in result.response
