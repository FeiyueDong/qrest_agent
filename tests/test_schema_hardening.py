from __future__ import annotations

from typing import Any

import pytest

from qrest_agent.agent.agent import QrestAgent
from qrest_agent.core.exporter import prepare_metadata_export
from qrest_agent.core.models import Candidate, Evidence
from qrest_agent.core.schema import QREST_FIELD_SPECS
from qrest_agent.core.schema_gate import SchemaViolation, validate_full, validate_shape
from qrest_agent.core.validator import validate_metadata, validate_state
from qrest_agent.state.evidence import Evidence as StateEvidence
from qrest_agent.state.working_state import FieldState, WorkingState
from tests.conftest import write_json


class ScriptedClient:
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


EVIDENCE = [Evidence(source_id="doc", text="source supports the value")]


def _candidate(field_path: str, value: Any, status: str = "extracted") -> Candidate:
    return Candidate(field_path=field_path, value=value, status=status, evidence=list(EVIDENCE))


# ---- §50：Schema Contract 基础类型测试 ----

def test_schema_contract_basic_type_mismatches_are_all_rejected() -> None:
    """方案 §50：string←integer、integer←array、number←object、array←integer、object←string 全部失败。"""
    cases: list[tuple[str, Any]] = []
    for spec in QREST_FIELD_SPECS:
        if spec.kind == "string":
            cases.append((spec.path, 18))
            cases.append((spec.path, [1]))
            cases.append((spec.path, {"a": 1}))
        elif spec.kind == "integer":
            cases.append((spec.path, [1]))
            cases.append((spec.path, 1.5))
            cases.append((spec.path, "18"))
        elif spec.kind == "number":
            cases.append((spec.path, "0.02"))
            cases.append((spec.path, {"dt": 1}))
        elif spec.kind == "array":
            cases.append((spec.path, 18))
            cases.append((spec.path, "abc"))
        elif spec.kind == "object":
            cases.append((spec.path, 46.9))
            cases.append((spec.path, "46x30"))
            cases.append((spec.path, [1]))

    for field_path, value in cases:
        result = validate_shape(field_path, value)
        assert not result.valid, f"{field_path} = {value!r} 应当被拒绝: {result.errors}"
        assert result.field_path == field_path


def test_schema_contract_valid_shapes_pass() -> None:
    assert validate_shape("InstrumentInfo.ChannelNum", 18).valid
    assert validate_shape("DataInfo.DT", 0.02).valid
    assert validate_shape("BuildingInfo.Elevation", [0.0, 4.5]).valid
    assert validate_shape("BuildingInfo.StructuralFootprint.Parameters", {"Length": 42.0, "Width": 25.2}).valid
    assert validate_shape("Header", "qREST_DATA").valid
    assert not validate_shape("Header", "WRONG").valid


# ---- §51：Channels = 18 永久回归 ----

def test_channels_18_candidate_rejected_and_state_unchanged() -> None:
    state = WorkingState.empty()
    state.set("BuildingInfo.ProjectName", "Demo", evidence=list(EVIDENCE))
    with pytest.raises(SchemaViolation):
        state.submit(_candidate("InstrumentInfo.Channels", 18))
    with pytest.raises(SchemaViolation):
        state.set("InstrumentInfo.Channels", 18)
    with pytest.raises(SchemaViolation):
        state.confirm("InstrumentInfo.Channels", 18, evidence=list(EVIDENCE))
    assert state.get("InstrumentInfo.Channels") is None


def test_channels_18_never_reaches_validator_ready_or_export(artifact_dir) -> None:  # type: ignore[no-untyped-def]
    state = WorkingState.empty()
    state.submit(_candidate("BuildingInfo.ElevationNum", 1))
    state.submit(_candidate("BuildingInfo.Elevation", [0.0]))
    state.submit(_candidate("InstrumentInfo.ChannelNum", 18))
    state.submit(_candidate("DataInfo.NPTS", 30000))
    state.submit(_candidate("DataInfo.DT", 0.02))
    report = validate_state(state)
    export = prepare_metadata_export(state)

    write_json(artifact_dir / "schema" / "channels_18_regression.json", {"report": report.to_dict(), "export": export.to_dict()})
    # 非法值没有进入状态 → 不会以 Channels=18 出现在任何位置
    assert state.get("InstrumentInfo.Channels") is None
    assert "Channels" not in state.to_metadata().get("InstrumentInfo", {})
    # ChannelNum=18 本身合法；缺 Channels 时项目不完整（但这是 missing，不是结构错误）
    assert state.get("InstrumentInfo.ChannelNum") is not None
    assert state.get("InstrumentInfo.ChannelNum").value == 18
    assert not report.ready


# ---- §53-§54：Channels item 类型与 nested required ----

def test_channels_item_type_must_be_object() -> None:
    result = validate_shape("InstrumentInfo.Channels", [1, 2, 3])
    assert not result.valid
    assert any("expected item type object" in error for error in result.errors)


