from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal

from qrest_agent.core.path import get_path, set_path
from qrest_agent.state.evidence import Evidence

FieldStatus = Literal[
    "missing",
    "extracted",
    "uncertain",
    "derived",
    "inferred",
    "confirmed",
    "conflict",
]

#: 允许进入最终 qREST Metadata 的状态（方案 §8）：
#: - confirmed：用户明确提供/确认；
#: - extracted：从资料中明确提取（含证据）；
#: - derived：由确定性关系计算（记录 derived_from）。
#: uncertain / inferred 默认禁止进入最终数据。
EXPORTABLE_STATUSES: frozenset[str] = frozenset({"extracted", "derived", "confirmed"})

_ALLOWED_STATUSES = {
    "missing",
    "extracted",
    "uncertain",
    "derived",
    "inferred",
    "confirmed",
    "conflict",
}


@dataclass(slots=True)
class Alternative:
    """冲突时保留的备选事实。"""

    value: Any
    status: FieldStatus
    confidence: float
    evidence: list[Evidence] = field(default_factory=list)
    source_label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "status": self.status,
            "confidence": self.confidence,
            "evidence": [item.to_dict() for item in self.evidence],
            "source_label": self.source_label,
        }


@dataclass(slots=True)
class FieldState:
    """Working State 中单个字段的当前事实（方案 §7 的 FieldState）。

    与旧 FieldRecord 兼容（value/status/confidence/evidence/alternatives），
    并新增 derived_from / revision / updated_by 用于审计。
    """

    field_path: str
    value: Any = None
    status: FieldStatus = "missing"
    confidence: float = 0.0
    evidence: list[Evidence] = field(default_factory=list)
    alternatives: list[Alternative] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)
    revision: int = 0
    updated_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_path": self.field_path,
            "value": self.value,
            "status": self.status,
            "confidence": self.confidence,
            "evidence": [item.to_dict() for item in self.evidence],
            "alternatives": [item.to_dict() for item in self.alternatives],
            "derived_from": list(self.derived_from),
            "revision": self.revision,
            "updated_by": self.updated_by,
        }

    def is_export_eligible(self, require_evidence: bool = True) -> bool:
        if self.value is None or self.status not in EXPORTABLE_STATUSES:
            return False
        if require_evidence and not self.evidence:
            return False
        return True


