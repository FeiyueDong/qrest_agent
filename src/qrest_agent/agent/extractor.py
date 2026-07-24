from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from qrest_agent.agent.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_user_prompt
from qrest_agent.core.models import Candidate, Evidence
from qrest_agent.core.schema import QREST_FIELD_SPECS_BY_PATH, QREST_REQUIRED_PATHS
from qrest_agent.ingestion.sources import SourceChunk
from qrest_agent.llm.clients import BaseLLMClient


class LLMExtractor:
    def __init__(self, client: BaseLLMClient) -> None:
        self.client = client

    def extract(self, chunks: list[SourceChunk]) -> list[Candidate]:
        candidates: list[Candidate] = []
        for chunk in chunks:
            messages = [
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": build_extraction_user_prompt(chunk.text)},
            ]
            result = self.client.complete_json(messages)
            for item in result.get("candidates", []):
                candidate = _candidate_from_model_item(item, chunk)
                if candidate is not None:
                    candidates.append(candidate)
        return candidates


class RuleBasedExtractor:
    """Small offline extractor used for smoke tests before an LLM is configured."""

    def extract(self, chunks: list[SourceChunk]) -> list[Candidate]:
        candidates: list[Candidate] = []
        for chunk in chunks:
            candidates.extend(_extract_from_json(chunk))
            candidates.extend(_extract_from_text(chunk))
        candidates.extend(_extract_cross_chunk_patterns(chunks))
        return candidates


@dataclass(frozen=True, slots=True)
class ElevationProfile:
    above_ground_floors: int
    basement_floors: int
    first_floor_height: float
    typical_above_height: float
    basement_first_height: float | None
    basement_second_height: float | None
    elevations: list[float]

    def monitored_floor_height(self, floor: str | int) -> float | None:
        if floor == "B1F":
            return self.elevations[0] if self.elevations and self.elevations[0] < 0 else None
        if floor == 1:
            return 0.0
        if isinstance(floor, int) and floor > 1:
            return _round_m(self.first_floor_height + (floor - 1) * self.typical_above_height)
        return None


def _extract_from_json(chunk: SourceChunk) -> list[Candidate]:
    text = chunk.text.strip()
    if not text.startswith("{"):
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    paths = {
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
    }
    candidates: list[Candidate] = []
    for path in paths:
        value = _get(data, path)
        if value is not None:
            candidates.append(_candidate(path, value, chunk, confidence=1.0))
    return candidates


def _extract_from_text(chunk: SourceChunk) -> list[Candidate]:
    text = chunk.text
    patterns: list[tuple[str, re.Pattern[str], Any]] = [
        (
            "BuildingInfo.ProjectName",
            re.compile(r"(?:项目名|项目名称|工程名|工程名称|ProjectName)\s*(?:为|是|:|：)\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)"),
            str,
        ),
        (
            "BuildingInfo.StructuralType",
            re.compile(r"(?:结构类型|结构体系|StructuralType)\s*(?:为|是|:|：)\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)"),
            str,
        ),
        (
            "BuildingInfo.ElevationNum",
            re.compile(r"(?:标高层数|ElevationNum)\s*(?:为|是|:|：)?\s*(\d+)"),
            int,
        ),
        (
            "DataInfo.DT",
            re.compile(r"(?:采样时间间隔|采样间隔|DT)\s*(?:为|是|:|：)?\s*([0-9]+(?:\.[0-9]+)?)\s*s?"),
            float,
        ),
        (
            "DataInfo.NPTS",
            re.compile(r"(?:数据点数|采样点数|NPTS)\s*(?:为|是|:|：)?\s*(\d+)"),
            int,
        ),
        (
            "DataInfo.EventName",
            re.compile(r"(?:事件名|事件名称|地震事件|EventName)\s*(?:为|是|:|：)\s*([A-Za-z0-9_\-.]+)"),
            str,
        ),
    ]
    candidates: list[Candidate] = []
    for field_path, pattern, caster in patterns:
        match = pattern.search(text)
        if match:
            raw_value = match.group(1)
            candidates.append(_candidate(field_path, caster(raw_value), chunk, evidence_text=match.group(0)))

    candidates.extend(_extract_kunming_document_patterns(text, chunk))
    return candidates


