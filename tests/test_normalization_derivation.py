from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from qrest_agent.agent.agent import QrestAgent
from qrest_agent.core.canonicalize import canonicalize_value, metadata_string_errors
from qrest_agent.core.exporter import prepare_metadata_export
from qrest_agent.core.schema_gate import SchemaViolation
from qrest_agent.state.evidence import Evidence as StateEvidence
from qrest_agent.state.working_state import FieldState, WorkingState
from tests.conftest import write_json


class ScriptedClient:
    """按调用序号返回响应的 LLM mock（回合内顺序：intent→plan→extract×N→respond）。"""

    model = "scripted"

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.requests: list[list[dict[str, str]]] = []

    def complete_json(self, messages: list[dict[str, str]], schema_hint: dict[str, Any] | None = None) -> dict[str, Any]:
        self.requests.append(messages)
        index = len(self.requests) - 1
        if index < len(self.responses):
            return self.responses[index]
        return {"candidates": [], "facts": []}


def _evidence(text: str) -> list[dict[str, Any]]:
    return [{"source_id": "user_message", "text": text}]


# ---- 方案 §16：ASCII 规范化 ----

def test_canonicalize_controlled_chinese_values() -> None:
    assert canonicalize_value("BuildingInfo.StructuralType", "钢框架").value == "SteelFrame"
    assert canonicalize_value("BuildingInfo.StructuralType", "钢筋混凝土框架").value == "RCFrame"
    assert canonicalize_value("BuildingInfo.StructuralFootprint.Shape", "矩形").value == "Rectangular"
    assert canonicalize_value("InstrumentInfo.Channels[0].Measurand", "加速度").value == "Acceleration"
    # 已是标准 ASCII 值 → 原样返回
    assert canonicalize_value("BuildingInfo.StructuralType", "RCFrame").value == "RCFrame"


def test_canonicalize_free_text_chinese_fails_without_translation() -> None:
    result = canonicalize_value("BuildingInfo.ProjectName", "昆明大楼")
    assert result.status == "failed"
    assert "do not invent" in result.reason
    result2 = canonicalize_value("DataInfo.EventName", "地震事件")
    assert result2.status == "failed"


def test_metadata_string_errors_detect_non_ascii_and_bad_controlled_values() -> None:
    errors = metadata_string_errors({"BuildingInfo": {"StructuralType": "钢框架"}})
    assert any("non-ASCII" in error for error in errors)
    errors2 = metadata_string_errors({"BuildingInfo": {"StructuralType": "NotARealType"}})
    assert any("not a standard StructuralType value" in error for error in errors2)
    errors3 = metadata_string_errors({"BuildingInfo": {"StructuralType": "SteelFrame"}})
    assert errors3 == []


def test_agent_maps_llm_chinese_structural_type_to_ascii(artifact_dir: Path) -> None:
    client = ScriptedClient(
        [
            {"intent": "collect_metadata", "skills": [], "need_user_input": False, "reason": ""},
            {"actions": [{"type": "extract"}], "reason": ""},
            {
                "candidates": [
                    {"field_path": "BuildingInfo.StructuralType", "value": "钢框架", "status": "extracted",
                     "confidence": 0.9, "evidence": _evidence("结构为钢框架。")}
                ]
            },
            {"response": "已记录结构类型。"},
        ]
    )
    agent = QrestAgent(llm_client=client)
    result = agent.run_turn("结构为钢框架。")

    write_json(artifact_dir / "normalization" / "ascii_structural_type.json", result.to_dict())
    record = agent.working_state.get("BuildingInfo.StructuralType")
    assert record is not None
    assert record.value == "SteelFrame"
    assert record.status == "extracted"
    metadata = agent.to_metadata()
    assert metadata["BuildingInfo"]["StructuralType"] == "SteelFrame"
    assert metadata_string_errors(metadata) == []


