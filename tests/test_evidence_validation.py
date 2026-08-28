from __future__ import annotations

from pathlib import Path

from qrest_agent.core.exporter import prepare_metadata_export
from qrest_agent.core.models import Candidate
from qrest_agent.core.validator import validate_state
from qrest_agent.state import WorkingState
from qrest_agent.state.evidence import Evidence
from tests.conftest import write_json


def test_required_field_without_evidence_blocks_validation_and_export(artifact_dir: Path) -> None:
    state = WorkingState.empty()
    state.submit(Candidate(field_path="BuildingInfo.ProjectName", value="NoEvidence", status="confirmed"))

    report = validate_state(state)
    export = prepare_metadata_export(state)

    write_json(
        artifact_dir / "validation" / "evidence_gap_report.json",
        {"report": report.to_dict(), "export": export.to_dict()},
    )

    assert not report.ready
    assert "BuildingInfo.ProjectName" in report.evidence_gaps
    assert any(
        issue.level == "error" and "no evidence" in issue.message
        for issue in report.issues
    )
    assert not export.ok
    assert "BuildingInfo.ProjectName" in export.blocked_fields
    assert export.field_annotations["BuildingInfo.ProjectName"] == "blocked"


def test_field_with_evidence_passes_evidence_validation() -> None:
    state = WorkingState.empty()
    state.submit(
        Candidate(
            field_path="BuildingInfo.ProjectName",
            value="WithEvidence",
            status="confirmed",
            evidence=[Evidence(source_id="doc1", text="文档中明确写明")],
        )
    )

    report = validate_state(state)

    assert "BuildingInfo.ProjectName" not in report.evidence_gaps
    assert report.ready or "BuildingInfo.ProjectName" not in [i.field_path for i in report.issues if i.level == "error"]


def test_working_state_evidence_gaps_feed_validator() -> None:
    working = WorkingState()
    working.set("BuildingInfo.ProjectName", "NoEvidence", status="extracted")
    working.set("DataInfo.DT", 0.02, evidence=[Evidence(source_id="doc1")])

    report = validate_state(working)

    assert "BuildingInfo.ProjectName" in report.evidence_gaps
    assert "DataInfo.DT" not in report.evidence_gaps


def test_conflict_issue_reports_alternative_count(artifact_dir: Path) -> None:
    state = WorkingState.empty()
    state.submit(Candidate(field_path="BuildingInfo.ProjectName", value="A", evidence=[Evidence(source_id="doc1")]))
    state.submit(Candidate(field_path="BuildingInfo.ProjectName", value="B", evidence=[Evidence(source_id="doc2")]))

    report = validate_state(state)
    write_json(artifact_dir / "validation" / "conflict_detail.json", report.to_dict())

    conflict_issue = next(issue for issue in report.issues if issue.field_path == "BuildingInfo.ProjectName")
    assert "1 alternatives" in conflict_issue.message


def test_export_annotates_defaulted_and_blank_fields(artifact_dir: Path) -> None:
    state = WorkingState.empty()
    evidence = [Evidence(source_id="test", text="manual")]
    for candidate in [
        Candidate(field_path="BuildingInfo.ElevationNum", value=1, status="confirmed", evidence=evidence),
        Candidate(field_path="BuildingInfo.Elevation", value=[0.0], status="confirmed", evidence=evidence),
        Candidate(field_path="InstrumentInfo.ChannelNum", value=1, status="confirmed", evidence=evidence),
        Candidate(
            field_path="InstrumentInfo.Channels",
            value=[{"ChannelNo": 1, "Azimuth": 90.0, "LocationXYZ": [0.0, 0.0, 0.0]}],
            status="confirmed",
            evidence=evidence,
        ),
        Candidate(field_path="DataInfo.NPTS", value=30000, status="confirmed", evidence=evidence),
        Candidate(field_path="DataInfo.DT", value=0.02, status="confirmed", evidence=evidence),
    ]:
        state.submit(candidate)

    export = prepare_metadata_export(state)
    write_json(artifact_dir / "validation" / "export_annotations.json", export.to_dict())

    annotations = export.field_annotations
    assert annotations["BuildingInfo.StructuralFootprint.Shape"] == "defaulted"
    assert annotations["BuildingInfo.ProjectName"] == "blank"
    assert annotations["DataInfo.DT"] == "evidenced"
    assert annotations["BuildingInfo.Elevation"] == "evidenced"