def _extract_cross_chunk_patterns(chunks: list[SourceChunk]) -> list[Candidate]:
    if not chunks:
        return []
    text = "\n".join(chunk.text for chunk in chunks)
    chunk = _combined_chunk(chunks, text)
    candidates: list[Candidate] = []

    profile = _parse_elevation_profile(text)
    if profile is not None:
        evidence = _elevation_evidence(text)
        candidates.append(
            _candidate(
                "BuildingInfo.ElevationNum",
                len(profile.elevations),
                chunk,
                status="derived",
                confidence=0.8,
                evidence_text=evidence,
            )
        )
        candidates.append(
            _candidate(
                "BuildingInfo.Elevation",
                profile.elevations,
                chunk,
                status="derived",
                confidence=0.75,
                evidence_text=evidence,
            )
        )

    channels = _derive_channels_from_layout(text, profile)
    if channels:
        candidates.append(
            _candidate(
                "InstrumentInfo.ChannelNum",
                len(channels),
                chunk,
                status="derived",
                confidence=0.75,
                evidence_text=_channel_evidence(text),
            )
        )
        candidates.append(
            _candidate(
                "InstrumentInfo.Channels",
                channels,
                chunk,
                status="derived",
                confidence=0.6,
                evidence_text=_channel_evidence(text),
            )
        )

    return candidates


def _extract_kunming_document_patterns(text: str, chunk: SourceChunk) -> list[Candidate]:
    candidates: list[Candidate] = []

    floor_match = re.search(r"地上共有\s*(\d+)\s*层，地下共有\s*(\d+)\s*层", text)
    if floor_match:
        above_ground = int(floor_match.group(1))
        basement = int(floor_match.group(2))
        candidates.append(
            _candidate(
                "BuildingInfo.ElevationNum",
                above_ground + basement,
                chunk,
                status="derived",
                confidence=0.75,
                evidence_text=floor_match.group(0),
            )
        )

    if "钢框架体系" in text or "钢框架" in text:
        candidates.append(
            _candidate(
                "BuildingInfo.StructuralType",
                "SteelFrame",
                chunk,
                status="derived",
                confidence=0.7,
                evidence_text="钢框架体系",
            )
        )

    footprint_match = re.search(
        r"(?:结构长度方向约为|结构长度方向|长度方向约为)\s*([0-9]+(?:\.[0-9]+)?)\s*m[，,、\s]*(?:宽度方向约为|宽度方向|宽度)\s*([0-9]+(?:\.[0-9]+)?)\s*m",
        text,
    )
    if footprint_match:
        length = float(footprint_match.group(1))
        width = float(footprint_match.group(2))
        candidates.append(_candidate("BuildingInfo.StructuralFootprint.Shape", "Rectangular", chunk, confidence=0.8, evidence_text=footprint_match.group(0)))
        candidates.append(
            _candidate(
                "BuildingInfo.StructuralFootprint.Parameters",
                {"Length": length, "Width": width},
                chunk,
                confidence=0.8,
                evidence_text=footprint_match.group(0),
            )
        )
        candidates.append(
            _candidate(
                "BuildingInfo.StructuralFootprint.BoundingBox",
                {"MaxX": length / 2, "MinX": -length / 2, "MaxY": width / 2, "MinY": -width / 2},
                chunk,
                status="derived",
                confidence=0.7,
                evidence_text=footprint_match.group(0),
            )
        )

    channel_match = re.search(r"(?:共布置|总计布置|总共布置)\s*(\d+)\s*个单向加速度传感器", text)
    if channel_match:
        candidates.append(
            _candidate(
                "InstrumentInfo.ChannelNum",
                int(channel_match.group(1)),
                chunk,
                confidence=0.85,
                evidence_text=channel_match.group(0),
            )
        )

    provider_match = re.search(r"系统采用(.+?)研制的\s*([A-Za-z0-9]+)\s*型加速度传感器", text)
    if provider_match:
        candidates.append(
            _candidate(
                "InstrumentInfo.Provider",
                provider_match.group(1),
                chunk,
                confidence=0.65,
                evidence_text=provider_match.group(0),
            )
        )

    start_match = re.search(r"数据开始时间[:：]\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})（UTC\+8）", text)
    if start_match:
        candidates.append(
            _candidate(
                "DataInfo.StartTime",
                f"{start_match.group(1)}T{start_match.group(2)}.000+08:00",
                chunk,
                confidence=0.9,
                evidence_text=start_match.group(0),
            )
        )

    return candidates


