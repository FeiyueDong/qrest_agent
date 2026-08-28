from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from qrest_agent.core.validator import validate_metadata
from qrest_agent.ingestion.sources import SourceManager
from qrest_agent.storage.artifacts import ArtifactManager
from qrest_agent.tools.metadata_calculator import (
    calculate_bounding_box,
    calculate_frequency,
    derive_channel_num,
    derive_elevation_num,
    derive_elevation_profile,
    normalize_azimuth,
    parse_channel_table,
)
from qrest_agent.tools.qrest_data_tools import QrestDataTools


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    """Agent 可调用的确定性工具集合。

    工具只做“输入明确、输出明确、行为确定”的事情（读文档、计算、校验、qREST 转换），
    不承担整体决策（方案 §6）。
    """

    def __init__(self, artifact_root: str | Path | None = None) -> None:
        self._qrest_tools = QrestDataTools()
        self.artifacts = ArtifactManager(artifact_root)
        self._tools: dict[str, tuple[ToolSpec, Callable[..., Any]]] = {
            "read_document": (
                ToolSpec(
                    name="read_document",
                    description="Read a supported document (pdf/docx/xlsx/csv/txt/json) into structured text chunks.",
                    parameters={
                        "path": "Path to the input document.",
                        "session_id": "Optional session id (ignored by this tool).",
                    },
                ),
                _read_document_tool,
            ),
            "calculate_frequency": (
                ToolSpec(
                    name="calculate_frequency",
                    description="Calculate sampling frequency from sampling interval: Frequency = 1 / DT.",
                    parameters={"dt": "Sampling interval in time units (must be positive)."},
                ),
                _frequency_tool,
            ),
            "calculate_bounding_box": (
                ToolSpec(
                    name="calculate_bounding_box",
                    description="Calculate the footprint bounding box centered at the geometric origin for a rectangular building.",
                    parameters={
                        "length": "Building footprint length along X.",
                        "width": "Building footprint width along Y.",
                    },
                ),
                _bounding_box_tool,
            ),
            "normalize_azimuth": (
                ToolSpec(
                    name="normalize_azimuth",
                    description="Normalize an azimuth to [0, 360); -1 (vertical) is preserved.",
                    parameters={"azimuth": "Azimuth in degrees, or -1 for vertical channels."},
                ),
                _azimuth_tool,
            ),
            "derive_elevation_profile": (
                ToolSpec(
                    name="derive_elevation_profile",
                    description="Derive the absolute elevation list from floor counts and story heights.",
                    parameters={
                        "above_ground_floors": "Number of above-ground floors.",
                        "basement_floors": "Number of basement floors.",
                        "first_floor_height": "Height of the first above-ground floor.",
                        "typical_above_height": "Typical above-ground story height.",
                        "basement_first_height": "Optional height of the first basement floor.",
                        "basement_second_height": "Optional height of the second basement floor.",
                    },
                ),
                _elevation_profile_tool,
            ),

            "derive_counts": (
                ToolSpec(
                    name="derive_counts",
                    description="Derive ElevationNum from Elevation array length and ChannelNum from Channels array length.",
                    parameters={
                        "elevations": "Optional Elevation array.",
                        "channels": "Optional Channels array.",
                    },
                ),
                _counts_tool,
            ),
            "table_reader": (
                ToolSpec(
                    name="table_reader",
                    description="Parse a channel configuration table (first row is the header) into a Channels list.",
                    parameters={
                        "rows": "List of table rows as strings.",
                        "delimiter": "Optional column delimiter; defaults to comma.",
                    },
                ),
                _table_reader_tool,
            ),
            "metadata_writer": (
                ToolSpec(
                    name="metadata_writer",
                    description="Write a qREST metadata object to a JSON file and return the output path.",
                    parameters={
                        "metadata": "qREST metadata dict.",
                        "output_path": "Path where metadata JSON should be written.",
                    },
                ),
                _metadata_writer_tool,
            ),
            "validate_metadata": (
                ToolSpec(
                    name="validate_metadata",
                    description="Validate a qREST metadata object and return the deterministic validation report.",
                    parameters={"metadata": "qREST metadata dict."},
                ),
                _validate_metadata_tool,
            ),
            "preflight_generate_qrest": (
                ToolSpec(
                    name="preflight_generate_qrest",
                    description="Check whether qREST metadata JSON and time-series TXT data are ready for .qrest generation.",
                    parameters={
                        "metadata_json": "Path to qREST metadata JSON.",
                        "data_txt": "Path to time-major text data.",
                        "session_id": "Optional session id for managed preflight report output.",
                    },
                ),
                self._qrest_tools.preflight_generate_qrest,
            ),
            "generate_qrest": (
                ToolSpec(
                    name="generate_qrest",
                    description="Generate a binary .qrest file from qREST metadata JSON and time-series TXT data.",
                    parameters={
                        "metadata_json": "Path to qREST metadata JSON.",
                        "data_txt": "Path to time-major text data.",
                        "output_qrest": "Path where the generated .qrest file should be written. Optional when session_id is supplied.",
                        "strict": "Optional bool. Treat preflight warnings as blocking errors when true.",
                        "session_id": "Optional session id for managed artifact output.",
                    },
                ),
                self._qrest_tools.generate_qrest,
            ),
            "load_qrest": (
                ToolSpec(
                    name="load_qrest",
                    description="Extract qREST metadata JSON and readable TXT data from a binary .qrest file.",
                    parameters={
                        "input_qrest": "Path to the input .qrest file.",
                        "output_metadata_json": "Path where metadata JSON should be written. Optional when session_id is supplied.",
                        "output_data_txt": "Path where readable data TXT should be written. Optional when session_id is supplied.",
                        "compare_metadata_json": "Optional metadata JSON path to compare against loaded metadata.",
                        "session_id": "Optional session id for managed artifact output.",
                    },
                ),
                self._qrest_tools.load_qrest,
            ),
        }

    def list_specs(self) -> list[ToolSpec]:
        return [spec for spec, _ in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        _, function = self._tools[name]
        session_id = arguments.get("session_id")
        prepared = self._prepare_arguments(name, dict(arguments))
        result = function(**prepared)
        if session_id is not None:
            self._write_tool_artifacts(str(session_id), name, result)
        return result

    def _prepare_arguments(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        session_id = arguments.pop("session_id", None)
        if session_id is None:
            return arguments

        if name == "generate_qrest":
            arguments.setdefault("output_qrest", self.artifacts.path(str(session_id), "generated.qrest"))
        elif name == "load_qrest":
            arguments.setdefault("output_metadata_json", self.artifacts.path(str(session_id), "loaded_metadata.json"))
            arguments.setdefault("output_data_txt", self.artifacts.path(str(session_id), "loaded_data.txt"))
        return arguments

    def _write_tool_artifacts(self, session_id: str, name: str, result: Any) -> None:
        if name == "preflight_generate_qrest":
            preflight = result.summary.get("preflight", {}) if hasattr(result, "summary") else {}
            self.artifacts.write_json(session_id, "generate_qrest_preflight_report.json", preflight)
        elif name == "generate_qrest":
            payload = result.to_dict() if hasattr(result, "to_dict") else {"result": result}
            self.artifacts.write_json(session_id, "generate_qrest_result.json", payload)
            preflight = result.summary.get("preflight", {}) if hasattr(result, "summary") else {}
            if preflight:
                self.artifacts.write_json(session_id, "generate_qrest_preflight_report.json", preflight)
        elif name == "load_qrest":
            payload = result.to_dict() if hasattr(result, "to_dict") else {"result": result}
            self.artifacts.write_json(session_id, "load_qrest_result.json", payload)


def _read_document_tool(path: str) -> dict[str, Any]:
    chunks = SourceManager().add_file(path)
    return {
        "path": str(path),
        "chunk_count": len(chunks),
        "chunks": [chunk.to_dict() for chunk in chunks],
    }


def _frequency_tool(dt: float) -> dict[str, Any]:
    return {"dt": dt, "frequency": calculate_frequency(dt)}


def _bounding_box_tool(length: float, width: float) -> dict[str, Any]:
    return {"bounding_box": calculate_bounding_box(length, width)}


def _azimuth_tool(azimuth: float) -> dict[str, Any]:
    return {"azimuth": normalize_azimuth(azimuth)}


def _elevation_profile_tool(
    above_ground_floors: int,
    basement_floors: int,
    first_floor_height: float,
    typical_above_height: float,
    basement_first_height: float | None = None,
    basement_second_height: float | None = None,
) -> dict[str, Any]:
    profile = derive_elevation_profile(
        above_ground_floors=above_ground_floors,
        basement_floors=basement_floors,
        first_floor_height=first_floor_height,
        typical_above_height=typical_above_height,
        basement_first_height=basement_first_height,
        basement_second_height=basement_second_height,
    )
    return {
        "profile": profile.to_dict(),
        "elevations": profile.elevations,
        "elevation_num": len(profile.elevations),
    }


def _table_reader_tool(rows: list[str], delimiter: str = ",") -> dict[str, Any]:
    channels = parse_channel_table(rows, delimiter=delimiter)
    return {"channels": channels, "channel_num": len(channels)}


def _metadata_writer_tool(metadata: dict[str, Any], output_path: str) -> dict[str, Any]:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(path)}


def _counts_tool(elevations: list[Any] | None = None, channels: list[Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if elevations is not None:
        result["ElevationNum"] = derive_elevation_num(elevations)
    if channels is not None:
        result["ChannelNum"] = derive_channel_num(channels)
    return result


def _validate_metadata_tool(metadata: dict[str, Any]) -> dict[str, Any]:
    return validate_metadata(metadata).to_dict()
