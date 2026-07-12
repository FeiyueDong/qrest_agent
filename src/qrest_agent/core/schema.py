from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FieldRequirement = Literal["required", "optional", "extension"]
FieldKind = Literal["string", "integer", "number", "array", "object"]


@dataclass(frozen=True, slots=True)
class FieldSpec:
    path: str
    kind: FieldKind
    requirement: FieldRequirement
    description: str
    unit_role: str | None = None
    allow_derived: bool = False


QREST_FIELD_SPECS = [
    FieldSpec("Header", "string", "required", "metadata identifier"),
    FieldSpec("Version", "array", "required", "file format version"),
    FieldSpec("Units", "array", "required", "base distance and time units"),
    FieldSpec("BuildingInfo.ProjectName", "string", "required", "project or building identifier"),
    FieldSpec("BuildingInfo.GeoLocation.Longitude", "number", "required", "longitude"),
    FieldSpec("BuildingInfo.GeoLocation.Latitude", "number", "required", "latitude"),
    FieldSpec("BuildingInfo.GeoLocation.NorthAngle", "number", "required", "local Y axis angle from north"),
    FieldSpec("BuildingInfo.StructuralType", "string", "required", "structural type"),
    FieldSpec("BuildingInfo.StructuralFootprint.Shape", "string", "required", "footprint shape"),
    FieldSpec("BuildingInfo.StructuralFootprint.Parameters", "object", "required", "shape parameters"),
    FieldSpec("BuildingInfo.StructuralFootprint.BoundingBox", "object", "required", "footprint bounding box"),
    FieldSpec("BuildingInfo.ElevationNum", "integer", "required", "number of elevation entries"),
    FieldSpec("BuildingInfo.Elevation", "array", "required", "elevation array", unit_role="distance"),
    FieldSpec("InstrumentInfo.Provider", "string", "required", "monitoring system provider"),
    FieldSpec("InstrumentInfo.ChannelNum", "integer", "required", "number of channels"),
    FieldSpec("InstrumentInfo.Channels", "array", "required", "channel configuration list"),
    FieldSpec("DataInfo.EventName", "string", "required", "event identifier"),
    FieldSpec("DataInfo.StartTime", "string", "required", "record start time"),
    FieldSpec("DataInfo.NPTS", "integer", "required", "sample point count"),
    FieldSpec("DataInfo.DT", "number", "required", "sampling interval", unit_role="time"),
    FieldSpec("DataInfo.Corrected", "string", "required", "data correction marker"),
]

QREST_REQUIRED_PATHS = [spec.path for spec in QREST_FIELD_SPECS if spec.requirement == "required"]
QREST_FIELD_SPECS_BY_PATH = {spec.path: spec for spec in QREST_FIELD_SPECS}
QREST_EXTENSION_POLICY = (
    "Unknown fields are preserved during import/export. They are not required for readiness "
    "and are not used by deterministic validation unless promoted to FieldSpec."
)

CHANNEL_REQUIRED_KEYS = [
    "ChannelNo",
    "ChannelID",
    "Measurand",
    "Scale",
    "Azimuth",
    "LocationXYZ",
]

DEFAULT_METADATA = {
    "Header": "qREST_DATA",
    "Version": [1, 0, 0],
    "Units": ["m", "s"],
    "BuildingInfo": {},
    "InstrumentInfo": {},
    "DataInfo": {},
    "analysis": {
        "method": None,
        "parameters": {},
        "status": "reserved",
    },
}
