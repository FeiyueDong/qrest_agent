from __future__ import annotations

from pathlib import Path

from qrest_agent.agent.tool_registry import ToolRegistry, validate_tool_arguments
from qrest_agent.resources import qrest_examples_root
from tests.conftest import write_json


def test_lists_qrest_data_tool_specs(artifact_dir: Path) -> None:
    registry = ToolRegistry()
    specs = [spec.to_dict() for spec in registry.list_specs()]
    names = {spec["name"] for spec in specs}
    write_json(artifact_dir / "tools" / "tool_registry_specs.json", specs)

    assert "generate_qrest" in names
    assert "load_qrest" in names
    assert "preflight_generate_qrest" in names


def test_executes_preflight_with_session_artifact(tmp_path: Path, artifact_dir: Path) -> None:
    registry = ToolRegistry(artifact_root=tmp_path / "artifacts")
    example_dir = qrest_examples_root() / "kunming2"

    result = registry.execute(
        "preflight_generate_qrest",
        {
            "session_id": "session-preflight",
            "metadata_json": example_dir / "metadata.json",
            "data_txt": example_dir / "data.txt",
        },
    )
    payload = result.to_dict()
    payload["managed_artifacts"] = registry.artifacts.list("session-preflight")
    write_json(artifact_dir / "tools" / "registry_preflight_result.json", payload)

    assert result.ok
    assert any("DataInfo.NPTS=30000" in warning for warning in result.warnings)
    assert (tmp_path / "artifacts" / "session-preflight" / "generate_qrest_preflight_report.json").exists()


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


def test_executes_tool_with_session_artifacts(tmp_path: Path, artifact_dir: Path) -> None:
    registry = ToolRegistry(artifact_root=tmp_path / "artifacts")

    result = registry.execute(
        "load_qrest",
        {
            "session_id": "session-a",
            "input_qrest": qrest_examples_root() / "kunming2" / "kunming2.qrest",
        },
    )
    payload = result.to_dict()
    payload["managed_artifacts"] = registry.artifacts.list("session-a")
    write_json(artifact_dir / "tools" / "registry_session_artifacts_result.json", payload)

    assert result.ok, result.to_dict()
    assert (tmp_path / "artifacts" / "session-a" / "loaded_metadata.json").exists()
    assert (tmp_path / "artifacts" / "session-a" / "loaded_data.txt").exists()


def test_tool_specs_expose_argument_schemas() -> None:
    registry = ToolRegistry()
    specs = {spec.name: spec for spec in registry.list_specs()}

    frequency = specs["calculate_frequency"]
    assert any(
        arg.name == "dt" and arg.type == "number" and arg.minimum == 0
        for arg in frequency.arguments
    )
    generate = specs["generate_qrest"]
    by_name = {arg.name: arg for arg in generate.arguments}
    assert by_name["metadata_json"].type == "path"
    assert by_name["strict"].type == "boolean"
    assert by_name["strict"].required is False
    # LLM 可见的 schema 表示
    payload = frequency.to_dict()
    assert payload["arguments"][0]["type"] == "number"


def test_tool_argument_validation_rejects_bad_calls() -> None:
    registry = ToolRegistry()

    import pytest

    with pytest.raises(ValueError, match="missing required argument"):
        registry.execute("calculate_frequency", {})
    with pytest.raises(ValueError, match="dt must be a number"):
        registry.execute("calculate_frequency", {"dt": "0.02"})
    with pytest.raises(ValueError, match="dt must be >= 0"):
        registry.execute("calculate_frequency", {"dt": -1})
    with pytest.raises(ValueError, match="metadata must be an object"):
        registry.execute("validate_metadata", {"metadata": []})


def test_tool_argument_validation_accepts_path_like(tmp_path: Path, artifact_dir: Path) -> None:
    registry = ToolRegistry(artifact_root=tmp_path / "artifacts")
    example_dir = qrest_examples_root() / "kunming2"

    # PosixPath 参数应被接受（path 类型支持 PathLike）
    result = registry.execute(
        "preflight_generate_qrest",
        {
            "session_id": "session-pathlike",
            "metadata_json": example_dir / "metadata.json",
            "data_txt": example_dir / "data.txt",
        },
    )
    assert result.ok
