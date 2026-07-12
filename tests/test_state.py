from __future__ import annotations

import unittest

from qrest_agent.core.models import Candidate
from qrest_agent.core.state import MetadataState
from qrest_agent.core.validator import validate_state


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


if __name__ == "__main__":
    unittest.main()