def test_agent_keeps_chinese_free_text_as_uncertain(artifact_dir: Path) -> None:
    """方案 §3.2：ProjectName 只有中文 → 不创造英文名，降为 uncertain，不进 metadata。"""
    client = ScriptedClient(
        [
            {"intent": "collect_metadata", "skills": [], "need_user_input": False, "reason": ""},
            {"actions": [{"type": "extract"}], "reason": ""},
            {
                "candidates": [
                    {"field_path": "BuildingInfo.ProjectName", "value": "昆明大楼", "status": "extracted",
                     "confidence": 0.9, "evidence": _evidence("项目名称为昆明大楼。")}
                ]
            },
            {"response": "需要确认项目英文名称。"},
        ]
    )
    agent = QrestAgent(llm_client=client)
    result = agent.run_turn("项目名称为昆明大楼。")

    write_json(artifact_dir / "normalization" / "chinese_free_text_uncertain.json", result.to_dict())
    record = agent.working_state.get("BuildingInfo.ProjectName")
    assert record is not None
    assert record.status == "uncertain"
    assert "ProjectName" not in agent.to_metadata().get("BuildingInfo", {})
    assert result.candidates[0].status == "uncertain"


def test_confirm_command_canonicalizes_controlled_value() -> None:
    from qrest_agent.agent.dialogue import ChatSession

    session = ChatSession()
    result = session.handle("/confirm BuildingInfo.StructuralType 钢框架")
    record = session.agent.working_state.get("BuildingInfo.StructuralType")
    assert record is not None
    assert record.status == "confirmed"
    assert record.value == "SteelFrame"
    # 自由字段中文确认 → 拒绝（不创造英文名）
    result2 = session.handle("/confirm BuildingInfo.ProjectName 昆明大楼")
    assert "规范化失败" in result2.response
    assert session.agent.working_state.get("BuildingInfo.ProjectName") is None


def test_exporter_blocks_non_ascii_metadata(artifact_dir: Path) -> None:
    state = WorkingState.empty()
    state._fields["BuildingInfo.StructuralType"] = FieldState(
        field_path="BuildingInfo.StructuralType", value="钢框架", status="confirmed",
        confidence=1.0, evidence=[StateEvidence(source_id="bug", text="simulated")],
    )
    export = prepare_metadata_export(state)
    write_json(artifact_dir / "normalization" / "exporter_ascii_gate.json", export.to_dict())
    assert not export.ok
    # ASCII 错误在 validate_state 的 Schema/Canonical 层即被拦截（final gate 是兜底）
    assert any("non-ASCII" in issue.message for issue in export.report.issues)
    assert metadata_string_errors(state.to_metadata())


# ---- 方案 §16：StructuralFootprint 推导 ----

def test_footprint_facts_derive_parameters_and_bounding_box(artifact_dir: Path) -> None:
    client = ScriptedClient(
        [
            {"intent": "collect_metadata", "skills": [], "need_user_input": False, "reason": ""},
            {"actions": [{"type": "extract"}], "reason": ""},
            {
                "candidates": [
                    {"field_path": "BuildingInfo.StructuralFootprint.Shape", "value": "矩形", "status": "extracted",
                     "confidence": 0.9, "evidence": _evidence("建筑平面呈矩形，尺寸约42m × 25.2m。")}
                ],
                "facts": [
                    {"path": "Building.footprint_length", "value": 42.0, "status": "extracted",
                     "evidence": _evidence("尺寸约42m")},
                    {"path": "Building.footprint_width", "value": 25.2, "status": "extracted",
                     "evidence": _evidence("25.2m")},
                ],
            },
            {"response": "已生成平面参数。"},
        ]
    )
    agent = QrestAgent(llm_client=client)
    result = agent.run_turn("建筑平面呈矩形，尺寸约42m × 25.2m。")

    write_json(artifact_dir / "normalization" / "footprint_derivation.json", result.to_dict())
    # Shape 中文 → canonical → Rectangular
    assert agent.working_state.get("BuildingInfo.StructuralFootprint.Shape").value == "Rectangular"
    # Parameters 由 facts 确定性推导
    parameters = agent.working_state.get("BuildingInfo.StructuralFootprint.Parameters")
    assert parameters is not None
    assert parameters.status == "derived"
    assert parameters.value == {"Length": 42.0, "Width": 25.2}
    assert parameters.derived_from == ["Building.footprint_length", "Building.footprint_width"]
    # BoundingBox 由 Tool 计算
    bbox = agent.working_state.get("BuildingInfo.StructuralFootprint.BoundingBox")
    assert bbox is not None
    assert bbox.status == "derived"
    assert bbox.value == {"MaxX": 21.0, "MinX": -21.0, "MaxY": 12.6, "MinY": -12.6}
    assert bbox.evidence[0].tool == "calculate_bounding_box"
    # facts 不进入 metadata
    metadata = agent.to_metadata()
    assert "Building" not in metadata or "footprint_length" not in metadata["Building"]
    assert agent.working_state.get_fact("Building.footprint_length").value == 42.0


