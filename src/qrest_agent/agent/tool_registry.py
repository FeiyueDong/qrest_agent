from __future__ import annotations

import json
from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Callable, Literal

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

ArgumentType = Literal["string", "integer", "number", "boolean", "array", "object", "path"]


@dataclass(frozen=True, slots=True)
class ArgumentSpec:
    """工具参数的机器可读 Schema（设计文档 §21）。"""

    name: str
    type: ArgumentType
    description: str = ""
    required: bool = True
    minimum: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "required": self.required,
        }
        if self.minimum is not None:
            payload["minimum"] = self.minimum
        return payload


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    arguments: list[ArgumentSpec] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "arguments": [argument.to_dict() for argument in self.arguments],
        }


def _arg(
    name: str,
    type_: ArgumentType,
    description: str = "",
    required: bool = True,
    minimum: float | None = None,
) -> ArgumentSpec:
    return ArgumentSpec(name=name, type=type_, description=description, required=required, minimum=minimum)


def validate_tool_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> list[str]:
    """参数 Schema 校验（设计文档 §21：Tool Registry 校验参数后再执行）。"""
    errors: list[str] = []
    for argument in spec.arguments:
        value = arguments.get(argument.name)
        if value is None:
            if argument.required:
                errors.append(f"missing required argument: {argument.name}")
            continue

        if argument.type == "string" and not isinstance(value, str):
            errors.append(f"{argument.name} must be a string")
        elif argument.type == "path" and not isinstance(value, (str, os.PathLike)):
            errors.append(f"{argument.name} must be a path")
        elif argument.type == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            errors.append(f"{argument.name} must be an integer")
        elif argument.type == "number" and (isinstance(value, bool) or not isinstance(value, int | float)):
            errors.append(f"{argument.name} must be a number")
        elif argument.type == "boolean" and not isinstance(value, bool):
            errors.append(f"{argument.name} must be a boolean")
        elif argument.type == "array" and not isinstance(value, list):
            errors.append(f"{argument.name} must be an array")
        elif argument.type == "object" and not isinstance(value, dict):
            errors.append(f"{argument.name} must be an object")

        if (
            isinstance(value, int | float)
            and not isinstance(value, bool)
            and argument.minimum is not None
            and value < argument.minimum
        ):
            errors.append(f"{argument.name} must be >= {argument.minimum}")
    return errors