class WorkingState:
    """方案 §7 的 Working State：保存 Agent 当前对工程的理解（事实 + 状态 + 证据）。

    所有 Agent 提取结果先进入 Working State；最终 Metadata 只从
    to_metadata() 生成，且默认只收有证据且状态合格的字段。
    """

    def __init__(
        self,
        base_metadata: dict[str, Any] | None = None,
        tracked_paths: list[str] | None = None,
    ) -> None:
        self.base_metadata = deepcopy(base_metadata or {})
        self.tracked_paths = list(tracked_paths or [])
        self._fields: dict[str, FieldState] = {}

    # ---- 查询 ----

    @property
    def fields(self) -> dict[str, FieldState]:
        return self._fields

    #: 与旧 MetadataState.records 同名的兼容访问（validator 仍按 records 读取）。
    @property
    def records(self) -> dict[str, FieldState]:
        return self._fields

    def get(self, field_path: str) -> FieldState | None:
        return self._fields.get(field_path)

    def record(self, field_path: str) -> FieldState:
        state = self._fields.get(field_path)
        if state is None:
            state = FieldState(field_path=field_path)
            self._fields[field_path] = state
        return state

    def field_paths(self) -> list[str]:
        return sorted(self._fields)

    def conflicts(self) -> list[str]:
        return sorted(path for path, state in self._fields.items() if state.status == "conflict")

    def missing(self) -> list[str]:
        missing_paths: list[str] = []
        for path in self.tracked_paths:
            state = self._fields.get(path)
            if state is None or state.status in {"missing", "empty"} or state.value is None:
                missing_paths.append(path)
        return missing_paths

    def evidence_gaps(self) -> list[str]:
        """状态合格但缺少证据的字段（Phase 7 的 evidence validation 前置检查）。"""
        return sorted(
            path
            for path, state in self._fields.items()
            if state.value is not None
            and state.status in EXPORTABLE_STATUSES
            and not state.evidence
        )

    # ---- 写入 ----

    def set(
        self,
        field_path: str,
        value: Any,
        *,
        status: str = "extracted",
        confidence: float = 0.5,
        evidence: list[Evidence] | None = None,
        derived_from: list[str] | None = None,
        updated_by: str = "system",
    ) -> FieldState:
        """低层写入/覆盖（导入、种子数据用）。对话合并请使用 update/confirm/derive。"""
        state = self.record(field_path)
        if (
            state.value is not None
            and state.value != value
            and state.status not in {"missing", "empty"}
        ):
            state.alternatives.append(
                Alternative(
                    value=deepcopy(state.value),
                    status=state.status,
                    confidence=state.confidence,
                    evidence=list(state.evidence),
                )
            )
        state.value = deepcopy(value)
        state.status = _normalize_status(status)
        state.confidence = confidence
        state.evidence = list(evidence or [])
        state.derived_from = list(derived_from or []) if state.status == "derived" else []
        state.updated_by = updated_by
        state.revision += 1
        return state

    def update(
        self,
        field_path: str,
        value: Any,
        *,
        status: str = "extracted",
        confidence: float = 0.5,
        evidence: list[Evidence] | None = None,
        derived_from: list[str] | None = None,
        updated_by: str = "system",
    ) -> FieldState:
        """合并一条新事实：confirmed 受保护；值不同且非 confirmed 时进入 conflict。"""
        return self._merge(
            field_path,
            value,
            status,
            confidence,
            list(evidence or []),
            derived_from,
            updated_by,
        )

    def submit(self, candidate: Any, *, updated_by: str | None = None) -> FieldState:
        """接受任何 Candidate 形状的对象（field_path/value/status/confidence/evidence）。"""
        return self._merge(
            candidate.field_path,
            candidate.value,
            getattr(candidate, "status", "extracted"),
            float(getattr(candidate, "confidence", 0.5) or 0.5),
            list(getattr(candidate, "evidence", None) or []),
            getattr(candidate, "derived_from", None),
            updated_by or getattr(candidate, "updated_by", None),
        )

    def submit_all(self, candidates: list[Any]) -> None:
        for candidate in candidates:
            self.submit(candidate)

    def confirm(
        self,
        field_path: str,
        value: Any,
        evidence: list[Evidence] | None = None,
        *,
        updated_by: str = "user",
    ) -> FieldState:
        return self.update(
            field_path,
            value,
            status="confirmed",
            confidence=1.0,
            evidence=list(evidence or []),
            updated_by=updated_by,
        )

    def derive(
        self,
        field_path: str,
        value: Any,
        derived_from: list[str],
        evidence: list[Evidence] | None = None,
        *,
        confidence: float = 0.8,
        updated_by: str = "tool",
    ) -> FieldState:
        return self.update(
            field_path,
            value,
            status="derived",
            confidence=confidence,
            evidence=list(evidence or []),
            derived_from=list(derived_from),
            updated_by=updated_by,
        )

    def mark_missing(
        self,
        field_path: str,
        evidence: list[Evidence] | None = None,
        *,
        updated_by: str = "system",
    ) -> FieldState:
        state = self.record(field_path)
        state.value = None
        state.status = "missing"
        state.evidence = list(evidence or [])
        state.updated_by = updated_by
        state.revision += 1
        return state

    def resolve_conflict(
        self,
        field_path: str,
        choice: Literal["current", "alternative"],
        evidence: list[Evidence] | None = None,
        *,
        updated_by: str = "user",
    ) -> FieldState:
        state = self.record(field_path)
        if state.status != "conflict":
            return state
        if choice == "alternative" and state.alternatives:
            chosen = state.alternatives[-1]
            state.value = deepcopy(chosen.value)
            state.evidence = list(chosen.evidence)
        state.alternatives = []
        state.status = "confirmed"
        state.confidence = 1.0
        state.updated_by = updated_by
        if evidence:
            state.evidence.extend(list(evidence))
        state.revision += 1
        return state

    # ---- 汇总 ----

    def to_metadata(self, require_evidence: bool = True) -> dict[str, Any]:
        metadata = deepcopy(self.base_metadata)
        for path, state in self._fields.items():
            if state.is_export_eligible(require_evidence=require_evidence):
                set_path(metadata, path, deepcopy(state.value))
        return metadata

    def to_audit_dict(self) -> dict[str, Any]:
        return {path: state.to_dict() for path, state in sorted(self._fields.items())}

    def seed_defaults(
        self,
        defaults: dict[str, Any],
        *,
        source_id: str = "system_default",
        updated_by: str = "system",
    ) -> None:
        for path, value in defaults.items():
            self.set(
                path,
                value,
                status="confirmed",
                confidence=1.0,
                evidence=[Evidence(source_id=source_id, text="qREST metadata default")],
                updated_by=updated_by,
            )

    def import_metadata(
        self,
        metadata: dict[str, Any],
        *,
        source_id: str = "metadata",
        paths: list[str] | None = None,
        updated_by: str = "import",
    ) -> None:
        self.base_metadata = deepcopy(metadata)
        for path in paths or []:
            value = get_path(metadata, path)
            if value is not None:
                self.set(
                    path,
                    value,
                    status="confirmed",
                    confidence=1.0,
                    evidence=[Evidence(source_id=source_id, location=path)],
                    updated_by=updated_by,
                )

    def _merge(
        self,
        field_path: str,
        value: Any,
        status: str,
        confidence: float,
        evidence: list[Evidence],
        derived_from: list[str] | None,
        updated_by: str | None,
    ) -> FieldState:
        status = _normalize_status(status)
        if status == "missing" or value is None:
            state = self.record(field_path)
            if state.status in {"missing", "empty"}:
                state.status = "missing"
                state.value = None
                state.revision += 1
            return state

        state = self._fields.get(field_path)
        if state is None or state.status in {"missing", "empty"}:
            state = self.record(field_path)
            state.value = deepcopy(value)
            state.status = status
            state.confidence = confidence
            state.evidence = list(evidence)
            state.derived_from = list(derived_from or []) if status == "derived" else []
            state.updated_by = updated_by
            state.revision += 1
            return state

        if state.status == "confirmed" and status != "confirmed":
            return state

        if state.value == value:
            state.confidence = max(state.confidence, confidence)
            state.evidence.extend(evidence)
            if status == "confirmed":
                state.status = "confirmed"
                state.updated_by = updated_by
            state.revision += 1
            return state

        if status == "confirmed":
            state.alternatives.append(
                Alternative(
                    value=deepcopy(state.value),
                    status=state.status,
                    confidence=state.confidence,
                    evidence=list(state.evidence),
                )
            )
            state.value = deepcopy(value)
            state.status = "confirmed"
            state.confidence = confidence
            state.evidence = list(evidence)
            state.derived_from = []
            state.updated_by = updated_by
            state.revision += 1
            return state

        state.status = "conflict"
        state.alternatives.append(
            Alternative(
                value=deepcopy(value),
                status=status,
                confidence=confidence,
                evidence=list(evidence),
            )
        )
        state.revision += 1
        return state


def _normalize_status(status: Any) -> FieldStatus:
    if status in _ALLOWED_STATUSES:
        return status  # type: ignore[return-value]
    return "extracted"