def test_footprint_without_shape_does_not_derive_parameters() -> None:
    """只有尺寸没有形状描述 → 不能假设矩形，Parameters 保持 missing（Accuracy First）。"""
    agent = QrestAgent()
    agent.working_state.set_fact("Building.footprint_length", 42.0, evidence=[StateEvidence(source_id="doc", text="42")])
    agent.working_state.set_fact("Building.footprint_width", 25.2, evidence=[StateEvidence(source_id="doc", text="25.2")])
    agent.run_turn("")
    assert agent.working_state.get("BuildingInfo.StructuralFootprint.Parameters") is None
    assert agent.working_state.get("BuildingInfo.StructuralFootprint.BoundingBox") is None


# ---- 方案 §16：Elevation 推导（跨 chunk 聚合）----

def test_elevation_facts_derive_elevation_and_num(artifact_dir: Path) -> None:
    agent = QrestAgent()
    for path, value, text in [
        ("Building.above_ground_floors", 14, "地上14层"),
        ("Building.basement_floors", 2, "地下2层"),
        ("Building.first_floor_height", 4.5, "首层4.5m"),
        ("Building.typical_story_height", 3.3, "标准层3.3m"),
        ("Building.basement_first_height", 2.7, "地下首层层高2.7m"),
    ]:
        agent.working_state.set_fact(path, value, evidence=[StateEvidence(source_id="doc", text=text)])

    result = agent.run_turn("")

    write_json(artifact_dir / "normalization" / "elevation_derivation.json", result.to_dict())
    elevation = agent.working_state.get("BuildingInfo.Elevation")
    assert elevation is not None
    assert elevation.status == "derived"
    assert elevation.value == [-2.7, 0.0, 4.5, 7.8, 11.1, 14.4, 17.7, 21.0, 24.3, 27.6, 30.9, 34.2, 37.5, 40.8, 44.1, 47.4]
    assert elevation.evidence[0].tool == "derive_elevation_profile"
    elevation_num = agent.working_state.get("BuildingInfo.ElevationNum")
    assert elevation_num is not None
    assert elevation_num.status == "derived"
    assert elevation_num.value == 16


