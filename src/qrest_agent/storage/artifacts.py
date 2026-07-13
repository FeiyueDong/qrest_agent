from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from qrest_agent.resources import project_root


class ArtifactManager:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else project_root() / "artifacts"
        self.root.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        path = self.root / _safe_part(session_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def path(self, session_id: str, *parts: str) -> Path:
        current = self.session_dir(session_id)
        for part in parts:
            current = current / _safe_part(part)
        current.parent.mkdir(parents=True, exist_ok=True)
        return current

    def write_json(self, session_id: str, name: str, payload: dict[str, Any]) -> Path:
        path = self.path(session_id, name)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def write_text(self, session_id: str, name: str, text: str) -> Path:
        path = self.path(session_id, name)
        path.write_text(text, encoding="utf-8")
        return path

    def list(self, session_id: str) -> list[dict[str, Any]]:
        root = self.session_dir(session_id)
        items: list[dict[str, Any]] = []
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            items.append(
                {
                    "name": path.relative_to(root).as_posix(),
                    "path": str(path),
                    "size": path.stat().st_size,
                }
            )
        return items


def _safe_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    cleaned = cleaned.strip("._")
    if not cleaned:
        return "artifact"
    if cleaned in {".", ".."}:
        return "artifact"
    return cleaned
