from __future__ import annotations

from pathlib import Path

from qrest_agent.skills import SkillRegistry
from tests.conftest import write_json


def test_loads_repo_native_skills(artifact_dir: Path) -> None:
    registry = SkillRegistry()

    generation = registry.load("qrest_data_generation")
    loading = registry.load("qrest_data_loading")

    write_json(
        artifact_dir / "skills" / "repo_native_skills.json",
        {
            "names": registry.list_names(),
            "skills": [generation.to_dict(), loading.to_dict()],
        },
    )

    assert "qrest_data_generation" in registry.list_names()
    assert "qrest_data_loading" in registry.list_names()
    assert "Do not invent missing engineering metadata" in generation.instructions
    assert generation.policy["tools"]["preflight"] == "preflight_generate_qrest"
    assert loading.policy["tools"]["load"] == "load_qrest"
