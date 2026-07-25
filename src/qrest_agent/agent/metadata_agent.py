from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qrest_agent.agent.extractor import LLMExtractor, RuleBasedExtractor
from qrest_agent.agent.tool_registry import ToolRegistry
from qrest_agent.core.models import Candidate, ValidationReport
from qrest_agent.core.state import MetadataState
from qrest_agent.core.validator import validate_state
from qrest_agent.ingestion.sources import SourceChunk, SourceManager
from qrest_agent.llm.clients import BaseLLMClient


@dataclass(slots=True)
class TurnResult:
    candidates: list[Candidate]
    report: ValidationReport
    response: str
    extractor: str = "unknown"
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [item.to_dict() for item in self.candidates],
            "report": self.report.to_dict(),
            "response": self.response,
            "extractor": self.extractor,
            "fallback_reason": self.fallback_reason,
        }


class MetadataAgent:
    def __init__(self, llm_client: BaseLLMClient | None = None, tool_registry: ToolRegistry | None = None) -> None:
        self.llm_client = llm_client
        self.state = MetadataState.empty()
        self.sources = SourceManager()
        self.extractor = LLMExtractor(llm_client) if llm_client is not None else RuleBasedExtractor()
        self.tools = tool_registry or ToolRegistry()

    def ingest_text(self, text: str, source_id: str = "user_message") -> list[SourceChunk]:
        return self.sources.add_text(text, source_id=source_id)

    def ingest_file(self, path: str | Path) -> list[SourceChunk]:
        return self.sources.add_file(path)

    def run_turn(self, text: str | None = None, files: list[str | Path] | None = None) -> TurnResult:
        chunks: list[SourceChunk] = []
        if text:
            chunks.extend(self.ingest_text(text))
        for path in files or []:
            chunks.extend(self.ingest_file(path))

        using_llm = isinstance(self.extractor, LLMExtractor)
        fallback_reason: str | None = None
        rule_extractor = RuleBasedExtractor()
        if using_llm:
            try:
                llm_candidates = self.extractor.extract(chunks)
            except Exception as exc:
                fallback_reason = f"LLM extraction failed: {exc}"
                llm_candidates = []

            rule_candidates = rule_extractor.extract(chunks)
            if llm_candidates:
                candidates = llm_candidates + rule_candidates
                extractor_name = "llm+rule" if rule_candidates else "llm"
            else:
                fallback_reason = fallback_reason or "LLM extraction returned no candidates"
                candidates = rule_candidates
                extractor_name = "rule"
        else:
            try:
                candidates = rule_extractor.extract(chunks)
            except Exception as exc:
                fallback_reason = f"rule extraction failed: {exc}"
                candidates = []
            extractor_name = "rule"

        self.state.submit_many(candidates)
        report = validate_state(self.state)
        return TurnResult(
            candidates=candidates,
            report=report,
            response=_build_response(report),
            extractor=extractor_name,
            fallback_reason=fallback_reason,
        )

    def export_metadata(self, include_reserved_analysis: bool = True) -> dict[str, Any]:
        report = validate_state(self.state)
        if not report.ready:
            missing = ", ".join(report.missing_required)
            conflicts = ", ".join(report.conflicts)
            raise ValueError(f"metadata is not ready; missing=[{missing}], conflicts=[{conflicts}]")
        return self.state.to_metadata(include_reserved_analysis=include_reserved_analysis)

    def export_audit(self) -> dict[str, Any]:
        report = validate_state(self.state)
        return {
            "ready": report.ready,
            "validation": report.to_dict(),
            "records": self.state.to_audit_dict(),
            "tool_specs": [spec.to_dict() for spec in self.tools.list_specs()],
        }

    def export_artifacts(self, metadata_path: str | Path, audit_path: str | Path) -> ValidationReport:
        report = validate_state(self.state)
        Path(audit_path).write_text(_to_json(self.export_audit()), encoding="utf-8")
        if report.ready:
            Path(metadata_path).write_text(_to_json(self.export_metadata()), encoding="utf-8")
        return report


def _build_response(report: ValidationReport) -> str:
    if report.conflicts:
        return "发现字段存在冲突，请确认：" + "，".join(report.conflicts)
    if report.missing_required:
        return "当前仍缺少必要信息：" + "，".join(report.missing_required)
    if any(issue.level == "warning" for issue in report.issues):
        return "元数据已基本完整，但仍有警告需要复核。"
    return "元数据已通过校验，可以导出 qREST metadata.json。"


def _to_json(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)
