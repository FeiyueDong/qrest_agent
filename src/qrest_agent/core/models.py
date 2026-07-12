from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CandidateStatus = Literal["extracted", "derived", "confirmed", "missing", "conflict"]
RecordStatus = Literal["empty", "extracted", "derived", "confirmed", "missing", "conflict"]


@dataclass(slots=True)
class Evidence:
    source_id: str
    location: str | None = None
    text: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evidence":
        return cls(
            source_id=str(data.get("source_id", "unknown")),
            location=data.get("location"),
            text=data.get("text"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"source_id": self.source_id, "location": self.location, "text": self.text}


@dataclass(slots=True)
class Candidate:
    field_path: str
    value: Any
    status: CandidateStatus = "extracted"
    confidence: float = 0.5
    evidence: list[Evidence] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Candidate":
        evidence = [Evidence.from_dict(item) for item in data.get("evidence", [])]
        return cls(
            field_path=str(data["field_path"]),
            value=data.get("value"),
            status=data.get("status", "extracted"),
            confidence=float(data.get("confidence", 0.5)),
            evidence=evidence,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_path": self.field_path,
            "value": self.value,
            "status": self.status,
            "confidence": self.confidence,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(slots=True)
class Alternative:
    value: Any
    status: CandidateStatus
    confidence: float
    evidence: list[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "status": self.status,
            "confidence": self.confidence,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(slots=True)
class FieldRecord:
    value: Any = None
    status: RecordStatus = "empty"
    confidence: float = 0.0
    evidence: list[Evidence] = field(default_factory=list)
    alternatives: list[Alternative] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "status": self.status,
            "confidence": self.confidence,
            "evidence": [item.to_dict() for item in self.evidence],
            "alternatives": [item.to_dict() for item in self.alternatives],
        }


@dataclass(slots=True)
class ValidationIssue:
    level: Literal["error", "warning"]
    field_path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"level": self.level, "field_path": self.field_path, "message": self.message}


@dataclass(slots=True)
class ValidationReport:
    ready: bool
    missing_required: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "missing_required": self.missing_required,
            "conflicts": self.conflicts,
            "issues": [item.to_dict() for item in self.issues],
        }

