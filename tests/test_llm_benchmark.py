from __future__ import annotations

from pathlib import Path
from typing import Any

from qrest_agent.agent.prompts import EXTRACTION_SYSTEM_PROMPT
from qrest_agent.agent.extractor import LLMExtractor
from qrest_agent.llm.benchmark import BenchmarkCase, evaluate_candidates, load_benchmark_cases, run_rule_benchmark
from qrest_agent.llm.clients import _parse_json_object
from qrest_agent.core.models import Candidate
from qrest_agent.resources import llm_benchmark_cases_path, llm_provider_config_path
from tests.conftest import write_json


class NumericStringClient:
    model = "numeric-string"

    def complete_json(self, messages, schema_hint=None):  # type: ignore[no-untyped-def]
        return {
            "candidates": [
                {
                    "field_path": "DataInfo.DT",
                    "value": "0.02",
                    "status": "extracted",
                    "confidence": 0.9,
                    "evidence": ["采样时间间隔：0.02 s"],
                },
                {
                    "field_path": "DataInfo.NPTS",
                    "value": "30000",
                    "status": "extracted",
                    "confidence": 0.9,
                    "evidence": ["数据点数：30000"],
                },
                {
                    "field_path": "DataInfo.Corrected",
                    "value": "null",
                    "status": "missing",
                    "confidence": 0.0,
                    "evidence": [],
                },
            ]
        }


def test_prompt_lists_allowed_field_paths() -> None:
    assert "Allowed field_path values" in EXTRACTION_SYSTEM_PROMPT
    assert "- BuildingInfo.ProjectName" in EXTRACTION_SYSTEM_PROMPT
    assert "Never put the extracted value in field_path" in EXTRACTION_SYSTEM_PROMPT


def test_parse_json_object_extracts_fenced_json() -> None:
    content = "Thinking...\n```json\n{\"candidates\": []}\n```\nDone."

    parsed = _parse_json_object(content)

    assert parsed == {"candidates": []}


def test_parse_json_object_strips_ansi_sequences() -> None:
    content = "\x1b[?25l{\"candidates\": []}\x1b[?25h"

    parsed = _parse_json_object(content)

    assert parsed == {"candidates": []}


def test_parse_json_object_repairs_common_model_json_issues() -> None:
    content = '{"candidates":[{"field_path":"DataInfo.DT","value":"0.02","status":"extracted","confidence": 0","evidence":[{"text":"line one\nline two"}]}]}'

    parsed = _parse_json_object(content)

    assert parsed["candidates"][0]["confidence"] == 0
    assert "line two" in parsed["candidates"][0]["evidence"][0]["text"]


def test_load_benchmark_cases_resource(artifact_dir: Path) -> None:
    cases = load_benchmark_cases()
    write_json(
        artifact_dir / "llm" / "benchmark_case_summary.json",
        {
            "case_file": str(llm_benchmark_cases_path()),
            "provider_config": str(llm_provider_config_path()),
            "case_ids": [case.case_id for case in cases],
        },
    )

    assert len(cases) >= 3
    assert {case.case_id for case in cases} >= {
        "simple_explicit_metadata",
        "missing_sampling_interval",
        "explicit_chinese_metadata",
    }


def test_rule_benchmark_outputs_metrics(artifact_dir: Path) -> None:
    result = run_rule_benchmark()
    write_json(artifact_dir / "llm" / "rule_benchmark.json", result)

    assert result["metrics"]["accuracy"] == 1.0
    assert result["metrics"]["hallucination_rate"] == 0.0
    assert result["metrics"]["json_valid_rate"] == 1.0


def test_evaluate_candidates_detects_forbidden_extraction() -> None:
    case = BenchmarkCase(
        case_id="missing",
        description="",
        text="",
        expected={"BuildingInfo.ProjectName": "A"},
        must_not_extract=["DataInfo.DT"],
    )
    candidates = [
        Candidate(field_path="BuildingInfo.ProjectName", value="A"),
        Candidate(field_path="DataInfo.DT", value=0.02),
    ]

    result = evaluate_candidates(candidates, case)

    assert result["counts"]["correct"] == 1
    assert result["counts"]["forbidden_extracted"] == 1
    assert result["forbidden_extracted"]["DataInfo.DT"] == [0.02]


def test_llm_extractor_normalizes_numeric_strings_and_missing_nulls() -> None:
    from qrest_agent.ingestion.sources import SourceChunk

    chunk = SourceChunk(source_id="test", location="chunk", text="采样时间间隔：0.02 s。数据点数：30000。")
    candidates = LLMExtractor(NumericStringClient()).extract([chunk])
    by_path = {candidate.field_path: candidate for candidate in candidates}

    assert by_path["DataInfo.DT"].value == 0.02
    assert by_path["DataInfo.NPTS"].value == 30000
    assert by_path["DataInfo.Corrected"].value is None
