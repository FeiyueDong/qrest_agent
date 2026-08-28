from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qrest_agent.resources import skills_root


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    name: str
    root: Path
    instructions: str
    policy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "root": str(self.root),
            "instructions": self.instructions,
            "policy": self.policy,
        }


class SkillRegistry:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else skills_root()

    def list_names(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(path.name for path in self.root.iterdir() if (path / "SKILL.md").is_file())

    def list_skills(self) -> list[SkillDefinition]:
        return [self.load(name) for name in self.list_names()]

    def load(self, name: str) -> SkillDefinition:
        skill_dir = self.root / name
        instructions_path = skill_dir / "SKILL.md"
        if not instructions_path.is_file():
            raise KeyError(f"unknown skill: {name}")
        policy_path = skill_dir / "tool_policy.json"
        policy: dict[str, Any] = {}
        if policy_path.is_file():
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
        return SkillDefinition(
            name=name,
            root=skill_dir,
            instructions=instructions_path.read_text(encoding="utf-8"),
            policy=policy,
        )
