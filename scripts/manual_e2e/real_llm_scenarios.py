"""真实 LLM E2E 场景（方案 §59-§60 + 规范化/推导方案 §16）。

用法：
  env PYTHONPATH=src .venv/bin/python scripts/manual_e2e/real_llm_scenarios.py [model] [scenario...]

默认模型 qwen3:4b-instruct；场景名：ascii/footprint/elevation/channels/correction/
hallucination/qrest_ask，或 all。

结果自动写入 test_outputs/llm_e2e/<model>.json，并打印一行汇总。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from qrest_agent.agent.agent import QrestAgent
from qrest_agent.llm.clients import OllamaClient

MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen3:4b-instruct"
SCENES = sys.argv[2:] or ["all"]


def run_scenario(name: str, text: str, files: list[str] | None = None, prior: str | None = None) -> dict[str, Any]:
    client = OllamaClient(model=MODEL, retries=0)
    agent = QrestAgent(llm_client=client)
    if prior:
        agent.run_turn(text=prior)
    start = time.time()
    result = agent.run_turn(text=text, files=files)
    elapsed = round(time.time() - start, 1)
    payload: dict[str, Any] = {
        "scenario": name,
        "seconds": elapsed,
        "intent": result.plan.intent if result.plan else None,
        "skills": result.plan.skills if result.plan else [],
        "actions": [a.to_dict() for a in result.plan.actions] if result.plan else [],
        "extractor": result.extractor,
        "fallback_reason": result.fallback_reason,
        "rejected": result.rejected_candidates,
        "records": {
            path: {"value": state.value, "status": state.status}
            for path, state in sorted(agent.working_state.records.items())
            if state.value is not None
        },
        "facts": {
            path: {"value": state.value, "status": state.status}
            for path, state in sorted(agent.working_state.facts.items())
        },
        "response": result.response[:400],
    }
    return payload


def summarize(model: str, outputs: list[dict[str, Any]]) -> dict[str, Any]:
    llm_turns = sum(1 for item in outputs if item.get("extractor") == "llm")
    rule_turns = sum(1 for item in outputs if item.get("extractor") == "rule")
    fallbacks = [item["scenario"] for item in outputs if item.get("fallback_reason")]
    rejected = sum(len(item.get("rejected") or []) for item in outputs)
    fact_scenes = [item["scenario"] for item in outputs if item.get("facts")]
    return {
        "model": model,
        "scenarios": len(outputs),
        "llm_extractor": llm_turns,
        "rule_fallback": rule_turns,
        "fallback_scenarios": fallbacks,
        "rejected_candidates": rejected,
        "scenes_with_facts": fact_scenes,
        "total_seconds": round(sum(item.get("seconds", 0) for item in outputs), 1),
    }


def main() -> None:
    wanted = set(SCENES)
    all_scenes = wanted == {"all"}
    outputs: list[dict[str, Any]] = []
    print(f"# model: {MODEL}", flush=True)

    if all_scenes or "ascii" in wanted:
        outputs.append(run_scenario(
            "ascii_structural_type",
            "结构为钢框架。项目名称为昆明大楼。",
        ))
    if all_scenes or "footprint" in wanted:
        outputs.append(run_scenario(
            "footprint_derivation",
            "建筑平面呈矩形，尺寸约42m × 25.2m。",
        ))
    if all_scenes or "elevation" in wanted:
        outputs.append(run_scenario(
            "elevation_derivation",
            "地上14层，地下2层，首层4.5m，标准层3.3m，地下首层层高2.7m。",
        ))
    if all_scenes or "channels" in wanted:
        outputs.append(run_scenario(
            "channel_num_only",
            "系统共布置18个传感器。",
        ))
    if all_scenes or "correction" in wanted:
        outputs.append(run_scenario(
            "correction_confirmed",
            "前面的长度不对，改为46.9m。",
            prior="建筑长度为42m，宽度25.2m，矩形平面。",
        ))
    if all_scenes or "hallucination" in wanted:
        outputs.append(run_scenario(
            "no_invented_structural_type",
            "这是一栋昆明的建筑，主要用于办公。",
        ))
    if all_scenes or "qrest_ask" in wanted:
        outputs.append(run_scenario(
            "qrest_generation_missing_data",
            "用当前项目状态生成 qREST",
        ))

    out_dir = Path("test_outputs") / "llm_e2e"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{MODEL.replace(':', '_')}.json"
    out_path.write_text(json.dumps(outputs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summarize(MODEL, outputs), ensure_ascii=False, indent=2), flush=True)
    print(f"# detail saved: {out_path}", flush=True)


if __name__ == "__main__":
    main()
