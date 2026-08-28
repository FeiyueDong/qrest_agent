from __future__ import annotations

from pathlib import Path
from typing import Any

from qrest_agent.agent.agent import QrestAgent
from qrest_agent.core.exporter import prepare_metadata_export
from qrest_agent.core.validator import validate_state
from qrest_agent.resources import qrest_examples_root
from qrest_agent.state.evidence import Evidence
from tests.conftest import write_json

DOCX_CASE = Path("resources/input_doc/Kunming_building_metadata_test_case.docx")


def _evidence(source_id: str = "user", text: str = "用户提供") -> list[Evidence]:
    return [Evidence(source_id=source_id, text=text)]


def test_acceptance_1_free_form_input_without_fixed_steps(artifact_dir: Path) -> None:
    """测试 1：一次性提供大量无结构文本，Agent 自主提取多类信息，不依赖固定步骤。"""
    agent = QrestAgent()
    text = (
        "项目名称为 Kunming_SSJY_Tower。结构类型为钢筋混凝土框架。"
        "事件名称为 2025_MYANMAR_7.9。采样间隔为 0.02s。数据点数为 30000。"
    )
    result = agent.run_turn(text)

    write_json(artifact_dir / "acceptance" / "1_free_form.json", result.to_dict())

    paths = set(agent.working_state.fields)
    for expected in (
        "BuildingInfo.ProjectName",
        "BuildingInfo.StructuralType",
        "DataInfo.EventName",
        "DataInfo.DT",
        "DataInfo.NPTS",
    ):
        assert expected in paths, expected
    assert result.decision.action == "ask_missing"  # 仍缺 Elevation/Channels 等，主动询问


def test_acceptance_2_document_upload_uses_file_tools(artifact_dir: Path) -> None:
    """测试 2：上传工程文档，Agent 通过文件工具读取并提取。"""
    agent = QrestAgent()
    result = agent.run_turn(files=[qrest_examples_root() / "kunming2" / "metadata.json"])

    write_json(artifact_dir / "acceptance" / "2_document_upload.json", result.to_dict())

    assert "BuildingInfo.ProjectName" in agent.working_state.fields
    assert result.report.ready
    assert agent.to_metadata()["BuildingInfo"]["ProjectName"] == "Kunming_SSJY"


def test_acceptance_3_missing_fields_are_asked_not_invented(artifact_dir: Path) -> None:
    """测试 3：缺少关键字段时明确告知缺失，不生成默认值。"""
    agent = QrestAgent()
    result = agent.run_turn("项目名称为 DemoBuilding。")

    write_json(artifact_dir / "acceptance" / "3_missing.json", result.to_dict())

    assert result.decision.action == "ask_missing"
    assert "BuildingInfo.Elevation" in result.report.missing_required
    elevation = agent.working_state.get("BuildingInfo.Elevation")
    assert elevation is None or elevation.value is None
    assert "BuildingInfo.Elevation" not in agent.to_metadata().get("BuildingInfo", {})


def test_acceptance_4_conflicts_are_marked_and_ask_confirmation(artifact_dir: Path) -> None:
    """测试 4：用户输入与已有信息冲突时标记 conflict 并请求确认。"""
    agent = QrestAgent()
    agent.working_state.set(
        "BuildingInfo.ProjectName",
        "OldName",
        evidence=_evidence("doc1", "文档中的名称"),
    )
    result = agent.run_turn("项目名称为 NewName。")

    write_json(artifact_dir / "acceptance" / "4_conflict.json", result.to_dict())

    record = agent.working_state.get("BuildingInfo.ProjectName")
    assert record is not None
    assert record.status == "conflict"
    assert result.decision.action == "resolve_conflicts"
    assert "BuildingInfo.ProjectName" in result.report.conflicts


def test_acceptance_5_deterministic_derivation_via_tool(artifact_dir: Path) -> None:
    """测试 5：DT=0.02 不再询问 Frequency，而是由 Tool 得到 50 Hz。"""
    agent = QrestAgent()
    result = agent.run_turn("采样间隔为 0.02s。")

    write_json(artifact_dir / "acceptance" / "5_derivation.json", result.to_dict())

    freq = [item for item in result.tool_results if item["tool"] == "calculate_frequency"]
    assert freq
    assert freq[0]["value"] == 50.0
    assert "50" in result.response
    assert "Frequency" in result.response


def test_acceptance_6_multi_turn_correction_keeps_evidence(artifact_dir: Path) -> None:
    """测试 6：多轮修正：用户纠正后 State 更新，并保留新旧证据。"""
    agent = QrestAgent()
    agent.working_state.set(
        "BuildingInfo.StructuralFootprint.Parameters",
        {"Length": 42.0, "Width": 25.2},
        evidence=_evidence("doc1", "资料中的尺寸"),
    )

    corrected = {"Length": 46.9, "Width": 25.2}
    agent.working_state.confirm(
        "BuildingInfo.StructuralFootprint.Parameters",
        corrected,
        _evidence("user_confirmation", "用户纠正：长度应为 46.9m"),
    )

    write_json(
        artifact_dir / "acceptance" / "6_correction.json",
        agent.working_state.to_audit_dict(),
    )

    record = agent.working_state.get("BuildingInfo.StructuralFootprint.Parameters")
    assert record is not None
    assert record.value == corrected
    assert record.status == "confirmed"
    assert any(item.source_id == "user_confirmation" for item in record.evidence)


def test_acceptance_7_export_only_when_required_fields_ready(artifact_dir: Path) -> None:
    """测试 7：必要字段满足后才允许导出正式 qREST Metadata。"""
    ready_agent = QrestAgent()
    ready_agent.run_turn(files=[qrest_examples_root() / "kunming2" / "metadata.json"])
    assert validate_state(ready_agent.working_state).ready
    ready_export = prepare_metadata_export(ready_agent.working_state)
    assert ready_export.ok
    assert ready_export.metadata is not None

    blocked_agent = QrestAgent()
    blocked_agent.run_turn("项目名称为 DemoBuilding。")
    blocked_export = prepare_metadata_export(blocked_agent.working_state)
    assert not blocked_export.ok
    assert "BuildingInfo.Elevation" in blocked_export.blocked_fields

    write_json(
        artifact_dir / "acceptance" / "7_export.json",
        {
            "ready_ok": ready_export.ok,
            "blocked_ok": blocked_export.ok,
            "blocked_fields": blocked_export.blocked_fields,
        },
    )
