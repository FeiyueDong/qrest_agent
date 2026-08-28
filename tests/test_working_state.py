from __future__ import annotations

import json
from pathlib import Path

from qrest_agent.agent.agent import QrestAgent
from qrest_agent.agent.prompts import AGENT_SYSTEM_PROMPT
from qrest_agent.core.models import Candidate
from qrest_agent.core.schema import QREST_REQUIRED_PATHS
from qrest_agent.core.validator import validate_state
from qrest_agent.resources import qrest_examples_root
from qrest_agent.state.evidence import Evidence
from qrest_agent.state.working_state import WorkingState
from tests.conftest import write_json


def _evidence(source_id: str = "user_message", text: str = "证据文本") -> list[Evidence]:
    return [Evidence(source_id=source_id, text=text)]


def test_set_and_update_merge_same_value() -> None:
    state = WorkingState()
    state.set("BuildingInfo.ProjectName", "A", evidence=_evidence("doc1"), updated_by="extractor")
    state.update("BuildingInfo.ProjectName", "A", status="confirmed", evidence=_evidence("user"), updated_by="user")

    record = state.get("BuildingInfo.ProjectName")
    assert record is not None
    assert record.status == "confirmed"
    assert record.value == "A"
    assert len(record.evidence) == 2
    assert record.revision == 2


def test_conflicting_extracted_values_mark_conflict() -> None:
    state = WorkingState()
    state.set("BuildingInfo.ProjectName", "A", evidence=_evidence("doc1"))
    state.update("BuildingInfo.ProjectName", "B", evidence=_evidence("doc2"))

    record = state.get("BuildingInfo.ProjectName")
    assert record is not None
    assert record.status == "conflict"
    assert len(record.alternatives) == 1
    assert state.conflicts() == ["BuildingInfo.ProjectName"]


def test_confirmed_value_is_protected_from_later_extraction() -> None:
    state = WorkingState()
    state.confirm("BuildingInfo.ProjectName", "A", _evidence("user"))
    state.update("BuildingInfo.ProjectName", "B", evidence=_evidence("doc1"))

    record = state.get("BuildingInfo.ProjectName")
    assert record is not None
    assert record.value == "A"
    assert record.status == "confirmed"
    assert not record.alternatives


def test_confirm_overrides_extracted_and_keeps_alternative() -> None:
    state = WorkingState()
    state.set("BuildingInfo.ProjectName", "A", evidence=_evidence("doc1"))
    state.confirm("BuildingInfo.ProjectName", "B", _evidence("user"))

    record = state.get("BuildingInfo.ProjectName")
    assert record is not None
    assert record.value == "B"
    assert record.status == "confirmed"
    assert record.alternatives[0].value == "A"


def test_derive_records_source_and_exports() -> None:
    state = WorkingState()
    state.derive(
        "BuildingInfo.ElevationNum",
        16,
        derived_from=["BuildingInfo.Elevation"],
        evidence=_evidence("rule_calculator"),
    )

    record = state.get("BuildingInfo.ElevationNum")
    assert record is not None
    assert record.status == "derived"
    assert record.derived_from == ["BuildingInfo.Elevation"]
    assert state.to_metadata()["BuildingInfo"]["ElevationNum"] == 16


def test_inferred_and_missing_never_export() -> None:
    state = WorkingState()
    state.set("BuildingInfo.StructuralType", "SteelFrame", status="inferred", evidence=_evidence("llm"))
    state.mark_missing("BuildingInfo.ProjectName")

    metadata = state.to_metadata()
    assert "StructuralType" not in metadata.get("BuildingInfo", {})
    assert "ProjectName" not in metadata.get("BuildingInfo", {})


def test_evidence_is_required_for_export_by_default() -> None:
    state = WorkingState()
    state.set("BuildingInfo.ProjectName", "NoEvidence")
    state.set("DataInfo.DT", 0.02, evidence=_evidence("doc1"))

    metadata = state.to_metadata()
    assert "ProjectName" not in metadata.get("BuildingInfo", {})
    assert metadata["DataInfo"]["DT"] == 0.02
    assert state.evidence_gaps() == ["BuildingInfo.ProjectName"]


def test_resolve_conflict_picks_alternative() -> None:
    state = WorkingState()
    state.set("BuildingInfo.ProjectName", "A", evidence=_evidence("doc1"))
    state.update("BuildingInfo.ProjectName", "B", evidence=_evidence("doc2"))
    state.resolve_conflict("BuildingInfo.ProjectName", "alternative", _evidence("user"))

    record = state.get("BuildingInfo.ProjectName")
    assert record is not None
    assert record.status == "confirmed"
    assert record.value == "B"
    assert not state.conflicts()


def test_inferred_candidate_status_is_kept_and_never_exports() -> None:
    state = WorkingState()
    state.submit(
        Candidate(
            field_path="BuildingInfo.StructuralType",
            value="RCFrame",
            status="inferred",
            evidence=_evidence("llm"),
        )
    )

    record = state.get("BuildingInfo.StructuralType")
    assert record is not None
    assert record.status == "inferred"
    assert "StructuralType" not in state.to_metadata().get("BuildingInfo", {})


def test_working_state_validates_like_metadata_state(artifact_dir: Path) -> None:
    metadata = json.loads((qrest_examples_root() / "kunming2" / "metadata.json").read_text(encoding="utf-8"))
    state = WorkingState()
    state.import_metadata(metadata, paths=QREST_REQUIRED_PATHS)

    report = validate_state(state)
    write_json(artifact_dir / "state" / "working_state_ready_report.json", report.to_dict())

    assert report.ready, report.to_dict()


def test_qrest_agent_turn_writes_working_state_and_decides(artifact_dir: Path) -> None:
    agent = QrestAgent()
    result = agent.run_turn("项目名称为 DemoBuilding。采样间隔为 0.02s。")

    write_json(artifact_dir / "agent" / "qrest_agent_phase1_turn.json", result.to_dict())

    project = agent.working_state.get("BuildingInfo.ProjectName")
    dt = agent.working_state.get("DataInfo.DT")
    assert project is not None
    assert project.value == "DemoBuilding"
    assert project.evidence
    assert dt is not None
    assert dt.value == 0.02
    assert result.decision.action == "ask_missing"
    assert "BuildingInfo.Elevation" in result.report.missing_required
    assert not result.report.ready
    assert agent.to_metadata()["DataInfo"]["DT"] == 0.02


def test_agent_system_prompt_documents_decision_authority() -> None:
    prompt = AGENT_SYSTEM_PROMPT
    for phrase in ("决策主体", "Skill", "Tool", "Working State", "Validator", "证据", "不得", "missing"):
        assert phrase in prompt
