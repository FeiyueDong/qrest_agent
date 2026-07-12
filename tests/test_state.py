from __future__ import annotations

import unittest
from copy import deepcopy

from qrest_agent.core.models import Candidate
from qrest_agent.core.state import MetadataState
from qrest_agent.core.validator import validate_state
from qrest_agent.resources import qrest_examples_root
import json


class MetadataStateTests(unittest.TestCase):
    def test_conflicting_candidates_are_not_silently_overwritten(self) -> None:
        state = MetadataState.empty()
        state.submit(Candidate(field_path="BuildingInfo.ProjectName", value="A", confidence=0.9))
        state.submit(Candidate(field_path="BuildingInfo.ProjectName", value="B", confidence=0.9))

        record = state.records["BuildingInfo.ProjectName"]
        report = validate_state(state)

        self.assertEqual(record.status, "conflict")
        self.assertIn("BuildingInfo.ProjectName", report.conflicts)

    def test_confirmed_value_overrides_extracted_conflict_candidate(self) -> None:
        state = MetadataState.empty()
        state.submit(Candidate(field_path="BuildingInfo.ProjectName", value="A", confidence=0.9))
        state.submit(Candidate(field_path="BuildingInfo.ProjectName", value="B", status="confirmed", confidence=1.0))

        record = state.records["BuildingInfo.ProjectName"]

        self.assertEqual(record.status, "confirmed")
        self.assertEqual(record.value, "B")

    def test_import_export_preserves_extension_fields(self) -> None:
        metadata = json.loads((qrest_examples_root() / "kunming2" / "metadata.json").read_text(encoding="utf-8"))
        metadata = deepcopy(metadata)
        metadata["BuildingInfo"]["Owner"] = "ResearchTeam"
        metadata["InstrumentInfo"]["Channels"][0]["DeviceType"] = "S05"
        metadata["CustomRoot"] = {"note": "preserve me"}

        state = MetadataState.from_metadata(metadata)
        exported = state.to_metadata()

        self.assertEqual(exported["BuildingInfo"]["Owner"], "ResearchTeam")
        self.assertEqual(exported["InstrumentInfo"]["Channels"][0]["DeviceType"], "S05")
        self.assertEqual(exported["CustomRoot"]["note"], "preserve me")

    def test_candidate_update_preserves_unrelated_extensions(self) -> None:
        metadata = json.loads((qrest_examples_root() / "kunming2" / "metadata.json").read_text(encoding="utf-8"))
        metadata["CustomRoot"] = {"note": "preserve me"}
        state = MetadataState.from_metadata(metadata)

        state.submit(Candidate(field_path="BuildingInfo.ProjectName", value="UpdatedName", status="confirmed"))
        exported = state.to_metadata()

        self.assertEqual(exported["BuildingInfo"]["ProjectName"], "UpdatedName")
        self.assertEqual(exported["CustomRoot"]["note"], "preserve me")


if __name__ == "__main__":
    unittest.main()
