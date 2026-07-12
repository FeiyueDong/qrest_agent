from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from typing import Any

from qrest_agent.agent.metadata_agent import MetadataAgent
from qrest_agent.resources import qrest_examples_root


class BadLLMClient:
    model = "bad"

    def complete_json(self, messages: list[dict[str, str]], schema_hint: dict[str, Any] | None = None) -> dict[str, Any]:
        raise ValueError("bad model output")


class UnknownPathLLMClient:
    model = "unknown-path"

    def complete_json(self, messages: list[dict[str, str]], schema_hint: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "candidates": [
                {
                    "field_path": "TestTower",
                    "value": "wrong",
                    "status": "extracted",
                    "confidence": 0.8,
                    "evidence": ["bad path"],
                }
            ]
        }


class MetadataAgentTests(unittest.TestCase):
    def test_rule_based_turn_reports_missing_fields(self) -> None:
        agent = MetadataAgent()
        result = agent.run_turn("项目名称为 DemoBuilding。采样间隔为 0.02s。")

        self.assertIn("BuildingInfo.ProjectName", [item.field_path for item in result.candidates])
        self.assertFalse(result.report.ready)
        self.assertIn("BuildingInfo.StructuralType", result.report.missing_required)

    def test_bad_llm_falls_back_to_rule_based_extractor(self) -> None:
        agent = MetadataAgent(llm_client=BadLLMClient())
        result = agent.run_turn("项目名称为 DemoBuilding。")

        self.assertIn("BuildingInfo.ProjectName", [item.field_path for item in result.candidates])

    def test_unknown_llm_field_path_falls_back_to_rule_based_extractor(self) -> None:
        agent = MetadataAgent(llm_client=UnknownPathLLMClient())
        result = agent.run_turn("项目名称为 DemoBuilding。")

        self.assertIn("BuildingInfo.ProjectName", [item.field_path for item in result.candidates])
        self.assertNotIn("TestTower", agent.state.records)

    def test_export_artifacts_writes_metadata_and_audit_when_ready(self) -> None:
        agent = MetadataAgent()
        agent.run_turn(files=[qrest_examples_root() / "kunming2" / "metadata.json"])
        with tempfile.TemporaryDirectory() as tempdir:
            metadata_path = Path(tempdir) / "metadata.json"
            audit_path = Path(tempdir) / "audit.json"

            report = agent.export_artifacts(metadata_path, audit_path)

            self.assertTrue(report.ready, report.to_dict())
            self.assertTrue(metadata_path.exists())
            self.assertTrue(audit_path.exists())
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertTrue(audit["ready"])
            self.assertIn("BuildingInfo.ProjectName", audit["records"])

    def test_export_artifacts_writes_only_audit_when_not_ready(self) -> None:
        agent = MetadataAgent()
        agent.run_turn("项目名称为 DemoBuilding。")
        with tempfile.TemporaryDirectory() as tempdir:
            metadata_path = Path(tempdir) / "metadata.json"
            audit_path = Path(tempdir) / "audit.json"

            report = agent.export_artifacts(metadata_path, audit_path)

            self.assertFalse(report.ready)
            self.assertFalse(metadata_path.exists())
            self.assertTrue(audit_path.exists())
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertFalse(audit["ready"])


if __name__ == "__main__":
    unittest.main()
