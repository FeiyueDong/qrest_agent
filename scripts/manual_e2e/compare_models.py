"""跨模型 E2E 结果对比（读取 test_outputs/llm_e2e/*.json）。

用法：env PYTHONPATH=src .venv/bin/python scripts/manual_e2e/compare_models.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT_DIR = Path("test_outputs") / "llm_e2e"

KEY_FIELDS = [
    "BuildingInfo.StructuralType",
    "BuildingInfo.ProjectName",
    "BuildingInfo.StructuralFootprint.Shape",
    "BuildingInfo.StructuralFootprint.Parameters",
    "BuildingInfo.StructuralFootprint.BoundingBox",
    "BuildingInfo.ElevationNum",
    "BuildingInfo.Elevation",
    "InstrumentInfo.ChannelNum",
    "InstrumentInfo.Channels",
]


def field_summary(records: dict[str, Any], path: str) -> str:
    record = records.get(path)
    if record is None:
        return "-"
    value = record["value"]
    if path.endswith("Elevation"):
        return f"{record['status']}:{len(value)}项" if isinstance(value, list) else f"{record['status']}:{value}"
    if path.endswith("BoundingBox") or path.endswith("Parameters"):
        return f"{record['status']}:{json.dumps(value, ensure_ascii=False)}"
    return f"{record['status']}:{value}"


def main() -> None:
    files = sorted(OUT_DIR.glob("*.json"))
    if not files:
        print(f"no results in {OUT_DIR}")
        return

    rows: list[dict[str, Any]] = []
    for path in files:
        scenarios = json.loads(path.read_text(encoding="utf-8"))
        model = path.stem.replace("_", ":")
        for item in scenarios:
            records = item.get("records", {})
            facts = item.get("facts", {})
            rows.append({
                "model": model,
                "scenario": item["scenario"],
                "extractor": item.get("extractor"),
                "fallback": bool(item.get("fallback_reason")),
                "rejected": len(item.get("rejected") or []),
                "facts": len(facts),
                "seconds": item.get("seconds"),
                "StructuralType": field_summary(records, "BuildingInfo.StructuralType"),
                "ProjectName": field_summary(records, "BuildingInfo.ProjectName"),
                "Parameters": field_summary(records, "BuildingInfo.StructuralFootprint.Parameters"),
                "BoundingBox": field_summary(records, "BuildingInfo.StructuralFootprint.BoundingBox"),
                "Elevation": field_summary(records, "BuildingInfo.Elevation"),
                "ElevationNum": field_summary(records, "BuildingInfo.ElevationNum"),
                "ChannelNum": field_summary(records, "InstrumentInfo.ChannelNum"),
                "Channels": field_summary(records, "InstrumentInfo.Channels"),
            })

    models = sorted({row["model"] for row in rows})
    scenarios = sorted({row["scenario"] for row in rows}, key=lambda s: list({r["scenario"] for r in rows}).index(s))

    # 汇总表
    print("| model | scenarios | llm | rule_fb | rejected | facts_scenes | total_s |")
    print("|---|---|---|---|---|---|---|")
    for model in models:
        model_rows = [row for row in rows if row["model"] == model]
        llm = sum(1 for row in model_rows if row["extractor"] == "llm")
        fb = [row["scenario"] for row in model_rows if row["fallback"]]
        rejected = sum(row["rejected"] for row in model_rows)
        facts_scenes = [row["scenario"] for row in model_rows if row["facts"] > 0]
        total = sum(row["seconds"] or 0 for row in model_rows)
        print(f"| {model} | {len(model_rows)} | {llm} | {','.join(fb) or '-'} | {rejected} | {','.join(facts_scenes) or '-'} | {round(total)} |")

    # 场景明细表
    print()
    print("| model | scenario | extractor | rejected | facts | key fields |")
    print("|---|---|---|---|---|---|")
    for row in rows:
        keys = []
        for key in ["StructuralType", "ProjectName", "Parameters", "BoundingBox", "ElevationNum", "Elevation", "ChannelNum", "Channels"]:
            value = row.get(key)
            if value and value != "-":
                keys.append(f"{key}={value}")
        print(f"| {row['model']} | {row['scenario']} | {row['extractor']} | {row['rejected']} | {row['facts']} | {'; '.join(keys) or '-'} |")


if __name__ == "__main__":
    main()
