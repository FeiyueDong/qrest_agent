from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from qrest_agent.storage.artifacts import ArtifactManager
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
    def __init__(self, artifact_root: str | Path | None = None) -> None:
        self._qrest_tools = QrestDataTools()
        self.artifacts = ArtifactManager(artifact_root)
        self._tools: dict[str, tuple[ToolSpec, Callable[..., Any]]] = {
            "generate_qrest": (
                ToolSpec(
                    name="generate_qrest",
                    description="Generate a binary .qrest file from qREST metadata JSON and time-series TXT data.",
                    parameters={
                        "metadata_json": "Path to qREST metadata JSON.",
                        "data_txt": "Path to time-major text data.",
                        "output_qrest": "Path where the generated .qrest file should be written. Optional when session_id is supplied.",
                        "strict": "Optional bool. Treat preflight warnings as blocking errors when true.",
                        "session_id": "Optional session id for managed artifact output.",
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
                        "output_metadata_json": "Path where metadata JSON should be written. Optional when session_id is supplied.",
                        "output_data_txt": "Path where readable data TXT should be written. Optional when session_id is supplied.",
                        "compare_metadata_json": "Optional metadata JSON path to compare against loaded metadata.",
                        "session_id": "Optional session id for managed artifact output.",
                    },
                ),
                self._qrest_tools.load_qrest,
            ),
        }

    def list_specs(self) -> list[ToolSpec]:
        return [spec for spec, _ in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        _, function = self._tools[name]
        prepared = self._prepare_arguments(name, dict(arguments))
        return function(**prepared)

    def _prepare_arguments(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        session_id = arguments.pop("session_id", None)
        if session_id is None:
            return arguments

        if name == "generate_qrest":
            arguments.setdefault("output_qrest", self.artifacts.path(str(session_id), "generated.qrest"))
        elif name == "load_qrest":
            arguments.setdefault("output_metadata_json", self.artifacts.path(str(session_id), "loaded_metadata.json"))
            arguments.setdefault("output_data_txt", self.artifacts.path(str(session_id), "loaded_data.txt"))
        return arguments
