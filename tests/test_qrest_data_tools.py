from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qrest_agent.resources import qrest_examples_root, qrest_tool_path
from qrest_agent.tools.qrest_data_tools import QrestDataTools


class QrestDataToolsTests(unittest.TestCase):
    def test_bundled_tools_exist(self) -> None:
        self.assertTrue(qrest_tool_path("data_generator").exists())
        self.assertTrue(qrest_tool_path("data_loader").exists())

    def test_load_qrest_exports_metadata_and_data(self) -> None:
        example = qrest_examples_root() / "kunming2" / "kunming2.qrest"
        with tempfile.TemporaryDirectory() as tempdir:
            output_metadata = Path(tempdir) / "metadata.json"
            output_data = Path(tempdir) / "data.txt"

            result = QrestDataTools().load_qrest(example, output_metadata, output_data)

            self.assertTrue(result.ok, result.to_dict())
            self.assertTrue(output_metadata.exists())
            self.assertTrue(output_data.exists())
            self.assertGreater(output_metadata.stat().st_size, 0)
            self.assertGreater(output_data.stat().st_size, 0)

    def test_generate_qrest_creates_file(self) -> None:
        example_dir = qrest_examples_root() / "kunming2"
        with tempfile.TemporaryDirectory() as tempdir:
            output_qrest = Path(tempdir) / "generated.qrest"

            result = QrestDataTools().generate_qrest(
                example_dir / "metadata.json",
                example_dir / "data.txt",
                output_qrest,
            )

            self.assertTrue(result.ok, result.to_dict())
            self.assertTrue(output_qrest.exists())
            self.assertGreater(output_qrest.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()

