from __future__ import annotations

import unittest

from qrest_agent.agent.metadata_agent import MetadataAgent


class MetadataAgentTests(unittest.TestCase):
    def test_rule_based_turn_reports_missing_fields(self) -> None:
        agent = MetadataAgent()
        result = agent.run_turn("项目名称为 DemoBuilding。采样间隔为 0.02s。")

        self.assertIn("BuildingInfo.ProjectName", [item.field_path for item in result.candidates])
        self.assertFalse(result.report.ready)
        self.assertIn("BuildingInfo.StructuralType", result.report.missing_required)


if __name__ == "__main__":
    unittest.main()

