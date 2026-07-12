from __future__ import annotations

import json
import re
from typing import Any

from qrest_agent.agent.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_user_prompt
from qrest_agent.core.models import Candidate, Evidence
from qrest_agent.core.schema import QREST_REQUIRED_PATHS
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
            re.compile(r"(?:采样间隔|DT)\s*(?:为|是|:|：)?\s*([0-9]+(?:\.[0-9]+)?)\s*s?"),
            float,
        ),
        (
            "DataInfo.NPTS",
            re.compile(r"(?:采样点数|NPTS)\s*(?:为|是|:|：)?\s*(\d+)"),
            int,
        ),
        (
            "DataInfo.EventName",
            re.compile(r"(?:事件名|地震事件|EventName)\s*(?:为|是|:|：)\s*([A-Za-z0-9_\-.]+)"),
            str,
        ),
    ]
    candidates: list[Candidate] = []
    for field_path, pattern, caster in patterns:
        match = pattern.search(text)
        if match:
            raw_value = match.group(1)
            candidates.append(_candidate(field_path, caster(raw_value), chunk, evidence_text=match.group(0)))

    height_match = re.search(r"(?:建筑高度|结构高度|大楼高度)\s*(?:为|是|:|：)?\s*([0-9]+(?:\.[0-9]+)?)\s*m", text)
    if height_match:
        height = float(height_match.group(1))
        candidates.append(
            _candidate(
                "BuildingInfo.Elevation",
                [0.0, height],
                chunk,
                status="derived",
                confidence=0.55,
                evidence_text=height_match.group(0),
            )
        )
        candidates.append(
            _candidate(
                "BuildingInfo.ElevationNum",
                2,
                chunk,
                status="derived",
                confidence=0.55,
                evidence_text=height_match.group(0),
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

    data = dict(item)
    data["evidence"] = evidence_items
    return Candidate.from_dict(data)


def _get(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current
