from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonProjectRepository:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, session_id: str, payload: dict[str, Any]) -> Path:
        path = self.root / f"{session_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load(self, session_id: str) -> dict[str, Any]:
        path = self.root / f"{session_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