def test_elevation_cross_chunk_aggregation(tmp_path: Path, artifact_dir: Path) -> None:
    """方案 §13：层数（文件1）与层高（文件2）分属不同 chunk，聚合后仍能推导。"""
    floors_file = tmp_path / "floors.txt"
    floors_file.write_text("地上14层，地下2层。", encoding="utf-8")
    heights_file = tmp_path / "heights.txt"
    heights_file.write_text("首层4.5m，标准层3.3m，地下首层层高2.7m。", encoding="utf-8")
    client = ScriptedClient(
        [
            {"intent": "collect_metadata", "skills": [], "need_user_input": False, "reason": ""},
            {"actions": [{"type": "extract"}], "reason": ""},
            # chunk 1（floors.txt）：层数
            {"candidates": [], "facts": [
                {"path": "Building.above_ground_floors", "value": 14, "status": "extracted", "evidence": _evidence("地上14层")},
                {"path": "Building.basement_floors", "value": 2, "status": "extracted", "evidence": _evidence("地下2层")},
            ]},
            # chunk 2（heights.txt）：层高
            {"candidates": [], "facts": [
                {"path": "Building.first_floor_height", "value": 4.5, "status": "extracted", "evidence": _evidence("首层4.5m")},
                {"path": "Building.typical_story_height", "value": 3.3, "status": "extracted", "evidence": _evidence("标准层3.3m")},
                {"path": "Building.basement_first_height", "value": 2.7, "status": "extracted", "evidence": _evidence("地下首层层高2.7m")},
            ]},
            {"response": "已根据各段落信息生成标高序列。"},
        ]
    )
    agent = QrestAgent(llm_client=client)
    result = agent.run_turn(files=[floors_file, heights_file])

    write_json(artifact_dir / "normalization" / "elevation_cross_chunk.json", result.to_dict())
    assert len(client.requests) == 5  # intent→plan→extract×2→respond
    assert agent.working_state.get_fact("Building.above_ground_floors").value == 14
    assert agent.working_state.get_fact("Building.typical_story_height").value == 3.3
    elevation = agent.working_state.get("BuildingInfo.Elevation")
    assert elevation is not None
    assert elevation.status == "derived"
    assert elevation.value == [-2.7, 0.0, 4.5, 7.8, 11.1, 14.4, 17.7, 21.0, 24.3, 27.6, 30.9, 34.2, 37.5, 40.8, 44.1, 47.4]
    assert agent.working_state.get("BuildingInfo.ElevationNum").value == 16


def test_elevation_without_story_height_keeps_missing() -> None:
    agent = QrestAgent()
    agent.working_state.set_fact("Building.above_ground_floors", 14, evidence=[StateEvidence(source_id="doc", text="14")])
    agent.working_state.set_fact("Building.basement_floors", 2, evidence=[StateEvidence(source_id="doc", text="2")])
    agent.run_turn("")
    assert agent.working_state.get("BuildingInfo.Elevation") is None


# ---- 方案 §16：Channels 数量 vs 数组 ----

def test_channel_num_only_keeps_channels_missing(artifact_dir: Path) -> None:
    client = ScriptedClient(
        [
            {"intent": "collect_metadata", "skills": [], "need_user_input": False, "reason": ""},
            {"actions": [{"type": "extract"}], "reason": ""},
            {
                "candidates": [
                    {"field_path": "InstrumentInfo.ChannelNum", "value": 18, "status": "extracted",
                     "confidence": 0.9, "evidence": _evidence("系统共布置18个传感器。")}
                ]
            },
            {"response": "已记录通道数量。"},
        ]
    )
    agent = QrestAgent(llm_client=client)
    result = agent.run_turn("系统共布置18个传感器。")

    write_json(artifact_dir / "normalization" / "channel_num_only.json", result.to_dict())
    assert agent.working_state.get("InstrumentInfo.ChannelNum").value == 18
    assert agent.working_state.get("InstrumentInfo.Channels") is None
    assert "Channels" not in agent.to_metadata().get("InstrumentInfo", {})


