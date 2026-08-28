from __future__ import annotations

from dataclasses import dataclass
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evidence":
        return cls(
            source_id=str(data.get("source_id", "unknown")),
            location=data.get("location"),
            text=data.get("text"),
            source_type=data.get("source_type"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "location": self.location,
            "text": self.text,
            "source_type": self.source_type,
        }

    def describe(self) -> str:
        if self.location:
            return f"{self.source_id}@{self.location}"
        return self.source_id