def test_channels_missing_mandatory_keys_reported_by_validator(artifact_dir) -> None:  # type: ignore[no-untyped-def]
    """方案 §54：基本 item type 由 Schema 层保证；完整 mandatory nested field 由 Validator 报告。"""
    state = WorkingState.empty()
    state.submit(_candidate("InstrumentInfo.Channels", [{"ChannelNo": 1}]))
    report = validate_state(state)
    write_json(artifact_dir / "schema" / "channels_missing_keys.json", report.to_dict())
    assert not report.ready
    channel_errors = [issue for issue in report.issues if "Channels" in issue.field_path]
    assert channel_errors, "缺少 channel mandatory key 必须被 Validator 报告"
    # full 检查同样报告
    full = validate_full("InstrumentInfo.Channels", [{"ChannelNo": 1}])
    assert not full.valid
    assert any("missing required key" in error for error in full.errors)


# ---- §55：LocationXYZ ----

def test_location_xyz_wrong_length_or_type_fails_final_validation() -> None:
    bad_channel = {"ChannelNo": 1, "ChannelID": "A1", "Measurand": "acc", "Scale": 1.0, "Azimuth": 90.0, "LocationXYZ": [1, 2]}
    assert not validate_full("InstrumentInfo.Channels", [bad_channel]).valid
    bad_channel2 = {"ChannelNo": 1, "ChannelID": "A1", "Measurand": "acc", "Scale": 1.0, "Azimuth": 90.0, "LocationXYZ": ["x", "y", "z"]}
    assert not validate_full("InstrumentInfo.Channels", [bad_channel2]).valid
    # 合法形状
    good_channel = {"ChannelNo": 1, "ChannelID": "A1", "Measurand": "acc", "Scale": 1.0, "Azimuth": 90.0, "LocationXYZ": [0.0, 0.0, 0.0]}
    assert validate_full("InstrumentInfo.Channels", [good_channel]).valid


# ---- §56-§59：其它字段回归 ----

def test_elevation_16_rejected() -> None:
    assert not validate_shape("BuildingInfo.Elevation", 16).valid
    assert not validate_full("BuildingInfo.Elevation", 16).valid
    state = WorkingState.empty()
    with pytest.raises(SchemaViolation):
        state.set("BuildingInfo.Elevation", 16)


def test_parameters_46_9_rejected() -> None:
    assert not validate_shape("BuildingInfo.StructuralFootprint.Parameters", 46.9).valid
    assert not validate_full("BuildingInfo.StructuralFootprint.Parameters", 46.9).valid


def test_bounding_box_string_rejected() -> None:
    assert not validate_shape("BuildingInfo.StructuralFootprint.BoundingBox", "46x30").valid
    assert not validate_full("BuildingInfo.StructuralFootprint.BoundingBox", "46x30").valid


def test_dt_and_npts_wrong_shapes_rejected() -> None:
    assert not validate_shape("DataInfo.DT", [0.02]).valid
    assert not validate_shape("DataInfo.NPTS", "many").valid
    state = WorkingState.empty()
    with pytest.raises(SchemaViolation):
        state.set("DataInfo.DT", [0.02])
    with pytest.raises(SchemaViolation):
        state.set("DataInfo.NPTS", "many")


# ---- §60：Import 不能绕过 Schema ----

def test_import_metadata_with_invalid_channels_reports_schema_error(artifact_dir) -> None:  # type: ignore[no-untyped-def]
    metadata = {
        "Header": "qREST_DATA",
        "Version": [1, 0, 0],
        "Units": ["m", "s"],
        "InstrumentInfo": {"Channels": 18, "ChannelNum": 18},
        "DataInfo": {"NPTS": 30000, "DT": 0.02},
    }
    report = validate_metadata(metadata)
    write_json(artifact_dir / "schema" / "import_invalid_channels.json", report.to_dict())
    schema_issues = [issue for issue in report.issues if issue.field_path == "InstrumentInfo.Channels"]
    assert schema_issues, "导入 Channels=18 必须产生 schema error"
    assert any("expected array" in issue.message for issue in schema_issues)
    assert not report.ready


def test_import_metadata_rejects_other_invalid_shapes() -> None:
    metadata = {
        "Header": "qREST_DATA",
        "Version": [1, 0, 0],
        "Units": ["m", "s"],
        "BuildingInfo": {"Elevation": 16, "StructuralFootprint": {"Parameters": 46.9}},
    }
    report = validate_metadata(metadata)
    assert any(issue.field_path == "BuildingInfo.Elevation" and issue.level == "error" for issue in report.issues)
    assert any(issue.field_path == "BuildingInfo.StructuralFootprint.Parameters" and issue.level == "error" for issue in report.issues)


# ---- §61：Tool / deterministic 写入不能绕过 Schema ----