def _parse_elevation_profile(text: str) -> ElevationProfile | None:
    floor_match = re.search(r"地上共有\s*(\d+)\s*层[，,、\s]*地下共有\s*(\d+)\s*层", text)
    first_match = re.search(r"首层高度\s*(?:为|是|:|：)?\s*([0-9]+(?:\.[0-9]+)?)\s*m", text)
    typical_match = re.search(r"其余地上楼层层高均为\s*([0-9]+(?:\.[0-9]+)?)\s*m", text)
    if not (floor_match and first_match and typical_match):
        return None

    above_ground = int(floor_match.group(1))
    basement = int(floor_match.group(2))
    first_height = float(first_match.group(1))
    typical_height = float(typical_match.group(1))
    basement_first = _optional_float_match(r"地下第一层层高\s*(?:为|是|:|：)?\s*([0-9]+(?:\.[0-9]+)?)\s*m", text)
    basement_second = _optional_float_match(r"地下第二层层高\s*(?:为|是|:|：)?\s*([0-9]+(?:\.[0-9]+)?)\s*m", text)

    elevations: list[float] = []
    if basement > 0:
        # The qREST examples keep one representative underground monitoring elevation
        # before ground level. If no explicit B1 absolute elevation exists, use the
        # height of the floor below B1 as the best supported boundary.
        if basement >= 2 and basement_second is not None:
            elevations.append(_round_m(-basement_second))
        elif basement_first is not None:
            elevations.append(_round_m(-basement_first))
    elevations.append(0.0)
    for index in range(above_ground):
        elevations.append(_round_m(first_height + index * typical_height))

    return ElevationProfile(
        above_ground_floors=above_ground,
        basement_floors=basement,
        first_floor_height=first_height,
        typical_above_height=typical_height,
        basement_first_height=basement_first,
        basement_second_height=basement_second,
        elevations=elevations,
    )


def _derive_channels_from_layout(text: str, profile: ElevationProfile | None) -> list[dict[str, Any]]:
    if profile is None:
        return []
    monitored_floors = _parse_monitored_floors(text)
    if not monitored_floors:
        return []
    per_floor_count = _parse_per_floor_sensor_count(text)
    if per_floor_count != 3:
        return []
    footprint = _parse_footprint_size(text)
    if footprint is None:
        return []
    if not re.search(r"左[右侧区域\s、及以及和]*右|左右两侧|左侧区域、右侧区域以及中间区域|中部区域", text):
        return []

    length, width = footprint
    x_edge = _round_m(max(length / 2 - 0.4, length / 2 * 0.95), digits=1)
    y_line = _round_m(-width / 6, digits=1)
    device_type = _parse_device_type(text)
    channel_templates = [
        (-x_edge, y_line, 90.0),
        (x_edge, y_line, 90.0),
        (0.0, y_line, 0.0),
    ]

    channels: list[dict[str, Any]] = []
    channel_no = 1
    for floor in monitored_floors:
        z = profile.monitored_floor_height(floor)
        if z is None:
            return []
        for x, y, azimuth in channel_templates:
            channel: dict[str, Any] = {
                "ChannelNo": channel_no,
                "ChannelID": "UNKNOWN",
                "Measurand": "Acceleration",
                "Scale": 1.0,
                "Azimuth": azimuth,
                "LocationXYZ": [_round_m(x, digits=1), _round_m(y, digits=1), _round_m(z, digits=1)],
            }
            if device_type is not None:
                channel["DeviceType"] = device_type
            channels.append(channel)
            channel_no += 1
    return channels


def _parse_monitored_floors(text: str) -> list[str | int]:
    match = re.search(r"监测楼层包括(.+?)(?:。|\n)", text)
    if not match:
        return []
    section = match.group(1)
    token_pattern = re.compile(r"地下第一层(?:（B1F）|\(B1F\))?|B1F|地上首层|首层|(\d+)\s*层")
    floors: list[str | int] = []
    for token in token_pattern.finditer(section):
        raw = token.group(0)
        if "地下第一层" in raw or "B1F" in raw:
            value: str | int = "B1F"
        elif "首层" in raw:
            value = 1
        else:
            value = int(token.group(1))
        if value not in floors:
            floors.append(value)
    return floors


def _parse_per_floor_sensor_count(text: str) -> int | None:
    match = re.search(r"每个(?:监测楼层|位置)\s*布置\s*(\d+)\s*个(?:单向)?加速度传感器|每(?:层|个位置)设置\s*(\d+)\s*个(?:水平向|单向)?加速度测点", text)
    if not match:
        return None
    value = match.group(1) or match.group(2)
    return int(value)


