from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from qrest_agent.core.models import Candidate, Evidence
from qrest_agent.core.state import MetadataState
from qrest_agent.core.validator import validate_state
from qrest_agent.resources import qrest_examples_root
from tests.conftest import write_json


def test_conflicting_candidates_are_not_silently_overwritten(artifact_dir: Path) -> None:
    state = MetadataState.empty()
    state.submit(Candidate(field_path="BuildingInfo.ProjectName", value="A", confidence=0.9))
    state.submit(Candidate(field_path="BuildingInfo.ProjectName", value="B", confidence=0.9))

    record = state.records["BuildingInfo.ProjectName"]
    report = validate_state(state)
    write_json(artifact_dir / "state" / "conflict_audit.json", state.to_audit_dict())
    write_json(artifact_dir / "state" / "conflict_report.json", report.to_dict())

    assert record.status == "conflict"
    assert "BuildingInfo.ProjectName" in report.conflicts


def test_confirmed_value_overrides_extracted_conflict_candidate(artifact_dir: Path) -> None:
    state = MetadataState.empty()
    state.submit(Candidate(field_path="BuildingInfo.ProjectName", value="A", confidence=0.9))
    state.submit(Candidate(field_path="BuildingInfo.ProjectName", value="B", status="confirmed", confidence=1.0))

    record = state.records["BuildingInfo.ProjectName"]
    write_json(artifact_dir / "state" / "confirmed_override_audit.json", state.to_audit_dict())

    assert record.status == "confirmed"
    assert record.value == "B"


def test_import_export_preserves_extension_fields(artifact_dir: Path) -> None:
    metadata = json.loads((qrest_examples_root() / "kunming2" / "metadata.json").read_text(encoding="utf-8"))
    metadata = deepcopy(metadata)
    metadata["BuildingInfo"]["Owner"] = "ResearchTeam"
    metadata["InstrumentInfo"]["Channels"][0]["DeviceType"] = "S05"
    metadata["CustomRoot"] = {"note": "preserve me"}

    state = MetadataState.from_metadata(metadata)
    exported = state.to_metadata()
    write_json(artifact_dir / "state" / "extension_preserved_metadata.json", exported)

    assert exported["BuildingInfo"]["Owner"] == "ResearchTeam"
    assert exported["InstrumentInfo"]["Channels"][0]["DeviceType"] == "S05"
    assert exported["CustomRoot"]["note"] == "preserve me"


def test_candidate_update_preserves_unrelated_extensions(artifact_dir: Path) -> None:
    metadata = json.loads((qrest_examples_root() / "kunming2" / "metadata.json").read_text(encoding="utf-8"))
    metadata["CustomRoot"] = {"note": "preserve me"}
    state = MetadataState.from_metadata(metadata)

    state.submit(
        Candidate(
            field_path="BuildingInfo.ProjectName",
            value="UpdatedName",
            status="confirmed",
            evidence=[Evidence(source_id="test", text="user update")],
        )
    )
    exported = state.to_metadata()
    write_json(artifact_dir / "state" / "updated_with_extension_metadata.json", exported)

    assert exported["BuildingInfo"]["ProjectName"] == "UpdatedName"
    assert exported["CustomRoot"]["note"] == "preserve me"