def test_derive_and_update_cannot_write_invalid_shape() -> None:
    state = WorkingState.empty()
    with pytest.raises(SchemaViolation):
        state.derive("InstrumentInfo.Channels", 18, derived_from=["InstrumentInfo.ChannelNum"])
    with pytest.raises(SchemaViolation):
        state.update("InstrumentInfo.Channels", 18)


# ---- §62：用户确认不能绕过 Schema ----

def test_user_confirmation_cannot_bypass_schema() -> None:
    state = WorkingState.empty()
    with pytest.raises(SchemaViolation):
        state.confirm("InstrumentInfo.Channels", 18, evidence=list(EVIDENCE))
    assert state.get("InstrumentInfo.Channels") is None


# ---- §63：Export Final Gate（人为构造非法状态）----

def test_export_final_gate_blocks_invalid_state(artifact_dir) -> None:  # type: ignore[no-untyped-def]
    state = WorkingState.empty()
    # 人为绕过写入门，模拟程序 bug：直接塞入非法 FieldState
    state._fields["InstrumentInfo.Channels"] = FieldState(
        field_path="InstrumentInfo.Channels",
        value=18,
        status="confirmed",
        confidence=1.0,
        evidence=[StateEvidence(source_id="bug", text="simulated internal bug")],
    )
    export = prepare_metadata_export(state)
    write_json(artifact_dir / "schema" / "export_final_gate.json", export.to_dict())
    assert not export.ok
    assert "InstrumentInfo.Channels" in export.blocked_fields
    # 非法结构在 validate_state 阶段即被 Schema 层拦截（final gate 是兜底安全网）
    schema_issues = [issue for issue in export.report.issues if issue.field_path == "InstrumentInfo.Channels"]
    assert schema_issues
    assert any("expected array" in issue.message for issue in schema_issues)
    # final gate 本身：对导出前的最终 metadata 再做一次形状校验（防御未来 validator 被绕过）
    from qrest_agent.core.schema_gate import validate_shape

    assert not validate_shape("InstrumentInfo.Channels", state.to_metadata().get("InstrumentInfo", {}).get("Channels")).valid


# ---- §85：LLM 输出 Channels=18 全链路（agent 层）----

def test_agent_rejects_llm_channels_18_and_reports_diagnostic(artifact_dir) -> None:  # type: ignore[no-untyped-def]
    client = ScriptedClient(
        [
            {"intent": "collect_metadata", "skills": [], "need_user_input": False, "reason": ""},
            {"actions": [{"type": "extract"}], "reason": ""},
            {
                "candidates": [
                    {
                        "field_path": "InstrumentInfo.Channels",
                        "value": 18,
                        "status": "extracted",
                        "confidence": 0.99,
                        "evidence": [{"source_id": "user_message", "text": "系统共布置18个传感器"}],
                    }
                ]
            },
            {"response": "已记录。"},
        ]
    )
    agent = QrestAgent(llm_client=client)
    result = agent.run_turn("系统共布置18个传感器")

    write_json(artifact_dir / "schema" / "agent_llm_channels_18.json", result.to_dict())
    assert result.rejected_candidates, "Channels=18 必须进入 rejected_candidates"
    assert result.rejected_candidates[0]["field_path"] == "InstrumentInfo.Channels"
    assert "expected array" in result.rejected_candidates[0]["reason"]
    assert agent.working_state.get("InstrumentInfo.Channels") is None
    # 高 confidence 不能绕过（§42）
    assert result.rejected_candidates[0].get("rejected") is True


def test_dialogue_confirm_command_rejects_invalid_shape() -> None:
    """方案 §62：CLI /confirm 对结构非法值也必须失败（confirmed 不绕过 Schema）。"""
    from qrest_agent.agent.dialogue import ChatSession

    session = ChatSession()
    result = session.handle("/confirm InstrumentInfo.Channels 18")
    assert "结构校验拒绝" in result.response
    assert session.agent.working_state.get("InstrumentInfo.Channels") is None


def test_agent_accepts_channel_num_18() -> None:
    client = ScriptedClient(
        [
            {"intent": "collect_metadata", "skills": [], "need_user_input": False, "reason": ""},
            {"actions": [{"type": "extract"}], "reason": ""},
            {
                "candidates": [
                    {
                        "field_path": "InstrumentInfo.ChannelNum",
                        "value": 18,
                        "status": "extracted",
                        "confidence": 0.9,
                        "evidence": [{"source_id": "user_message", "text": "系统共布置18个传感器"}],
                    }
                ]
            },
            {"response": "已记录 18 个通道。"},
        ]
    )
    agent = QrestAgent(llm_client=client)
    result = agent.run_turn("系统共布置18个传感器")

    assert not result.rejected_candidates
    record = agent.working_state.get("InstrumentInfo.ChannelNum")
    assert record is not None
    assert record.value == 18
    assert record.status == "extracted"
