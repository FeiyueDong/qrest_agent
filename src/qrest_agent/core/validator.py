from __future__ import annotations

from typing import Any

from qrest_agent.core.canonicalize import metadata_string_errors
from qrest_agent.core.models import ValidationIssue, ValidationReport
from qrest_agent.core.metadata_policy import channel_key_importance, channel_policy_keys, field_policy, is_blank
from qrest_agent.core.path import get_path
from qrest_agent.core.schema import QREST_REQUIRED_PATHS
from qrest_agent.core.schema_gate import SchemaViolation, validate_shape
from qrest_agent.state import WorkingState
from qrest_agent.state.evidence import Evidence
from qrest_agent.state.working_state import EXPORTABLE_STATUSES


def validate_state(state: Any) -> ValidationReport:
    metadata = state.to_metadata()
    missing_required: list[str] = []
    missing_important: list[str] = []
    missing_optional: list[str] = []
    conflicts: list[str] = []
    issues: list[ValidationIssue] = []

    _validate_schema(metadata, issues)

    for path in QREST_REQUIRED_PATHS:
        record = state.records.get(path)
        value = get_path(metadata, path)
        if record is not None and record.status == "conflict":
            conflicts.append(path)
            alternative_count = len(record.alternatives)
            message = (
                f"field has conflicting candidate values ({alternative_count} alternatives)"
                if alternative_count
                else "field has conflicting candidate values"
            )
            issues.append(ValidationIssue("error", path, message))
        elif is_blank(value):
            _append_missing_field(
                path,
                field_policy(path).importance,
                missing_required,
                missing_important,
                missing_optional,
                issues,
            )

    _validate_root(metadata, issues)
    _validate_building(metadata, issues)
    _validate_instrument(metadata, issues, missing_required, missing_important, missing_optional)
    _validate_data_info(metadata, issues)
    evidence_gaps = _validate_evidence(state, issues)

    ready = not missing_required and not conflicts and not any(issue.level == "error" for issue in issues)
    return ValidationReport(
        ready=ready,
        missing_required=missing_required,
        missing_important=missing_important,
        missing_optional=missing_optional,
        conflicts=conflicts,
        evidence_gaps=evidence_gaps,
        issues=issues,
    )


def _validate_evidence(state: Any, issues: list[ValidationIssue]) -> list[str]:
    """Evidence validation（方案 §7/§8）：状态合格但缺少证据的关键字段不得进入最终数据。

    只检查 tracked required paths；证据由 Working State 的 FieldState.evidence 提供。
    """
    gaps: list[str] = []
    for path in QREST_REQUIRED_PATHS:
        record = state.records.get(path)
        if record is None:
            continue
        if record.value is not None and record.status in EXPORTABLE_STATUSES and not record.evidence:
            gaps.append(path)
            issues.append(
                ValidationIssue("error", path, "field has no evidence; evidence is required for final export")
            )
    return gaps


def validate_metadata(metadata: dict[str, Any]) -> ValidationReport:
    """对完整 metadata dict 校验（方案 §32/§60）：非法结构不得因来源是 JSON 而放行。

    结构非法字段跳过导入（避免 SchemaViolation 中断），改由 Generic Schema
    Validation 层以 schema_error 报告。
    """
    state = WorkingState()
    for path in QREST_REQUIRED_PATHS:
        value = get_path(metadata, path)
        if value is None:
            continue
        try:
            state.set(
                path,
                value,
                status="confirmed",
                confidence=1.0,
                evidence=[Evidence(source_id="metadata", location=path)],
                updated_by="import",
            )
        except SchemaViolation:
            continue

    report = validate_state(state)
    issues = list(report.issues)
    _validate_schema(metadata, issues)
    issues = _dedupe_issues(issues)
    return ValidationReport(
        ready=report.ready and not any(issue.level == "error" for issue in issues),
        missing_required=report.missing_required,
        missing_important=report.missing_important,
        missing_optional=report.missing_optional,
        conflicts=report.conflicts,
        evidence_gaps=report.evidence_gaps,
        issues=issues,
    )


