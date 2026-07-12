from __future__ import annotations

import json
import unittest
from pathlib import Path

from qrest_agent.core.validator import validate_metadata


class ValidatorTests(unittest.TestCase):
    def test_qrest_sample_metadata_is_ready(self) -> None:
        path = Path("/home/yue/CodeFiles/qrest_data/resource/kunming2/metadata.json")
        metadata = json.loads(path.read_text(encoding="utf-8"))

        report = validate_metadata(metadata)

        self.assertTrue(report.ready, report.to_dict())

    def test_missing_required_field_is_reported(self) -> None:
        metadata = json.loads(Path("/home/yue/CodeFiles/qrest_data/resource/kunming2/metadata.json").read_text(encoding="utf-8"))
        del metadata["DataInfo"]["DT"]

        report = validate_metadata(metadata)

        self.assertFalse(report.ready)
        self.assertIn("DataInfo.DT", report.missing_required)

    def test_truncated_sample_reports_channel_count_mismatch(self) -> None:
        metadata = json.loads(Path("/home/yue/CodeFiles/qrest_data/resource/metadata.json").read_text(encoding="utf-8"))

        report = validate_metadata(metadata)

        self.assertFalse(report.ready)
        self.assertTrue(
            any(issue.field_path == "InstrumentInfo.ChannelNum" for issue in report.issues),
            report.to_dict(),
        )


if __name__ == "__main__":
    unittest.main()
