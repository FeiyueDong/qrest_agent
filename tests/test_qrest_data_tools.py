from __future__ import annotations

from pathlib import Path

from qrest_agent.resources import qrest_examples_root, qrest_tool_path
from qrest_agent.tools.qrest_data_tools import QrestDataTools
from tests.conftest import write_json


def test_bundled_tools_exist(artifact_dir: Path) -> None:
    payload = {
        "data_generator": str(qrest_tool_path("data_generator")),
        "data_loader": str(qrest_tool_path("data_loader")),
    }
    write_json(artifact_dir / "tools" / "bundled_tools.json", payload)

    assert qrest_tool_path("data_generator").exists()
    assert qrest_tool_path("data_loader").exists()


def test_load_qrest_exports_metadata_and_data(tmp_path: Path, artifact_dir: Path) -> None:
    example = qrest_examples_root() / "kunming2" / "kunming2.qrest"
    output_metadata = tmp_path / "metadata.json"
    output_data = tmp_path / "data.txt"

    result = QrestDataTools().load_qrest(example, output_metadata, output_data)

    artifact_metadata = artifact_dir / "tools" / "loaded_metadata.json"
    artifact_data = artifact_dir / "tools" / "loaded_data_head.txt"
    artifact_metadata.write_text(output_metadata.read_text(encoding="utf-8"), encoding="utf-8")
    artifact_data.write_text(
        "\n".join(output_data.read_text(encoding="utf-8").splitlines()[:20]) + "\n",
        encoding="utf-8",
    )
    payload = result.to_dict()
    payload["artifact_outputs"] = {
        "metadata_json": str(artifact_metadata),
        "data_txt_head": str(artifact_data),
    }
    write_json(artifact_dir / "tools" / "load_qrest_result.json", payload)

    assert result.ok, result.to_dict()
    assert output_metadata.exists()
    assert output_data.exists()
    assert output_metadata.stat().st_size > 0
    assert output_data.stat().st_size > 0


def test_generate_qrest_creates_file(tmp_path: Path, artifact_dir: Path) -> None:
    example_dir = qrest_examples_root() / "kunming2"
    output_qrest = tmp_path / "generated.qrest"

    result = QrestDataTools().generate_qrest(
        example_dir / "metadata.json",
        example_dir / "data.txt",
        output_qrest,
    )

    artifact_qrest = artifact_dir / "tools" / "generated.qrest"
    artifact_qrest.write_bytes(output_qrest.read_bytes())
    payload = result.to_dict()
    payload["artifact_outputs"] = {"qrest": str(artifact_qrest)}
    write_json(artifact_dir / "tools" / "generate_qrest_result.json", payload)

    assert result.ok, result.to_dict()
    assert output_qrest.exists()
    assert output_qrest.stat().st_size > 0