def _validate_schema(metadata: dict[str, Any], issues: list[ValidationIssue]) -> None:
    """Generic Schema Validation（方案 §28/§66）：所有字段基于统一 Schema 校验类型与形状。

    嵌套 required keys 的完整结构由 Domain Validation 按字段政策报告
    （方案 §54：基本 item type → Schema 层；完整 mandatory nested field → Validator）。
    """
    for path in QREST_REQUIRED_PATHS:
        value = get_path(metadata, path)
        if is_blank(value):
            continue
        result = validate_shape(path, value)
        if not result.valid:
            for error in result.errors:
                issues.append(ValidationIssue("error", path, error))

    # 方案 §4：正式 Metadata 字符串必须 ASCII 且受控字段使用标准值
    for error in metadata_string_errors(metadata):
        issues.append(ValidationIssue("error", _error_path(error), error))


def _error_path(message: str) -> str:
    return message.split(":", 1)[0]


def _dedupe_issues(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[ValidationIssue] = []
    for issue in issues:
        key = (issue.level, issue.field_path, issue.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(issue)
    return unique


def _validate_root(metadata: dict[str, Any], issues: list[ValidationIssue]) -> None:
    if not is_blank(metadata.get("Header")) and metadata.get("Header") != "qREST_DATA":
        issues.append(ValidationIssue("error", "Header", "Header must be qREST_DATA"))

    version = metadata.get("Version")
    if not is_blank(version) and not _is_number_list(version, 3, int):
        issues.append(ValidationIssue("error", "Version", "Version must be an integer array of length 3"))

    units = metadata.get("Units")
    if not is_blank(units) and (not isinstance(units, list) or len(units) < 2 or not all(isinstance(item, str) for item in units)):
        issues.append(ValidationIssue("error", "Units", "Units must contain at least distance and time units"))


def _validate_building(metadata: dict[str, Any], issues: list[ValidationIssue]) -> None:
    building = metadata.get("BuildingInfo")
    if not isinstance(building, dict):
        return

    elevation = building.get("Elevation")
    elevation_num = building.get("ElevationNum")
    if isinstance(elevation, list) and isinstance(elevation_num, int) and len(elevation) != elevation_num:
        issues.append(
            ValidationIssue(
                "error",
                "BuildingInfo.Elevation",
                "Elevation length must match BuildingInfo.ElevationNum",
            )
        )
    if isinstance(elevation, list) and any(not isinstance(item, int | float) for item in elevation):
        issues.append(ValidationIssue("error", "BuildingInfo.Elevation", "Elevation values must be numeric"))

    geo = building.get("GeoLocation")
    if isinstance(geo, dict):
        for key in ("Longitude", "Latitude", "NorthAngle"):
            if not is_blank(geo.get(key)) and not isinstance(geo.get(key), int | float):
                issues.append(ValidationIssue("error", f"BuildingInfo.GeoLocation.{key}", "value must be numeric"))

    bbox = get_path(metadata, "BuildingInfo.StructuralFootprint.BoundingBox")
    if isinstance(bbox, dict):
        for key in ("MaxX", "MinX", "MaxY", "MinY"):
            if not is_blank(bbox.get(key)) and not isinstance(bbox.get(key), int | float):
                issues.append(
                    ValidationIssue(
                        "error",
                        f"BuildingInfo.StructuralFootprint.BoundingBox.{key}",
                        "bounding box value must be numeric",
                    )
                )
        if isinstance(bbox.get("MaxX"), int | float) and isinstance(bbox.get("MinX"), int | float):
            if bbox["MaxX"] <= bbox["MinX"]:
                issues.append(
                    ValidationIssue("error", "BuildingInfo.StructuralFootprint.BoundingBox", "MaxX must be > MinX")
                )
        if isinstance(bbox.get("MaxY"), int | float) and isinstance(bbox.get("MinY"), int | float):
            if bbox["MaxY"] <= bbox["MinY"]:
                issues.append(
                    ValidationIssue("error", "BuildingInfo.StructuralFootprint.BoundingBox", "MaxY must be > MinY")
                )


def _validate_instrument(
    metadata: dict[str, Any],
    issues: list[ValidationIssue],
    missing_required: list[str],
    missing_important: list[str],
    missing_optional: list[str],
) -> None:
    instrument = metadata.get("InstrumentInfo")
    if not isinstance(instrument, dict):
        return

    channels = instrument.get("Channels")
    channel_num = instrument.get("ChannelNum")
    if not isinstance(channels, list):
        # 方案 §26：类型不对必须报错，不能静默跳过
        if not is_blank(channels):
            issues.append(ValidationIssue("error", "InstrumentInfo.Channels", "Channels must be an array"))
        return

    if isinstance(channel_num, int) and len(channels) != channel_num:
        issues.append(
            ValidationIssue("error", "InstrumentInfo.ChannelNum", "ChannelNum must match number of Channels")
        )

    expected_numbers = list(range(1, len(channels) + 1))
    actual_numbers: list[int] = []
    for index, channel in enumerate(channels):
        path = f"InstrumentInfo.Channels[{index}]"
        if not isinstance(channel, dict):
            issues.append(ValidationIssue("error", path, "channel entry must be an object"))
            continue

        for key in channel_policy_keys():
            if key not in channel or is_blank(channel.get(key)):
                issue_path = f"{path}.{key}"
                _append_missing_field(
                    issue_path,
                    channel_key_importance(key),
                    missing_required,
                    missing_important,
                    missing_optional,
                    issues,
                    field_label="channel field",
                )

        channel_no = channel.get("ChannelNo")
        if is_blank(channel_no):
            pass
        elif isinstance(channel_no, int):
            actual_numbers.append(channel_no)
        else:
            issues.append(ValidationIssue("error", f"{path}.ChannelNo", "ChannelNo must be an integer"))

        azimuth = channel.get("Azimuth")
        if is_blank(azimuth):
            pass
        elif not isinstance(azimuth, int | float):
            issues.append(ValidationIssue("error", f"{path}.Azimuth", "Azimuth must be numeric"))
        elif azimuth != -1 and not 0 <= azimuth <= 360:
            issues.append(ValidationIssue("error", f"{path}.Azimuth", "Azimuth must be -1 or within [0, 360]"))

        location = channel.get("LocationXYZ")
        if not is_blank(location) and not _is_number_list(location, 3, int | float):
            issues.append(ValidationIssue("error", f"{path}.LocationXYZ", "LocationXYZ must be numeric length 3"))

    if actual_numbers and actual_numbers != expected_numbers:
        issues.append(
            ValidationIssue(
                "error",
                "InstrumentInfo.Channels",
                "ChannelNo values must start at 1 and increase continuously",
            )
        )


def _validate_data_info(metadata: dict[str, Any], issues: list[ValidationIssue]) -> None:
    data_info = metadata.get("DataInfo")
    if not isinstance(data_info, dict):
        return

    npts = data_info.get("NPTS")
    if not is_blank(npts) and (not isinstance(npts, int) or npts <= 0):
        issues.append(ValidationIssue("error", "DataInfo.NPTS", "NPTS must be a positive integer"))

    dt = data_info.get("DT")
    if not is_blank(dt) and (not isinstance(dt, int | float) or dt <= 0):
        issues.append(ValidationIssue("error", "DataInfo.DT", "DT must be a positive number"))


def _is_number_list(value: Any, length: int, number_type: Any) -> bool:
    return isinstance(value, list) and len(value) == length and all(isinstance(item, number_type) for item in value)


def _append_missing_field(
    path: str,
    importance: str,
    missing_required: list[str],
    missing_important: list[str],
    missing_optional: list[str],
    issues: list[ValidationIssue],
    field_label: str = "qREST metadata field",
) -> None:
    if importance == "mandatory":
        missing_required.append(path)
        issues.append(ValidationIssue("error", path, f"mandatory {field_label} is missing"))
    elif importance == "important":
        missing_important.append(path)
        issues.append(ValidationIssue("warning", path, f"important {field_label} is missing; default will be used on export"))
    else:
        missing_optional.append(path)
        issues.append(ValidationIssue("info", path, f"optional {field_label} is missing; blank value will be exported"))
