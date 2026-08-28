from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from qrest_agent.agent.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_user_prompt
from qrest_agent.core.models import Candidate, Evidence
from qrest_agent.core.schema import QREST_FIELD_SPECS_BY_PATH, QREST_REQUIRED_PATHS
from qrest_agent.ingestion.sources import SourceChunk
from qrest_agent.llm.clients import BaseLLMClient

#: LLM 候选允许的状态；其他状态直接拒绝。
_ALLOWED_CANDIDATE_STATUSES = {
    "extracted",
    "derived",
    "confirmed",
    "missing",
    "uncertain",
    "inferred",
    "conflict",
}

#: Intermediate Facts 的路径命名空间（方案 §6-§7）：以这些前缀开头的候选是
#: 推理中间事实（Building.above_ground_floors、Monitoring.monitored_floors 等），
#: 永不导出为 Metadata。
FACT_PREFIXES: tuple[str, ...] = ("Building.", "Monitoring.")


@dataclass(slots=True)
class ExtractionContext:
    """Extraction 的本轮专业上下文（方案 §6/§7/§8）。

    让 Extractor 不再只是“通用 Metadata 抽取器”，而是能感知：
    - 本轮 intent（如 correction → 用户消息中的替代值应产生 confirmed）；
    - 本轮选中的 Skills 及其完整指令（约束如何理解与提取）。
    """

    intent: str = ""
    selected_skills: list[str] = field(default_factory=list)
    skill_instructions: list[str] = field(default_factory=list)
    user_message: str = ""
    #: 当前已知字段值（correction 时帮助模型输出完整对象，保留未提及的子字段）
    current_values: dict[str, Any] = field(default_factory=dict)

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "selected_skills": list(self.selected_skills),
            "skill_instructions": list(self.skill_instructions),
            "current_values": dict(self.current_values),
        }


class LLMExtractor:
    """正式提取路径：LLM + selected Skills 的语义提取（设计文档 §9）。

    Candidate 必须通过证据校验（§11）：
    - value != null 且 status 为 extracted/confirmed 时，evidence 为空 → 拒绝；
    - evidence.text 无法在来源 chunk 中找到（归一化后）→ 降为 uncertain。
    """

    def __init__(self, client: BaseLLMClient) -> None:
        self.client = client

    def extract(
        self,
        chunks: list[SourceChunk],
        context: ExtractionContext | None = None,
    ) -> list[Candidate]:
        candidates: list[Candidate] = []
        prompt_context = context.to_prompt_dict() if context is not None else None
        for chunk in chunks:
            messages = [
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_extraction_user_prompt(chunk.text, prompt_context),
                },
            ]
            result = self.client.complete_json(messages)
            for item in result.get("candidates", []):
                candidate = _candidate_from_model_item(item, chunk)
                if candidate is None:
                    continue
                validated = _validate_llm_candidate(candidate, chunk)
                if validated is None:
                    continue
                _apply_correction_promotion(validated, chunk, context)
                candidates.append(validated)
            for item in result.get("facts", []):
                candidate = _fact_from_model_item(item, chunk)
                if candidate is None:
                    continue
                validated = _validate_llm_candidate(candidate, chunk)
                if validated is None:
                    continue
                candidates.append(validated)
        return candidates


class RuleBasedExtractor:
    """离线/无模型/测试模式的确定性兜底提取（设计文档 §9 fallback）。

    只保留通用字段模式，不包含任何项目特定解析逻辑。
    """

    def extract(
        self,
        chunks: list[SourceChunk],
        context: ExtractionContext | None = None,
    ) -> list[Candidate]:
        # 规则兜底只做通用模式提取；correction 语义只适用于 LLM 路径。
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
    return candidates


def _validate_llm_candidate(candidate: Candidate, chunk: SourceChunk) -> Candidate | None:
    """Candidate 证据校验（设计文档 §11）：防 LLM 幻觉 value + 伪造 evidence。"""
    if candidate.status not in _ALLOWED_CANDIDATE_STATUSES:
        return None
    if candidate.value is None:
        return candidate

    # 11.1 禁止自动补 evidence：extracted/confirmed 必须有证据
    if candidate.status in {"extracted", "confirmed"} and not candidate.evidence:
        return None

    # 11.2 evidence 可验证：文本归一化后必须在来源 chunk 中能找到
    if candidate.status in {"extracted", "confirmed", "uncertain"} and candidate.evidence:
        source_text = _normalize_evidence_text(chunk.text)
        if not any(
            evidence.text and _normalize_evidence_text(evidence.text) in source_text
            for evidence in candidate.evidence
        ):
            # 伪造/不可验证的 evidence：降为 uncertain，保留审计信息，禁止进入最终数据
            candidate.status = "uncertain"
            candidate.confidence = min(candidate.confidence, 0.4)
    return candidate


def _apply_correction_promotion(
    candidate: Candidate,
    chunk: SourceChunk,
    context: ExtractionContext | None,
) -> None:
    """方案 §8：correction 语义必须可靠产生 confirmed。

    条件（全部满足）：
    - 本轮 intent == correction；
    - 来源是用户消息（chat）；
    - 候选已通过证据校验（仍是 extracted）且给出非空替代值。
    此时 extracted → confirmed（用户明确给出的替代值，等同确认）。
    """
    if context is None or context.intent != "correction":
        return
    if chunk.source_type != "chat":
        return
    if candidate.status != "extracted" or candidate.value is None:
        return
    candidate.status = "confirmed"
    candidate.confidence = max(candidate.confidence, 1.0)


def _normalize_evidence_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


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
    # 设计文档 §11.1：不自动把整个 chunk 当作 evidence；缺失时由 _validate_llm_candidate 拒绝
    item["evidence"] = evidence_items
    return Candidate.from_dict(item)


def _fact_from_model_item(item: Any, chunk: SourceChunk) -> Candidate | None:
    """方案 §6：Intermediate Fact（path/value/status/evidence）→ Candidate。

    只接受以 FACT_PREFIXES 开头的路径；facts 与 metadata 一样必须带可验证证据。
    """
    if not isinstance(item, dict):
        return None
    field_path = str(item.get("path") or item.get("field_path") or "")
    if not field_path.startswith(FACT_PREFIXES):
        return None
    return Candidate(
        field_path=field_path,
        value=item.get("value"),
        status=item.get("status", "extracted"),
        confidence=float(item.get("confidence", 0.6) or 0.6),
        evidence=_evidence_from_item(item, chunk),
    )


def _evidence_from_item(item: dict[str, Any], chunk: SourceChunk) -> list[Evidence]:
    evidence_items: list[dict[str, Any]] = []
    raw_evidence = item.get("evidence")
    if isinstance(raw_evidence, list):
        for evidence in raw_evidence:
            if isinstance(evidence, dict):
                evidence_items.append(evidence)
            elif isinstance(evidence, str):
                evidence_items.append({"source_id": chunk.source_id, "location": chunk.location, "text": evidence})
    return [Evidence.from_dict(entry) for entry in evidence_items]
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
