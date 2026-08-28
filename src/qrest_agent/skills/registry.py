from __future__ import annotations

import json
import re
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
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "root": str(self.root),
            "instructions": self.instructions,
            "policy": self.policy,
            "description": self.description,
        }

    def summary(self) -> dict[str, str]:
        return {"name": self.name, "description": self.description}


class SkillRegistry:
    """发现并加载 repo-native Skill。

    SKILL.md 支持 YAML 风格的 frontmatter（--- 块），用于描述性元数据：
        ---
        name: building_info
        description: 建筑位置、结构类型、尺寸、标高等工程信息
        ---
    description 供主 Agent 在动态选择 Skill 时查看（设计文档 §7）。
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else skills_root()

    def list_names(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(path.name for path in self.root.iterdir() if (path / "SKILL.md").is_file())

    def list_skills(self) -> list[SkillDefinition]:
        return [self.load(name) for name in self.list_names()]

    def summaries(self) -> list[dict[str, str]]:
        """给 LLM 看的最小 Skill 摘要（动态选择用）。"""
        return [skill.summary() for skill in self.list_skills()]

    def load(self, name: str) -> SkillDefinition:
        skill_dir = self.root / name
        instructions_path = skill_dir / "SKILL.md"
        if not instructions_path.is_file():
            raise KeyError(f"unknown skill: {name}")
        policy_path = skill_dir / "tool_policy.json"
        policy: dict[str, Any] = {}
        if policy_path.is_file():
            policy = json.loads(policy_path.read_text(encoding="utf-8"))

        raw = instructions_path.read_text(encoding="utf-8")
        metadata, body = _parse_frontmatter(raw)
        return SkillDefinition(
            name=name,
            root=skill_dir,
            instructions=body,
            policy=policy,
            description=str(metadata.get("description") or _heading_description(body)),
        )


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """解析 SKILL.md 头部的 --- frontmatter 块；无 frontmatter 时原样返回。"""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return {}, text
    lines = stripped.splitlines()
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, text
    metadata: dict[str, Any] = {}
    for line in lines[1:end]:
        match = re.match(r"^([A-Za-z0-9_]+)s*:s*(.*)$", line.strip())
        if match:
            metadata[match.group(1)] = match.group(2).strip().strip("\"'")
    return metadata, "\n".join(lines[end + 1 :]).strip()


def _heading_description(text: str) -> str:
    first = next((line for line in text.splitlines() if line.strip()), "")
    return first.lstrip("#").strip()