def _parse_footprint_size(text: str) -> tuple[float, float] | None:
    match = re.search(
        r"(?:结构长度方向约为|结构长度方向|长度方向约为)\s*([0-9]+(?:\.[0-9]+)?)\s*m[，,、\s]*(?:宽度方向约为|宽度方向|宽度)\s*([0-9]+(?:\.[0-9]+)?)\s*m",
        text,
    )
    if match:
        return float(match.group(1)), float(match.group(2))
    match = re.search(r"建筑平面尺寸约为\s*([0-9]+(?:\.[0-9]+)?)\s*m?\s*[×xX]\s*([0-9]+(?:\.[0-9]+)?)\s*m", text)
    if match:
        return float(match.group(1)), float(match.group(2))
    return None


def _parse_device_type(text: str) -> str | None:
    match = re.search(r"研制的\s*([A-Za-z0-9]+)\s*型加速度传感器", text)
    return match.group(1) if match else None


def _optional_float_match(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text)
    return float(match.group(1)) if match else None


def _round_m(value: float, digits: int = 3) -> float:
    rounded = round(float(value), digits)
    return 0.0 if rounded == -0.0 else rounded


def _combined_chunk(chunks: list[SourceChunk], text: str) -> SourceChunk:
    source_ids = ",".join(dict.fromkeys(chunk.source_id for chunk in chunks[:5]))
    if len(chunks) > 5:
        source_ids = f"{source_ids},..."
    return SourceChunk(source_id=source_ids or "combined_sources", location="cross_chunk", text=text[:3000], source_type="derived")


def _elevation_evidence(text: str) -> str:
    snippets = []
    for pattern in (
        r"建筑地上共有.+?地下共有.+?层",
        r"首层高度.+?m",
        r"其余地上楼层层高均为.+?m",
        r"地下第一层层高.+?m",
        r"地下第二层层高.+?m",
    ):
        match = re.search(pattern, text)
        if match:
            snippets.append(match.group(0))
    return "；".join(snippets)[:500]


def _channel_evidence(text: str) -> str:
    snippets = []
    for pattern in (
        r"监测楼层包括.+?(?:。|\n)",
        r"每个监测楼层布置.+?(?:。|\n)",
        r"每层设置三个.+?(?:。|\n)",
        r"测点分别位于.+?(?:。|\n)",
        r"系统采用.+?型加速度传感器",
    ):
        match = re.search(pattern, text)
        if match:
            snippets.append(match.group(0).strip())
    return "；".join(snippets)[:800]


def _candidate(
    field_path: str,
    value: Any,
    chunk: SourceChunk,
    status: str = "extracted",
    confidence: float = 0.8,
    evidence_text: str | None = None,
) -> Candidate:
    return Candidate(
        field_path=field_path,
        value=value,
        status=status,  # type: ignore[arg-type]
        confidence=confidence,
        evidence=[Evidence(source_id=chunk.source_id, location=chunk.location, text=evidence_text or chunk.text[:300])],
    )


def _candidate_from_model_item(item: Any, chunk: SourceChunk) -> Candidate | None:
    if not isinstance(item, dict):
        return None
    field_path = item.get("field_path")
    if field_path not in QREST_REQUIRED_PATHS:
        return None
    item = dict(item)
    item["value"] = _normalize_model_value(field_path, item.get("value"), item.get("status"))

    evidence_items: list[dict[str, Any]] = []
    raw_evidence = item.get("evidence")
    if isinstance(raw_evidence, list):
        for evidence in raw_evidence:
            if isinstance(evidence, dict):
                evidence_items.append(evidence)
            elif isinstance(evidence, str):
                evidence_items.append({"source_id": chunk.source_id, "location": chunk.location, "text": evidence})
    if not evidence_items and item.get("value") is not None:
        evidence_items.append({"source_id": chunk.source_id, "location": chunk.location, "text": chunk.text[:300]})

    item["evidence"] = evidence_items
    return Candidate.from_dict(item)


def _normalize_model_value(field_path: str, value: Any, status: Any) -> Any:
    if isinstance(value, str) and value.strip().lower() in {"null", "none", "missing", ""}:
        return None
    if status == "missing":
        return None

    spec = QREST_FIELD_SPECS_BY_PATH.get(field_path)
    if spec is None:
        return value
    if spec.kind == "integer" and isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return value
    if spec.kind == "number" and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    if spec.kind in {"object", "array"} and isinstance(value, str) and value.strip().startswith(("{", "[")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _get(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current
