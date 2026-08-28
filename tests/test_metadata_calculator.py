from __future__ import annotations

import json
from pathlib import Path

from qrest_agent.agent.tool_registry import ToolRegistry
from qrest_agent.resources import qrest_examples_root
from qrest_agent.skills import SkillRegistry
from qrest_agent.tools.metadata_calculator import (
    build_channel_layout,
    calculate_bounding_box,
    calculate_frequency,
    derive_channel_num,
    derive_elevation_num,
    derive_elevation_profile,
    normalize_azimuth,
)
from tests.conftest import write_json


def test_calculate_frequency_from_dt() -> None:
    assert calculate_frequency(0.02) == 50.0
    assert calculate_frequency(0.01) == 100.0


def test_calculate_bounding_box_centers_on_origin() -> None:
    box = calculate_bounding_box(42.0, 25.2)
    assert box == {"MaxX": 21.0, "MinX": -21.0, "MaxY": 12.6, "MinY": -12.6}


def test_derive_elevation_profile_matches_reference_case() -> None:
    profile = derive_elevation_profile(
        above_ground_floors=14,
        basement_floors=2,
        first_floor_height=4.5,
        typical_above_height=3.3,
        basement_first_height=2.6,
    )
    assert profile.elevations[:5] == [-2.6, 0.0, 4.5, 7.8, 11.1]
    assert len(profile.elevations) == 16
    assert profile.elevations[-1] == 47.4
    assert profile.monitored_floor_height("B1F") == -2.6
    assert profile.monitored_floor_height(1) == 0.0
    assert profile.monitored_floor_height(3) == 11.1


def test_build_channel_layout_generates_deterministic_channels() -> None:
    profile = derive_elevation_profile(
        above_ground_floors=14,
        basement_floors=2,
        first_floor_height=4.5,
        typical_above_height=3.3,
        basement_first_height=2.6,
    )
    channels = build_channel_layout(
        monitored_floors=["B1F", 1, 3, 6, 9, 13],
        profile=profile,
        footprint_length=42.0,
        footprint_width=25.2,
        device_type="941B",
    )

    assert len(channels) == 18
    assert channels[0]["ChannelNo"] == 1
    assert channels[0]["LocationXYZ"] == [-20.6, -4.2, -2.6]
    assert channels[0]["DeviceType"] == "941B"
    assert channels[0]["Azimuth"] == 90.0
    assert channels[0]["Measurand"] == "Acceleration"
    heights = sorted({channel["LocationXYZ"][2] for channel in channels})
    assert heights == [-2.6, 0.0, 11.1, 21.0, 30.9, 44.1]


def test_build_channel_layout_requires_per_floor_count_of_three() -> None:
    profile = derive_elevation_profile(
        above_ground_floors=3,
        basement_floors=0,
        first_floor_height=4.5,
        typical_above_height=3.3,
    )
    channels = build_channel_layout(
        monitored_floors=[1, 2, 3],
        profile=profile,
        footprint_length=42.0,
        footprint_width=25.2,
        per_floor_count=2,
    )
    assert channels == []


def test_derive_counts_and_azimuth_normalization() -> None:
    assert derive_elevation_num([0.0, 4.5, 7.8]) == 3
    assert derive_channel_num([{}, {}, {}]) == 3
    assert normalize_azimuth(360.0) == 0.0
    assert normalize_azimuth(450.0) == 90.0
    assert normalize_azimuth(-1) == -1.0


def test_calculation_tools_are_registered_and_executable(tmp_path: Path) -> None:
    registry = ToolRegistry(artifact_root=tmp_path / "artifacts")

    frequency = registry.execute("calculate_frequency", {"dt": 0.02})
    box = registry.execute("calculate_bounding_box", {"length": 42.0, "width": 25.2})
    azimuth = registry.execute("normalize_azimuth", {"azimuth": 450.0})
    profile = registry.execute(
        "derive_elevation_profile",
        {
            "above_ground_floors": 14,
            "basement_floors": 2,
            "first_floor_height": 4.5,
            "typical_above_height": 3.3,
            "basement_first_height": 2.6,
        },
    )
    layout = registry.execute(
        "derive_channel_layout",
        {
            "profile": profile["profile"],
            "monitored_floors": ["B1F", 1, 3, 6, 9, 13],
            "length": 42.0,
            "width": 25.2,
            "device_type": "941B",
        },
    )
    counts = registry.execute("derive_counts", {"elevations": [0.0, 4.5], "channels": [{}, {}]})

    write_json(
        artifact_dir := tmp_path / "calc.json",
        {
            "frequency": frequency,
            "box": box,
            "azimuth": azimuth,
            "profile": profile,
            "layout_head": layout["channels"][:2],
            "counts": counts,
        },
    )

    assert frequency == {"dt": 0.02, "frequency": 50.0}
    assert box["bounding_box"]["MaxX"] == 21.0
    assert azimuth["azimuth"] == 90.0
    assert profile["elevation_num"] == 16
    assert len(layout["channels"]) == 18
    assert counts == {"ElevationNum": 2, "ChannelNum": 2}


def test_read_document_tool_returns_chunks() -> None:
    registry = ToolRegistry()
    result = registry.execute(
        "read_document",
        {"path": qrest_examples_root() / "kunming2" / "metadata.json"},
    )
    assert result["chunk_count"] >= 1
    assert result["chunks"][0]["source_type"] == "json"


def test_validate_metadata_tool_reports_ready() -> None:
    registry = ToolRegistry()
    metadata = json.loads((qrest_examples_root() / "kunming2" / "metadata.json").read_text(encoding="utf-8"))
    report = registry.execute("validate_metadata", {"metadata": metadata})
    assert report["ready"] is True


def test_knowledge_skills_are_discoverable_and_authoritative(artifact_dir: Path) -> None:
    registry = SkillRegistry()
    skills = {
        name: registry.load(name)
        for name in ("metadata", "building_info", "instrument_info", "data_info")
    }

    write_json(
        artifact_dir / "skills" / "knowledge_skills.json",
        {name: skill.to_dict() for name, skill in skills.items()},
    )

    assert registry.list_names() == [
        "building_info",
        "data_info",
        "instrument_info",
        "metadata",
        "qrest_data_generation",
        "qrest_data_loading",
    ]
    assert "必须" in skills["metadata"].instructions
    assert "ElevationNum = len(Elevation)" in skills["building_info"].instructions
    assert "ChannelNum = len(Channels)" in skills["instrument_info"].instructions
    assert "Frequency = 1 / DT" in skills["data_info"].instructions
    for skill in skills.values():
        assert "禁止" in skill.instructions
