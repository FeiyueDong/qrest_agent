from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Evidence:
    """一条事实来源记录（方案 §7：value + status + evidence）。

    source_type 可取值示例：chat / document / json / tool / rule / llm /
    user_confirmation / system_default。它只用于审计与校验，不参与合并决策。
    """

    source_id: str
    location: str | None = None
    text: str | None = None
    source_type: str | None = None
    #: 确定性推导：计算工具名（设计文档 §11.3，如 "derive_counts"）
    tool: str | None = None
    #: 确定性推导：来源字段路径（如 ["BuildingInfo.Elevation"]）
    derived_from: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evidence":
        raw_derived_from = data.get("derived_from") or []
        return cls(
            source_id=str(data.get("source_id", "unknown")),
            location=data.get("location"),
            text=data.get("text"),
            source_type=data.get("source_type"),
            tool=data.get("tool"),
            derived_from=[str(item) for item in raw_derived_from] if isinstance(raw_derived_from, list) else [],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "location": self.location,
            "text": self.text,
            "source_type": self.source_type,
            "tool": self.tool,
            "derived_from": list(self.derived_from),
        }

    def describe(self) -> str:
        if self.location:
            return f"{self.source_id}@{self.location}"
        return self.source_id
