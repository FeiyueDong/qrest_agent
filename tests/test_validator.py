from __future__ import annotations

import json
from pathlib import Path

from qrest_agent.core.schema import QREST_EXTENSION_POLICY, QREST_FIELD_SPECS, QREST_REQUIRED_PATHS
from qrest_agent.core.validator import validate_metadata
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
