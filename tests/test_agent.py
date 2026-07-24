from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from qrest_agent.agent.metadata_agent import MetadataAgent
from qrest_agent.resources import qrest_examples_root
from tests.conftest import write_json


class BadLLMClient:
    model = "bad"

    def complete_json(self, messages: list[dict[str, str]], schema_hint: dict[str, Any] | None = None) -> dict[str, Any]:
        raise ValueError("bad model output")


class UnknownPathLLMClient:
    model = "unknown-path"

    def complete_json(self, messages: list[dict[str, str]], schema_hint: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "candidates": [
                {
                    "field_path": "TestTower",
                    "value": "wrong",
                    "status": "extracted",
                    "confidence": 0.8,
                    "evidence": ["bad path"],
                }
            ]
        }


class PartialLLMClient:
    model = "partial"

    def complete_json(self, messages: list[dict[str, str]], schema_hint: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "candidates": [
                {
                    "field_path": "DataInfo.EventName",
                    "value": "LLM_EVENT",
                    "status": "extracted",
                    "confidence": 0.8,
                    "evidence": ["事件名称为 LLM_EVENT"],
                }
            ]
        }


def test_rule_based_turn_reports_missing_fields(artifact_dir: Path) -> None:
    agent = MetadataAgent()
    result = agent.run_turn("项目名称为 DemoBuilding。采样间隔为 0.02s。")

    write_json(artifact_dir / "agent" / "rule_based_missing_turn.json", result.to_dict())

    assert "BuildingInfo.ProjectName" in [item.field_path for item in result.candidates]
    assert not result.report.ready
    assert "BuildingInfo.StructuralType" in result.report.missing_required


def test_bad_llm_falls_back_to_rule_based_extractor(artifact_dir: Path) -> None:
    agent = MetadataAgent(llm_client=BadLLMClient())
    result = agent.run_turn("项目名称为 DemoBuilding。")

    write_json(artifact_dir / "agent" / "bad_llm_fallback_turn.json", result.to_dict())

    assert "BuildingInfo.ProjectName" in [item.field_path for item in result.candidates]
    assert result.extractor == "rule"
    assert result.fallback_reason is not None


def test_unknown_llm_field_path_falls_back_to_rule_based_extractor(artifact_dir: Path) -> None:
    agent = MetadataAgent(llm_client=UnknownPathLLMClient())
    result = agent.run_turn("项目名称为 DemoBuilding。")

    write_json(artifact_dir / "agent" / "unknown_path_fallback_turn.json", result.to_dict())

    assert "BuildingInfo.ProjectName" in [item.field_path for item in result.candidates]
    assert "TestTower" not in agent.state.records
    assert result.fallback_reason == "LLM extraction returned no candidates"


def test_llm_extraction_is_supplemented_by_rule_based_extractor(artifact_dir: Path) -> None:
    agent = MetadataAgent(llm_client=PartialLLMClient())
    result = agent.run_turn("项目名称为 DemoBuilding。事件名称为 LLM_EVENT。采样间隔为 0.02s。")

    write_json(artifact_dir / "agent" / "partial_llm_with_rule_supplement_turn.json", result.to_dict())

    candidate_paths = {item.field_path for item in result.candidates}
    assert result.extractor == "llm+rule"
    assert "DataInfo.EventName" in candidate_paths
    assert "BuildingInfo.ProjectName" in candidate_paths
    assert "DataInfo.DT" in candidate_paths


def test_export_artifacts_writes_metadata_and_audit_when_ready(tmp_path: Path, artifact_dir: Path) -> None:
    agent = MetadataAgent()
    agent.run_turn(files=[qrest_examples_root() / "kunming2" / "metadata.json"])
    metadata_path = tmp_path / "metadata.json"
    audit_path = tmp_path / "audit.json"

    report = agent.export_artifacts(metadata_path, audit_path)

    output_metadata = artifact_dir / "agent" / "ready_metadata.json"
    output_audit = artifact_dir / "agent" / "ready_audit.json"
    output_metadata.write_text(metadata_path.read_text(encoding="utf-8"), encoding="utf-8")
    output_audit.write_text(audit_path.read_text(encoding="utf-8"), encoding="utf-8")

    assert report.ready, report.to_dict()
    assert metadata_path.exists()
    assert audit_path.exists()
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["ready"]
    assert "BuildingInfo.ProjectName" in audit["records"]


def test_export_artifacts_writes_only_audit_when_not_ready(tmp_path: Path, artifact_dir: Path) -> None:
    agent = MetadataAgent()
    agent.run_turn("项目名称为 DemoBuilding。")
    metadata_path = tmp_path / "metadata.json"
    audit_path = tmp_path / "audit.json"

    report = agent.export_artifacts(metadata_path, audit_path)

    output_audit = artifact_dir / "agent" / "not_ready_audit.json"
    output_audit.write_text(audit_path.read_text(encoding="utf-8"), encoding="utf-8")

    assert not report.ready
    assert not metadata_path.exists()
    assert audit_path.exists()
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert not audit["ready"]
