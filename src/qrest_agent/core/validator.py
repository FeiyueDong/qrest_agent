from __future__ import annotations

from typing import Any

from qrest_agent.core.models import ValidationIssue, ValidationReport
from qrest_agent.core.metadata_policy import channel_key_importance, channel_policy_keys, field_policy, is_blank
from qrest_agent.core.path import get_path
from qrest_agent.core.schema import QREST_REQUIRED_PATHS
from qrest_agent.core.state import MetadataState


def validate_state(state: MetadataState) -> ValidationReport:
    metadata = state.to_metadata()
    missing_required: list[str] = []
    missing_important: list[str] = []
    missing_optional: list[str] = []
    conflicts: list[str] = []
    issues: list[ValidationIssue] = []

    for path in QREST_REQUIRED_PATHS:
        record = state.records.get(path)
        value = get_path(metadata, path)
        if record is not None and record.status == "conflict":
            conflicts.append(path)
            issues.append(ValidationIssue("error", path, "field has conflicting candidate values"))
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

    ready = not missing_required and not conflicts and not any(issue.level == "error" for issue in issues)
    return ValidationReport(
        ready=ready,
        missing_required=missing_required,
        missing_important=missing_important,
        missing_optional=missing_optional,
        conflicts=conflicts,
        issues=issues,
    )


def validate_metadata(metadata: dict[str, Any]) -> ValidationReport:
    return validate_state(MetadataState.from_metadata(metadata))


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
