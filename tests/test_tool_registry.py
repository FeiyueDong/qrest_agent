from __future__ import annotations

from pathlib import Path

from qrest_agent.agent.tool_registry import ToolRegistry
from qrest_agent.resources import qrest_examples_root
from tests.conftest import write_json


def test_lists_qrest_data_tool_specs(artifact_dir: Path) -> None:
    registry = ToolRegistry()
    specs = [spec.to_dict() for spec in registry.list_specs()]
    names = {spec["name"] for spec in specs}
    write_json(artifact_dir / "tools" / "tool_registry_specs.json", specs)

    assert "generate_qrest" in names
    assert "load_qrest" in names


def test_executes_load_qrest(tmp_path: Path, artifact_dir: Path) -> None:
    registry = ToolRegistry()
    result = registry.execute(
        "load_qrest",
        {
            "input_qrest": qrest_examples_root() / "kunming2" / "kunming2.qrest",
            "output_metadata_json": tmp_path / "metadata.json",
            "output_data_txt": tmp_path / "data.txt",
        },
    )
    payload = result.to_dict()
    payload["artifact_outputs"] = {
        "metadata_json": str(tmp_path / "metadata.json"),
        "data_txt": str(tmp_path / "data.txt"),
    }
    write_json(artifact_dir / "tools" / "registry_load_qrest_result.json", payload)

    assert result.ok, result.to_dict()
