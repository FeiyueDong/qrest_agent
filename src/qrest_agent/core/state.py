from __future__ import annotations

from copy import deepcopy
from typing import Any

from qrest_agent.core.models import Candidate, Evidence, FieldRecord
from qrest_agent.core.path import get_path
from qrest_agent.core.schema import DEFAULT_METADATA, QREST_REQUIRED_PATHS
from qrest_agent.state.working_state import WorkingState


class MetadataState:
    """Phase 1-2 过渡门面：委托给新的 qrest_agent.state.WorkingState。

    旧调用方（dialogue / validator / exporter / tests）继续通过本类工作；
    Phase 3 拆分后本类将被删除，新主 Agent 直接使用 WorkingState。
    """

    def __init__(
        self,
        records: dict[str, FieldRecord] | None = None,
        base_metadata: dict[str, Any] | None = None,
        working: WorkingState | None = None,
    ) -> None:
        if working is not None:
            self.working = working
            return
        self.working = WorkingState(
            base_metadata=deepcopy(base_metadata) if base_metadata is not None else deepcopy(DEFAULT_METADATA)
        )
        for path, record in (records or {}).items():
            status = record.status if record.status != "empty" else "missing"
            self.working.set(
                path,
                record.value,
                status=status,
                confidence=record.confidence,
                evidence=list(record.evidence),
            )

    @property
    def records(self) -> dict[str, FieldRecord]:
        return self.working.fields

    @classmethod
    def empty(cls) -> "MetadataState":
        state = cls()
        state.working.seed_defaults(
            {path: get_path(DEFAULT_METADATA, path) for path in ("Header", "Version", "Units")}
        )
        return state

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any], source_id: str = "metadata") -> "MetadataState":
        state = cls(base_metadata=metadata)
        state.working.import_metadata(metadata, source_id=source_id, paths=QREST_REQUIRED_PATHS)
        return state

    def submit(self, candidate: Candidate) -> FieldRecord:
        return self.working.submit(candidate)

    def submit_many(self, candidates: list[Candidate]) -> None:
        self.working.submit_all(candidates)

    def to_metadata(self, include_reserved_analysis: bool = True, require_evidence: bool = True) -> dict[str, Any]:
        metadata = self.working.to_metadata(require_evidence=require_evidence)
        if include_reserved_analysis and "analysis" not in metadata:
            metadata["analysis"] = deepcopy(DEFAULT_METADATA["analysis"])
        if not include_reserved_analysis:
            metadata.pop("analysis", None)
        return metadata

    def to_audit_dict(self) -> dict[str, Any]:
        return self.working.to_audit_dict()
