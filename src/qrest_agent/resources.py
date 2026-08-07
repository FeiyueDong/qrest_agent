from __future__ import annotations

import os
import platform
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resource_root() -> Path:
    override = os.environ.get("QREST_AGENT_RESOURCE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return project_root() / "resources"


def qrest_data_root() -> Path:
    return resource_root() / "qrest_data"


def qrest_examples_root() -> Path:
    return qrest_data_root() / "examples"


def qrest_metadata_policy_path() -> Path:
    return qrest_examples_root() / "metadata.json"


def qrest_docs_root() -> Path:
    return qrest_data_root() / "docs"


def qrest_schema_path() -> Path:
    return qrest_data_root() / "schema" / "metadata_schema.json"


def llm_resource_root() -> Path:
    return resource_root() / "llm"


def llm_benchmark_cases_path() -> Path:
    return llm_resource_root() / "benchmark_cases.json"


def llm_provider_config_path() -> Path:
    return llm_resource_root() / "provider_config.json"


def qrest_tool_path(tool_name: str) -> Path:
    system = platform.system().lower()
    if system != "linux":
        raise RuntimeError(f"bundled qREST data tools are currently available for linux only, got {system}")
    path = qrest_data_root() / "tools" / "linux" / "bin" / tool_name
    if not path.exists():
        raise FileNotFoundError(f"qREST data tool not found: {path}")
    return path


def list_qrest_examples() -> list[Path]:
    root = qrest_examples_root()
    if not root.exists():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir())
