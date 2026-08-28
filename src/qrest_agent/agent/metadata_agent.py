from __future__ import annotations

from pathlib import Path
from typing import Any

from qrest_agent.agent.agent import QrestAgent, TurnResult
from qrest_agent.core.exporter import MetadataExportResult, prepare_metadata_export
from qrest_agent.core.models import Candidate, ValidationReport
from qrest_agent.core.state import MetadataState
from qrest_agent.core.validator import validate_state
from qrest_agent.ingestion.sources import SourceChunk
from qrest_agent.llm.clients import BaseLLMClient


class MetadataAgent:
    """旧管线的过渡门面（Phase 1-2）：委托给新的 QrestAgent。

    新主 Agent 是决策主体；本类保留旧 API（state/tools/extractor）供
    dialogue、API、Web 与既有测试使用，Phase 3 拆分后将被移除。
    """

    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        tool_registry: Any | None = None,
    ) -> None:
        self.core = QrestAgent(llm_client=llm_client, tool_registry=tool_registry)
        self.state = MetadataState(working=self.core.working_state)
        self.llm_client = llm_client
        self.sources = self.core.sources
        self.extractor = self.core.extractor
        self.tools = self.core.tools

    def ingest_text(self, text: str, source_id: str = "user_message") -> list[SourceChunk]:
        return self.core.ingest_text(text, source_id=source_id)

    def ingest_file(self, path: str | Path) -> list[SourceChunk]:
        return self.core.ingest_file(path)

    def run_turn(self, text: str | None = None, files: list[str | Path] | None = None) -> TurnResult:
        return self.core.run_turn(text=text, files=files)

    def export_metadata(self, include_reserved_analysis: bool = True) -> dict[str, Any]:
        result = self.prepare_metadata_export(include_reserved_analysis=include_reserved_analysis)
        if not result.ok or result.metadata is None:
            blocked = ", ".join(result.blocked_fields)
            raise ValueError(f"metadata cannot be exported; blocked=[{blocked}]")
        return result.metadata

    def prepare_metadata_export(self, include_reserved_analysis: bool = True) -> MetadataExportResult:
        return prepare_metadata_export(self.state, include_reserved_analysis=include_reserved_analysis)

    def export_audit(self) -> dict[str, Any]:
        report = validate_state(self.state)
        export = self.prepare_metadata_export()
        return {
            "ready": report.ready,
            "validation": report.to_dict(),
            "export": export.to_dict(include_metadata=False),
            "records": self.state.to_audit_dict(),
            "tool_specs": [spec.to_dict() for spec in self.tools.list_specs()],
        }

    def export_artifacts(self, metadata_path: str | Path, audit_path: str | Path) -> ValidationReport:
        export = self.prepare_metadata_export()
        report = export.report
        Path(audit_path).write_text(_to_json(self.export_audit()), encoding="utf-8")
        if export.ok and export.metadata is not None:
            Path(metadata_path).write_text(_to_json(export.metadata), encoding="utf-8")
        return report


def _to_json(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)
