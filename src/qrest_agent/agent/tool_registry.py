from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from qrest_agent.tools.qrest_data_tools import QrestDataTools


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._qrest_tools = QrestDataTools()
        self._tools: dict[str, tuple[ToolSpec, Callable[..., Any]]] = {
            "generate_qrest": (
                ToolSpec(
                    name="generate_qrest",
                    description="Generate a binary .qrest file from qREST metadata JSON and time-series TXT data.",
                    parameters={
                        "metadata_json": "Path to qREST metadata JSON.",
                        "data_txt": "Path to time-major text data.",
                        "output_qrest": "Path where the generated .qrest file should be written.",
                    },
                ),
                self._qrest_tools.generate_qrest,
            ),
            "load_qrest": (
                ToolSpec(
                    name="load_qrest",
                    description="Extract qREST metadata JSON and readable TXT data from a binary .qrest file.",
                    parameters={
                        "input_qrest": "Path to the input .qrest file.",
                        "output_metadata_json": "Path where metadata JSON should be written.",
                        "output_data_txt": "Path where readable data TXT should be written.",
                    },
                ),
                self._qrest_tools.load_qrest,
            ),
        }

    def list_specs(self) -> list[ToolSpec]:
        return [spec for spec, _ in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, str | Path]) -> Any:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        _, function = self._tools[name]
        return function(**arguments)