def test_parameters_correction_recomputes_bbox_without_conflict() -> None:
    """修正 Parameters 后旧 derived BoundingBox 应被确定性重算，而不是变成 conflict。"""
    agent = QrestAgent()
    agent.working_state.set("BuildingInfo.StructuralFootprint.Shape", "Rectangular",
                            evidence=[StateEvidence(source_id="doc", text="rect")])
    agent.working_state.set("BuildingInfo.StructuralFootprint.Parameters", {"Length": 42.0, "Width": 25.2},
                            evidence=[StateEvidence(source_id="doc", text="42x25.2")])
    agent.run_turn("")  # derivation pass: BoundingBox derived
    bbox = agent.working_state.get("BuildingInfo.StructuralFootprint.BoundingBox")
    assert bbox is not None and bbox.status == "derived"
    assert bbox.value["MaxX"] == 21.0

    # 用户修正长度 → Parameters confirmed 46.9
    agent.working_state.confirm("BuildingInfo.StructuralFootprint.Parameters",
                                {"Length": 46.9, "Width": 25.2},
                                evidence=[StateEvidence(source_id="user", text="改为46.9m")])
    agent.run_turn("")  # derivation pass: bbox recomputed

    bbox = agent.working_state.get("BuildingInfo.StructuralFootprint.BoundingBox")
    assert bbox is not None
    assert bbox.status == "derived", "重算结果不应变成 conflict"
    assert bbox.value == {"MaxX": 23.45, "MinX": -23.45, "MaxY": 12.6, "MinY": -12.6}
    # 无冲突
    from qrest_agent.core.validator import validate_state

    assert validate_state(agent.working_state).conflicts == []


def test_derived_to_derived_recompute_overwrites_old_value() -> None:
    """WorkingState 合并：derived→derived 不同值 = 确定性重算覆盖，不产生 alternatives。"""
    state = WorkingState.empty()
    state.derive("BuildingInfo.ElevationNum", 3, derived_from=["BuildingInfo.Elevation"])
    state.derive("BuildingInfo.ElevationNum", 5, derived_from=["BuildingInfo.Elevation"])
    record = state.get("BuildingInfo.ElevationNum")
    assert record.value == 5
    assert record.status == "derived"
    assert record.alternatives == []


def test_inferred_placeholder_does_not_block_deterministic_derivation() -> None:
    """LLM 的 inferred BoundingBox/Elevation 占位不能阻塞 Tool 的确定性推导。"""
    agent = QrestAgent()
    agent.working_state.set("BuildingInfo.StructuralFootprint.Shape", "Rectangular",
                            evidence=[StateEvidence(source_id="doc", text="rect")])
    agent.working_state.set("BuildingInfo.StructuralFootprint.Parameters", {"Length": 42.0, "Width": 25.2},
                            evidence=[StateEvidence(source_id="doc", text="42x25.2")])
    # 模拟 LLM 输出 inferred 占位（不可导出，但 value 非 None）
    agent.working_state.set("BuildingInfo.StructuralFootprint.BoundingBox",
                            {"MaxX": 21.0, "MinX": -21.0, "MaxY": 12.6, "MinY": -12.6},
                            status="inferred", evidence=[StateEvidence(source_id="doc", text="llm guess")])
    agent.run_turn("")

    bbox = agent.working_state.get("BuildingInfo.StructuralFootprint.BoundingBox")
    assert bbox is not None
    assert bbox.status == "derived", "inferred 占位应被确定性推导覆盖"
    assert bbox.evidence[0].tool == "calculate_bounding_box"


def test_facts_never_enter_metadata_or_schema_gate(artifact_dir: Path) -> None:
    """Intermediate Facts 不参与 metadata 导出，也不受 schema gate 约束（但仍需证据）。"""
    agent = QrestAgent()
    agent.working_state.set_fact("Monitoring.monitored_floors", ["B1F", "1", "3"], evidence=[StateEvidence(source_id="doc", text="监测楼层")])
    agent.working_state.set_fact("Building.typical_story_height", 3.3, evidence=[StateEvidence(source_id="doc", text="3.3")])
    result = agent.run_turn("")
    write_json(artifact_dir / "normalization" / "facts_namespace.json", agent.working_state.to_facts_dict())
    metadata = agent.to_metadata()
    assert "Building" not in metadata
    assert "Monitoring" not in metadata
    assert agent.working_state.fact_paths() == ["Building.typical_story_height", "Monitoring.monitored_floors"]
    assert result.rejected_candidates == []
