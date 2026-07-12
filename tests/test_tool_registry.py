from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qrest_agent.agent.tool_registry import ToolRegistry
from qrest_agent.resources import qrest_examples_root


class ToolRegistryTests(unittest.TestCase):
    def test_lists_qrest_data_tool_specs(self) -> None:
        registry = ToolRegistry()
        names = {spec.name for spec in registry.list_specs()}

        self.assertIn("generate_qrest", names)
        self.assertIn("load_qrest", names)

    def test_executes_load_qrest(self) -> None:
        registry = ToolRegistry()
        with tempfile.TemporaryDirectory() as tempdir:
            result = registry.execute(
                "load_qrest",
                {
                    "input_qrest": qrest_examples_root() / "kunming2" / "kunming2.qrest",
                    "output_metadata_json": Path(tempdir) / "metadata.json",
                    "output_data_txt": Path(tempdir) / "data.txt",
                },
            )

            self.assertTrue(result.ok, result.to_dict())


if __name__ == "__main__":
    unittest.main()

