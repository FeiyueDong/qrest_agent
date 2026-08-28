from __future__ import annotations

import json
from pathlib import Path

from qrest_agent.core.exporter import prepare_metadata_export
from qrest_agent.core.metadata_policy import channel_key_importance, field_policy
from qrest_agent.core.models import Candidate, Evidence
from qrest_agent.core.path import get_path
from qrest_agent.core.schema import QREST_EXTENSION_POLICY, QREST_FIELD_SPECS, QREST_REQUIRED_PATHS
from qrest_agent.core.validator import validate_metadata
from qrest_agent.state import WorkingState
from qrest_agent.resources import qrest_examples_root, qrest_schema_path
from tests.conftest import write_json


def test_qrest_sample_metadata_is_ready(artifact_dir: Path) -> None:
    path = qrest_examples_root() / "kunming2" / "metadata.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))

    report = validate_metadata(metadata)
    write_json(artifact_dir / "validation" / "kunming2_ready_report.json", report.to_dict())

    assert report.ready, report.to_dict()


def test_missing_required_field_is_reported(artifact_dir: Path) -> None:
    metadata = json.loads((qrest_examples_root() / "kunming2" / "metadata.json").read_text(encoding="utf-8"))
    del metadata["DataInfo"]["DT"]

    report = validate_metadata(metadata)
    write_json(artifact_dir / "validation" / "missing_dt_report.json", report.to_dict())

    assert not report.ready
    assert "DataInfo.DT" in report.missing_required


def test_truncated_sample_reports_channel_count_mismatch(artifact_dir: Path) -> None:
    metadata = json.loads((qrest_examples_root() / "kunming2" / "metadata.json").read_text(encoding="utf-8"))
    metadata["InstrumentInfo"]["Channels"] = metadata["InstrumentInfo"]["Channels"][:3]

    report = validate_metadata(metadata)
    write_json(artifact_dir / "validation" / "channel_mismatch_report.json", report.to_dict())

    assert not report.ready
    assert any(issue.field_path == "InstrumentInfo.ChannelNum" for issue in report.issues), report.to_dict()


def test_formal_schema_resource_exists_and_matches_required_paths(artifact_dir: Path) -> None:
    schema = json.loads(qrest_schema_path().read_text(encoding="utf-8"))
    write_json(
        artifact_dir / "validation" / "schema_summary.json",
        {
            "schema_path": str(qrest_schema_path()),
            "root_required": schema["required"],
            "required_paths": QREST_REQUIRED_PATHS,
            "extension_policy": QREST_EXTENSION_POLICY,
        },
    )

    assert schema["properties"]["Header"]["const"] == "qREST_DATA"
    assert "additionalProperties" in schema
    assert "BuildingInfo.ProjectName" in QREST_REQUIRED_PATHS
    assert len(QREST_FIELD_SPECS) == len(QREST_REQUIRED_PATHS)
    assert "Unknown fields are preserved" in QREST_EXTENSION_POLICY


def test_metadata_policy_is_loaded_from_annotated_example(artifact_dir: Path) -> None:
    payload = {
        "Header": field_policy("Header").importance,
        "Units": field_policy("Units").importance,
        "ProjectName": field_policy("BuildingInfo.ProjectName").importance,
        "StructuralFootprint.Shape": field_policy("BuildingInfo.StructuralFootprint.Shape").importance,
        "DataInfo.DT": field_policy("DataInfo.DT").importance,
        "ChannelID": channel_key_importance("ChannelID"),
        "Measurand": channel_key_importance("Measurand"),
        "LocationXYZ": channel_key_importance("LocationXYZ"),
    }
    write_json(artifact_dir / "validation" / "metadata_policy_summary.json", payload)

    assert payload["Header"] == "important"
    assert payload["Units"] == "mandatory"
    assert payload["ProjectName"] == "optional"
    assert payload["StructuralFootprint.Shape"] == "important"
    assert payload["DataInfo.DT"] == "mandatory"
    assert payload["ChannelID"] == "optional"
    assert payload["Measurand"] == "important"
    assert payload["LocationXYZ"] == "mandatory"


def test_export_allows_defaults_for_important_and_blanks_for_optional_fields(artifact_dir: Path) -> None:
    state = WorkingState.empty()
    evidence = [Evidence(source_id="test", text="manual candidate")]
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

    report = validate_metadata(state.to_metadata())
    export = prepare_metadata_export(state)
    write_json(artifact_dir / "validation" / "weighted_missing_report.json", report.to_dict())
    write_json(artifact_dir / "validation" / "weighted_export_result.json", export.to_dict(include_metadata=True))

    assert report.ready
    assert "BuildingInfo.StructuralFootprint.Shape" in report.missing_important
    assert "InstrumentInfo.Channels[0].Measurand" in report.missing_important
    assert "BuildingInfo.ProjectName" in report.missing_optional
    assert "InstrumentInfo.Channels[0].ChannelID" in report.missing_optional
    assert export.ok
    assert export.metadata is not None
    assert get_path(export.metadata, "BuildingInfo.StructuralFootprint.Shape") == "Rectangular"
    assert get_path(export.metadata, "BuildingInfo.ProjectName") is None
    channel = export.metadata["InstrumentInfo"]["Channels"][0]
    assert channel["Measurand"] == "Acceleration"
    assert channel["Scale"] == 1
    assert channel["ChannelID"] is None


def test_export_blocks_when_mandatory_fields_are_missing(artifact_dir: Path) -> None:
    state = WorkingState.empty()

    export = prepare_metadata_export(state)
    write_json(artifact_dir / "validation" / "weighted_export_blocked.json", export.to_dict())

    assert not export.ok
    assert "BuildingInfo.Elevation" in export.blocked_fields
