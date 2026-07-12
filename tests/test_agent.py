from __future__ import annotations

import unittest
from typing import Any

from qrest_agent.agent.metadata_agent import MetadataAgent


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


if __name__ == "__main__":
    unittest.main()
