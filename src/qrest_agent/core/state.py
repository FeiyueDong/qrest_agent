from __future__ import annotations

from copy import deepcopy
from typing import Any

from qrest_agent.core.models import Alternative, Candidate, Evidence, FieldRecord
from qrest_agent.core.path import get_path, set_path
from qrest_agent.core.schema import DEFAULT_METADATA, QREST_REQUIRED_PATHS


class MetadataState:
    def __init__(self, records: dict[str, FieldRecord] | None = None) -> None:
        self.records = records or {}

    @classmethod
    def empty(cls) -> "MetadataState":
        state = cls()
        for path in ("Header", "Version", "Units"):
            value = get_path(DEFAULT_METADATA, path)
            state.records[path] = FieldRecord(
                value=deepcopy(value),
                status="confirmed",
                confidence=1.0,
                evidence=[Evidence(source_id="system_default", text="qREST metadata default")],
            )
        return state

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any], source_id: str = "metadata") -> "MetadataState":
        state = cls.empty()
        for path in QREST_REQUIRED_PATHS:
            value = get_path(metadata, path)
            if value is not None:
                state.records[path] = FieldRecord(
                    value=deepcopy(value),
                    status="confirmed",
                    confidence=1.0,
                    evidence=[Evidence(source_id=source_id, location=path)],
                )
        return state

    def submit(self, candidate: Candidate) -> FieldRecord:
        current = self.records.get(candidate.field_path)
        if candidate.status == "missing" or candidate.value is None:
            if current is None:
                current = FieldRecord(value=None, status="missing", confidence=candidate.confidence)
                self.records[candidate.field_path] = current
            return current

        if current is None or current.status in {"empty", "missing"}:
            current = FieldRecord(
                value=deepcopy(candidate.value),
                status=candidate.status,
                confidence=candidate.confidence,
                evidence=list(candidate.evidence),
            )
            self.records[candidate.field_path] = current
            return current

        if current.status == "confirmed" and candidate.status != "confirmed":
            return current

        if current.value == candidate.value:
            current.confidence = max(current.confidence, candidate.confidence)
            current.evidence.extend(candidate.evidence)
            if candidate.status == "confirmed":
                current.status = "confirmed"
            return current

        if candidate.status == "confirmed":
            current.alternatives.append(
                Alternative(
                    value=deepcopy(current.value),
                    status=current.status if current.status != "empty" else "extracted",
                    confidence=current.confidence,
                    evidence=list(current.evidence),
                )
            )
            current.value = deepcopy(candidate.value)
            current.status = "confirmed"
            current.confidence = candidate.confidence
            current.evidence = list(candidate.evidence)
            return current

        current.status = "conflict"
        current.alternatives.append(
            Alternative(
                value=deepcopy(candidate.value),
                status=candidate.status,
                confidence=candidate.confidence,
                evidence=list(candidate.evidence),
            )
        )
        return current

    def submit_many(self, candidates: list[Candidate]) -> None:
        for candidate in candidates:
            self.submit(candidate)

    def to_metadata(self, include_reserved_analysis: bool = True) -> dict[str, Any]:
        metadata = deepcopy(DEFAULT_METADATA if include_reserved_analysis else {})
        if not include_reserved_analysis:
            metadata.update({"Header": None, "Version": None, "Units": None})

        for path, record in self.records.items():
            if record.status in {"empty", "missing", "conflict"}:
                continue
            set_path(metadata, path, deepcopy(record.value))
        return metadata

    def to_audit_dict(self) -> dict[str, Any]:
        return {path: record.to_dict() for path, record in sorted(self.records.items())}

