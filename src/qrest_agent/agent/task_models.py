from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qrest_agent.core.models import ValidationReport


@dataclass(frozen=True, slots=True)
class TaskIntent:
    name: str
    skill_name: str
    mode: str
    metadata_json: str | None = None
    data_txt: str | None = None
    output_qrest: str | None = None
    input_qrest: str | None = None
    compare_metadata_json: str | None = None
    strict: bool = False


@dataclass(slots=True)
class TaskExecutionResult:
    response: str
    report: ValidationReport
    command: str
    tool_result: dict[str, Any]
