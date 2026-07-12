from __future__ import annotations

import json
import re
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
        return candidates


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
