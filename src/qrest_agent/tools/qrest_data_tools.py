from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from qrest_agent.resources import qrest_tool_path


@dataclass(slots=True)
class ToolResult:
    ok: bool
    command: list[str]
    stdout: str
    stderr: str
    outputs: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "outputs": self.outputs,
        }


class QrestDataTools:
    """Agent-callable wrappers around qREST data command-line tools."""

    def generate_qrest(self, metadata_json: str | Path, data_txt: str | Path, output_qrest: str | Path) -> ToolResult:
        command = [
            str(qrest_tool_path("data_generator")),
            str(Path(metadata_json)),
            str(Path(data_txt)),
            str(Path(output_qrest)),
        ]
        return _run(command, outputs={"qrest": str(output_qrest)})

    def load_qrest(self, input_qrest: str | Path, output_metadata_json: str | Path, output_data_txt: str | Path) -> ToolResult:
        command = [
            str(qrest_tool_path("data_loader")),
            str(Path(input_qrest)),
            str(Path(output_metadata_json)),
            str(Path(output_data_txt)),
        ]
        return _run(
            command,
            outputs={"metadata_json": str(output_metadata_json), "data_txt": str(output_data_txt)},
        )


def _run(command: list[str], outputs: dict[str, str]) -> ToolResult:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    return ToolResult(
        ok=completed.returncode == 0,
        command=command,
        stdout=completed.stdout,
        stderr=completed.stderr,
        outputs=outputs,
    )