class ToolRegistry:
    """Agent 可调用的确定性工具集合（设计文档 §6/§21）。

    工具只做“输入明确、输出明确、行为确定”的事情；所有调用经过本 Registry：
    校验工具名 → 校验参数 Schema → 执行 → 捕获异常 → 返回结构化结果。
    """

    def __init__(self, artifact_root: str | Path | None = None) -> None:
        self._qrest_tools = QrestDataTools()
        self.artifacts = ArtifactManager(artifact_root)
        self._tools: dict[str, tuple[ToolSpec, Callable[..., Any]]] = {
            "read_document": (
                ToolSpec(
                    name="read_document",
                    description="Read a supported document (pdf/docx/xlsx/csv/txt/json) into structured text chunks.",
                    arguments=[
                        _arg("path", "path", "Path to the input document."),
                        _arg("session_id", "string", "Optional session id (ignored by this tool).", required=False),
                    ],
                ),
                _read_document_tool,
            ),
            "calculate_frequency": (
                ToolSpec(
                    name="calculate_frequency",
                    description="Calculate sampling frequency from sampling interval: Frequency = 1 / DT.",
                    arguments=[_arg("dt", "number", "Sampling interval in time units (must be positive).", minimum=0)],
                ),
                _frequency_tool,
            ),
            "calculate_bounding_box": (
                ToolSpec(
                    name="calculate_bounding_box",
                    description="Calculate the footprint bounding box centered at the geometric origin for a rectangular building.",
                    arguments=[
                        _arg("length", "number", "Building footprint length along X."),
                        _arg("width", "number", "Building footprint width along Y."),
                    ],
                ),
                _bounding_box_tool,
            ),
            "normalize_azimuth": (
                ToolSpec(
                    name="normalize_azimuth",
                    description="Normalize an azimuth to [0, 360); -1 (vertical) is preserved.",
                    arguments=[_arg("azimuth", "number", "Azimuth in degrees, or -1 for vertical channels.")],
                ),
                _azimuth_tool,
            ),
            "derive_elevation_profile": (
                ToolSpec(
                    name="derive_elevation_profile",
                    description="Derive the absolute elevation list from floor counts and story heights.",
                    arguments=[
                        _arg("above_ground_floors", "integer", "Number of above-ground floors."),
                        _arg("basement_floors", "integer", "Number of basement floors."),
                        _arg("first_floor_height", "number", "Height of the first above-ground floor."),
                        _arg("typical_above_height", "number", "Typical above-ground story height."),
                        _arg("basement_first_height", "number", "Optional height of the first basement floor.", required=False),
                        _arg("basement_second_height", "number", "Optional height of the second basement floor.", required=False),
                    ],
                ),
                _elevation_profile_tool,
            ),
            "derive_counts": (
                ToolSpec(
                    name="derive_counts",
                    description="Derive ElevationNum from Elevation array length and ChannelNum from Channels array length.",
                    arguments=[
                        _arg("elevations", "array", "Optional Elevation array.", required=False),
                        _arg("channels", "array", "Optional Channels array.", required=False),
                    ],
                ),
                _counts_tool,
            ),
            "table_reader": (
                ToolSpec(
                    name="table_reader",
                    description="Parse a channel configuration table (first row is the header) into a Channels list.",
                    arguments=[
                        _arg("rows", "array", "List of table rows as strings."),
                        _arg("delimiter", "string", "Optional column delimiter; defaults to comma.", required=False),
                    ],
                ),
                _table_reader_tool,
            ),
            "metadata_writer": (
                ToolSpec(
                    name="metadata_writer",
                    description="Write a qREST metadata object to a JSON file and return the output path.",
                    arguments=[
                        _arg("metadata", "object", "qREST metadata dict."),
                        _arg("output_path", "path", "Path where metadata JSON should be written."),
                    ],
                ),
                _metadata_writer_tool,
            ),
            "validate_metadata": (
                ToolSpec(
                    name="validate_metadata",
                    description="Validate a qREST metadata object and return the deterministic validation report.",
                    arguments=[_arg("metadata", "object", "qREST metadata dict.")],
                ),
                _validate_metadata_tool,
            ),
            "preflight_generate_qrest": (
                ToolSpec(
                    name="preflight_generate_qrest",
                    description="Check whether qREST metadata JSON and time-series TXT data are ready for .qrest generation.",
                    arguments=[
                        _arg("metadata_json", "path", "Path to qREST metadata JSON."),
                        _arg("data_txt", "path", "Path to time-major text data."),
                        _arg("session_id", "string", "Optional session id for managed preflight report output.", required=False),
                    ],
                ),
                self._qrest_tools.preflight_generate_qrest,
            ),
            "generate_qrest": (
                ToolSpec(
                    name="generate_qrest",
                    description="Generate a binary .qrest file from qREST metadata JSON and time-series TXT data.",
                    arguments=[
                        _arg("metadata_json", "path", "Path to qREST metadata JSON."),
                        _arg("data_txt", "path", "Path to time-major text data."),
                        _arg("output_qrest", "path", "Path where the generated .qrest file should be written. Optional when session_id is supplied.", required=False),
                        _arg("strict", "boolean", "Treat preflight warnings as blocking errors when true.", required=False),
                        _arg("session_id", "string", "Optional session id for managed artifact output.", required=False),
                    ],
                ),
                self._qrest_tools.generate_qrest,
            ),
            "load_qrest": (
                ToolSpec(
                    name="load_qrest",
                    description="Extract qREST metadata JSON and readable TXT data from a binary .qrest file.",
                    arguments=[
                        _arg("input_qrest", "path", "Path to the input .qrest file."),
                        _arg("output_metadata_json", "path", "Path where metadata JSON should be written. Optional when session_id is supplied.", required=False),
                        _arg("output_data_txt", "path", "Path where readable data TXT should be written. Optional when session_id is supplied.", required=False),
                        _arg("compare_metadata_json", "path", "Optional metadata JSON path to compare against loaded metadata.", required=False),
                        _arg("session_id", "string", "Optional session id for managed artifact output.", required=False),
                    ],
                ),
                self._qrest_tools.load_qrest,
            ),
        }

    def list_specs(self) -> list[ToolSpec]:
        return [spec for spec, _ in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        spec, function = self._tools[name]
        session_id = arguments.get("session_id")
        prepared = self._prepare_arguments(name, dict(arguments))
        errors = validate_tool_arguments(spec, prepared)
        if errors:
            raise ValueError("tool argument validation failed: " + "; ".join(errors))
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
