from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qrest_agent.agent.extractor import LLMExtractor, RuleBasedExtractor
from qrest_agent.core.models import Candidate
from qrest_agent.ingestion.sources import SourceChunk
from qrest_agent.llm.clients import BaseLLMClient
from qrest_agent.resources import llm_benchmark_cases_path


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    description: str
    text: str
    expected: dict[str, Any]
    must_not_extract: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkCase":
        return cls(
            case_id=data["case_id"],
            description=data.get("description", ""),
            text=data["text"],
            expected=data.get("expected", {}),
            must_not_extract=data.get("must_not_extract", []),
        )


def load_benchmark_cases(path: str | Path | None = None) -> list[BenchmarkCase]:
    cases_path = Path(path) if path is not None else llm_benchmark_cases_path()
    return [BenchmarkCase.from_dict(item) for item in json.loads(cases_path.read_text(encoding="utf-8"))]


def run_rule_benchmark(cases: list[BenchmarkCase] | None = None) -> dict[str, Any]:
    return _run_benchmark("rule", RuleBasedExtractor(), cases or load_benchmark_cases())


def run_llm_benchmark(model: str, client: BaseLLMClient, cases: list[BenchmarkCase] | None = None) -> dict[str, Any]:
    return _run_benchmark(model, LLMExtractor(client), cases or load_benchmark_cases())


def _run_benchmark(model_name: str, extractor: Any, cases: list[BenchmarkCase]) -> dict[str, Any]:
    case_results: list[dict[str, Any]] = []
    totals = {
        "expected": 0,
        "correct": 0,
        "missing": 0,
        "wrong": 0,
        "forbidden_extracted": 0,
        "json_failures": 0,
    }

    for case in cases:
        chunk = SourceChunk(source_id=case.case_id, location="benchmark", text=case.text, source_type="benchmark")
        json_valid = True
        error: str | None = None
        try:
            candidates = extractor.extract([chunk])
        except Exception as exc:
            candidates = []
            json_valid = False
            error = str(exc)

        evaluation = evaluate_candidates(candidates, case)
        if not json_valid:
            totals["json_failures"] += 1
        for key in ("expected", "correct", "missing", "wrong", "forbidden_extracted"):
            totals[key] += evaluation["counts"][key]

        case_results.append(
            {
                "case_id": case.case_id,
                "description": case.description,
                "json_valid": json_valid,
                "error": error,
                "candidates": [candidate.to_dict() for candidate in candidates],
                "evaluation": evaluation,
            }
        )

    expected_total = totals["expected"]
    accuracy = totals["correct"] / expected_total if expected_total else 1.0
    hallucination_denominator = sum(len(case.must_not_extract) for case in cases)
    hallucination_rate = (
        totals["forbidden_extracted"] / hallucination_denominator if hallucination_denominator else 0.0
    )
    json_valid_rate = (len(cases) - totals["json_failures"]) / len(cases) if cases else 1.0

    return {
        "model": model_name,
        "case_count": len(cases),
        "metrics": {
            "accuracy": accuracy,
            "hallucination_rate": hallucination_rate,
            "json_valid_rate": json_valid_rate,
            **totals,
        },
        "cases": case_results,
    }


def evaluate_candidates(candidates: list[Candidate], case: BenchmarkCase) -> dict[str, Any]:
    by_path: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        if candidate.value is None:
            continue
        by_path.setdefault(candidate.field_path, []).append(candidate)

    expected_results: dict[str, Any] = {}
    correct = 0
    missing = 0
    wrong = 0
    for field_path, expected_value in case.expected.items():
        predicted = by_path.get(field_path, [])
        predicted_values = [candidate.value for candidate in predicted]
        if not predicted:
            status = "missing"
            missing += 1
        elif any(_values_equal(value, expected_value) for value in predicted_values):
            status = "correct"
            correct += 1
        else:
            status = "wrong"
            wrong += 1
        expected_results[field_path] = {
            "status": status,
            "expected": expected_value,
            "predicted": predicted_values,
        }

    forbidden = {
        field_path: [candidate.value for candidate in by_path[field_path]]
        for field_path in case.must_not_extract
        if field_path in by_path
    }

    return {
        "expected": expected_results,
        "forbidden_extracted": forbidden,
        "counts": {
            "expected": len(case.expected),
            "correct": correct,
            "missing": missing,
            "wrong": wrong,
            "forbidden_extracted": len(forbidden),
        },
    }


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, int | float) and isinstance(right, int | float):
        return abs(float(left) - float(right)) <= 1e-9
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            return False
        return all(_values_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return False
        return all(_values_equal(item_left, item_right) for item_left, item_right in zip(left, right))
    return left == right

