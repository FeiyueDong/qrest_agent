from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qrest_agent.resources import qrest_tool_path
from qrest_agent.core.validator import validate_metadata


@dataclass(slots=True)
class ToolResult:
    ok: bool
    command: list[str]
    stdout: str
    stderr: str
    outputs: dict[str, str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "outputs": self.outputs,
            "warnings": self.warnings,
            "errors": self.errors,
            "summary": self.summary,
        }


@dataclass(slots=True)
class DataTextProfile:
    path: str
    row_count: int
    channel_count: int | None
    malformed_rows: int
    non_numeric_rows: int

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "row_count": self.row_count,
            "channel_count": self.channel_count,
            "malformed_rows": self.malformed_rows,
            "non_numeric_rows": self.non_numeric_rows,
        }


@dataclass(slots=True)
class PreflightReport:
    ready: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata_report: dict[str, Any] | None = None
    data_profile: DataTextProfile | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "errors": self.errors,
            "warnings": self.warnings,
            "metadata_report": self.metadata_report,
            "data_profile": self.data_profile.to_dict() if self.data_profile else None,
        }


class QrestDataTools:
    """Agent-callable wrappers around qREST data command-line tools."""

    def generate_qrest(
        self,
        metadata_json: str | Path,
        data_txt: str | Path,
        output_qrest: str | Path,
        strict: bool = False,
    ) -> ToolResult:
        preflight = preflight_generate_qrest(metadata_json, data_txt)
        outputs = {"qrest": str(output_qrest)}
        if preflight.errors or (strict and preflight.warnings):
            return ToolResult(
                ok=False,
                command=[],
                stdout="",
                stderr="preflight failed",
                outputs=outputs,
                warnings=preflight.warnings,
                errors=preflight.errors or preflight.warnings,
                summary={"preflight": preflight.to_dict()},
            )

        Path(output_qrest).parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(qrest_tool_path("data_generator")),
            str(Path(metadata_json)),
            str(Path(data_txt)),
            str(Path(output_qrest)),
        ]
        result = _run(
            command,
            outputs=outputs,
            warnings=preflight.warnings,
            summary={"preflight": preflight.to_dict()},
        )
        if result.ok:
            result.summary["readable"] = f"generated qREST file: {output_qrest}"
        return result

    def load_qrest(
        self,
        input_qrest: str | Path,
        output_metadata_json: str | Path,
        output_data_txt: str | Path,
        compare_metadata_json: str | Path | None = None,
    ) -> ToolResult:
        if not Path(input_qrest).exists():
            return ToolResult(
                ok=False,
                command=[],
                stdout="",
                stderr="input qREST file does not exist",
                outputs={"metadata_json": str(output_metadata_json), "data_txt": str(output_data_txt)},
                errors=[f"input qREST file does not exist: {input_qrest}"],
            )

        Path(output_metadata_json).parent.mkdir(parents=True, exist_ok=True)
        Path(output_data_txt).parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(qrest_tool_path("data_loader")),
            str(Path(input_qrest)),
            str(Path(output_metadata_json)),
            str(Path(output_data_txt)),
        ]
        result = _run(
            command,
            outputs={"metadata_json": str(output_metadata_json), "data_txt": str(output_data_txt)},
        )
        if result.ok:
            result.summary.update(_summarize_loaded_outputs(output_metadata_json, output_data_txt))
            if compare_metadata_json is not None:
                comparison = compare_metadata_files(compare_metadata_json, output_metadata_json)
                result.summary["metadata_comparison"] = comparison
                if not comparison["equal"]:
                    result.warnings.append("loaded metadata differs from comparison metadata")
        return result


def preflight_generate_qrest(metadata_json: str | Path, data_txt: str | Path) -> PreflightReport:
    metadata_path = Path(metadata_json)
    data_path = Path(data_txt)
    errors: list[str] = []
    warnings: list[str] = []
    metadata_report: dict[str, Any] | None = None
    data_profile: DataTextProfile | None = None
    metadata: dict[str, Any] | None = None

    if not metadata_path.exists():
        errors.append(f"metadata JSON does not exist: {metadata_path}")
    else:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"metadata JSON is invalid: {exc}")

    if metadata is not None:
        report = validate_metadata(metadata)
        metadata_report = report.to_dict()
        if not report.ready:
            errors.extend(f"{issue.field_path}: {issue.message}" for issue in report.issues if issue.level == "error")

    if not data_path.exists():
        errors.append(f"data TXT does not exist: {data_path}")
    else:
        data_profile = inspect_data_txt(data_path)
        if data_profile.row_count == 0:
            errors.append(f"data TXT has no non-empty rows: {data_path}")
        if data_profile.malformed_rows:
            warnings.append(f"data TXT has {data_profile.malformed_rows} rows with inconsistent channel counts")
        if data_profile.non_numeric_rows:
            errors.append(f"data TXT has {data_profile.non_numeric_rows} non-numeric rows")

    if metadata is not None and data_profile is not None:
        data_info = metadata.get("DataInfo", {}) if isinstance(metadata.get("DataInfo"), dict) else {}
        instrument_info = metadata.get("InstrumentInfo", {}) if isinstance(metadata.get("InstrumentInfo"), dict) else {}
        npts = data_info.get("NPTS")
        channel_num = instrument_info.get("ChannelNum")
        if isinstance(npts, int) and npts != data_profile.row_count:
            warnings.append(f"DataInfo.NPTS={npts} but data TXT has {data_profile.row_count} rows")
        if isinstance(channel_num, int) and data_profile.channel_count is not None and channel_num != data_profile.channel_count:
            warnings.append(
                f"InstrumentInfo.ChannelNum={channel_num} but data TXT has {data_profile.channel_count} columns"
            )

    return PreflightReport(
        ready=not errors,
        errors=errors,
        warnings=warnings,
        metadata_report=metadata_report,
        data_profile=data_profile,
    )


