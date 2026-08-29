"""小模型稳定性测试：同一模型同一场景重复 N 次，观察波动。

用法：
  env PYTHONPATH=src .venv/bin/python scripts/manual_e2e/stability_test.py [model] [runs] [scenario...]

默认 qwen3:4b-instruct × 3，场景 ascii footprint elevation correction。
结果写入 test_outputs/llm_e2e/<model>_stability.json。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from qrest_agent.agent.agent import QrestAgent
from qrest_agent.llm.clients import OllamaClient

MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen3:4b-instruct"
RUNS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
SCENES = sys.argv[3:] or ["ascii", "footprint", "elevation", "correction"]

SCENARIO_ARGS: dict[str, dict[str, Any]] = {
    "ascii": {"text": "结构为钢框架。项目名称为昆明大楼。"},
    "footprint": {"text": "建筑平面呈矩形，尺寸约42m × 25.2m。"},
    "elevation": {"text": "地上14层，地下2层，首层4.5m，标准层3.3m，地下首层层高2.7m。"},
    "correction": {"text": "前面的长度不对，改为46.9m。", "prior": "建筑长度为42m，宽度25.2m，矩形平面。"},
    "channels": {"text": "系统共布置18个传感器。"},
    "hallucination": {"text": "这是一栋昆明的建筑，主要用于办公。"},
}


def run_once(name: str, client: OllamaClient) -> dict[str, Any]:
    agent = QrestAgent(llm_client=client)
    args = SCENARIO_ARGS[name]
    if args.get("prior"):
        agent.run_turn(text=args["prior"])
    result = agent.run_turn(text=args["text"])
    return {
        "scenario": name,
        "extractor": result.extractor,
        "fallback_reason": result.fallback_reason,
        "rejected": result.rejected_candidates,
        "records": {
            path: {"value": state.value, "status": state.status}
            for path, state in sorted(agent.working_state.records.items())
            if state.value is not None and path not in {"Header", "Version", "Units"}
        },
        "facts": {
            path: {"value": state.value, "status": state.status}
            for path, state in sorted(agent.working_state.facts.items())
        },
    }


def main() -> None:
    client = OllamaClient(model=MODEL, retries=2)
    all_runs: list[dict[str, Any]] = []
    for run in range(1, RUNS + 1):
        for scene in SCENES:
            if scene not in SCENARIO_ARGS:
                print(f"skip unknown scenario: {scene}")
                continue
            print(f"# run {run}/{RUNS} scene {scene} ({MODEL})", flush=True)
            all_runs.append({"run": run, **run_once(scene, client)})

    out_dir = Path("test_outputs") / "llm_e2e"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{MODEL.replace(':', '_')}_stability.json"
    out_path.write_text(json.dumps(all_runs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"# saved: {out_path}", flush=True)


if __name__ == "__main__":
    main()
