from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from qrest_agent.state.evidence import Evidence
from qrest_agent.state.working_state import Alternative, FieldState, FieldStatus

# 兼容别名（Phase 2 过渡）：新的 Working State 字段记录即 FieldState。
FieldRecord = FieldState
RecordStatus = FieldStatus

CandidateStatus = Literal[
    "extracted",
    "derived",
    "confirmed",
    "missing",
    "conflict",
    "uncertain",
    "inferred",
]


@dataclass(slots=True)
class Candidate:
    """一条待合并的候选事实（提取器/动作解释的输出形状）。"""

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
class ValidationIssue:
    level: Literal["error", "warning", "info"]
    field_path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"level": self.level, "field_path": self.field_path, "message": self.message}


@dataclass(slots=True)
class ValidationReport:
    ready: bool
    missing_required: list[str] = field(default_factory=list)
    missing_important: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    evidence_gaps: list[str] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "missing_required": self.missing_required,
            "missing_important": self.missing_important,
            "missing_optional": self.missing_optional,
            "missing_fields": self.missing_required + self.missing_important + self.missing_optional,
            "conflicts": self.conflicts,
            "evidence_gaps": list(self.evidence_gaps),
            "issues": [item.to_dict() for item in self.issues],
        }