def inspect_data_txt(path: str | Path) -> DataTextProfile:
    row_count = 0
    channel_count: int | None = None
    malformed_rows = 0
    non_numeric_rows = 0
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            values = stripped.split()
            row_count += 1
            if channel_count is None:
                channel_count = len(values)
            elif len(values) != channel_count:
                malformed_rows += 1
            try:
                for value in values:
                    float(value)
            except ValueError:
                non_numeric_rows += 1
    return DataTextProfile(
        path=str(path),
        row_count=row_count,
        channel_count=channel_count,
        malformed_rows=malformed_rows,
        non_numeric_rows=non_numeric_rows,
    )


def compare_metadata_files(expected_metadata_json: str | Path, actual_metadata_json: str | Path) -> dict[str, Any]:
    expected = json.loads(Path(expected_metadata_json).read_text(encoding="utf-8"))
    actual = json.loads(Path(actual_metadata_json).read_text(encoding="utf-8"))
    differences = _diff_values(expected, actual)
    return {
        "expected_metadata_json": str(expected_metadata_json),
        "actual_metadata_json": str(actual_metadata_json),
        "equal": not differences,
        "differences": differences[:50],
        "difference_count": len(differences),
    }


def _summarize_loaded_outputs(metadata_json: str | Path, data_txt: str | Path) -> dict[str, Any]:
    metadata = json.loads(Path(metadata_json).read_text(encoding="utf-8"))
    profile = inspect_data_txt(data_txt)
    building = metadata.get("BuildingInfo", {}) if isinstance(metadata.get("BuildingInfo"), dict) else {}
    instrument = metadata.get("InstrumentInfo", {}) if isinstance(metadata.get("InstrumentInfo"), dict) else {}
    data_info = metadata.get("DataInfo", {}) if isinstance(metadata.get("DataInfo"), dict) else {}
    readable = (
        f"project={building.get('ProjectName', 'unknown')}; "
        f"event={data_info.get('EventName', 'unknown')}; "
        f"channels={instrument.get('ChannelNum', profile.channel_count)}; "
        f"rows={profile.row_count}; columns={profile.channel_count}"
    )
    return {
        "metadata": {
            "project_name": building.get("ProjectName"),
            "event_name": data_info.get("EventName"),
            "channel_num": instrument.get("ChannelNum"),
            "npts": data_info.get("NPTS"),
            "dt": data_info.get("DT"),
        },
        "data_profile": profile.to_dict(),
        "readable": readable,
    }


def _diff_values(expected: Any, actual: Any, path: str = "") -> list[dict[str, Any]]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        differences: list[dict[str, Any]] = []
        for key in sorted(set(expected) | set(actual)):
            child_path = f"{path}.{key}" if path else str(key)
            if key not in expected:
                differences.append({"path": child_path, "expected": None, "actual": actual[key], "status": "extra"})
            elif key not in actual:
                differences.append({"path": child_path, "expected": expected[key], "actual": None, "status": "missing"})
            else:
                differences.extend(_diff_values(expected[key], actual[key], child_path))
        return differences
    if isinstance(expected, list) and isinstance(actual, list):
        if expected == actual:
            return []
        return [{"path": path, "expected": expected, "actual": actual, "status": "changed"}]
    if expected != actual:
        return [{"path": path, "expected": expected, "actual": actual, "status": "changed"}]
    return []


def _run(
    command: list[str],
    outputs: dict[str, str],
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    summary: dict[str, Any] | None = None,
) -> ToolResult:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    return ToolResult(
        ok=completed.returncode == 0,
        command=command,
        stdout=completed.stdout,
        stderr=completed.stderr,
        outputs=outputs,
        warnings=list(warnings or []),
        errors=list(errors or []),
        summary=dict(summary or {}),
    )
