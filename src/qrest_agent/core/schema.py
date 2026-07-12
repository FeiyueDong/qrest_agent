from __future__ import annotations

QREST_REQUIRED_PATHS = [
    "Header",
    "Version",
    "Units",
    "BuildingInfo.ProjectName",
    "BuildingInfo.GeoLocation.Longitude",
    "BuildingInfo.GeoLocation.Latitude",
    "BuildingInfo.GeoLocation.NorthAngle",
    "BuildingInfo.StructuralType",
    "BuildingInfo.StructuralFootprint.Shape",
    "BuildingInfo.StructuralFootprint.Parameters",
    "BuildingInfo.StructuralFootprint.BoundingBox",
    "BuildingInfo.ElevationNum",
    "BuildingInfo.Elevation",
    "InstrumentInfo.Provider",
    "InstrumentInfo.ChannelNum",
    "InstrumentInfo.Channels",
    "DataInfo.EventName",
    "DataInfo.StartTime",
    "DataInfo.NPTS",
    "DataInfo.DT",
    "DataInfo.Corrected",
]

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

