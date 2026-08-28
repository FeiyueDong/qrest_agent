from __future__ import annotations

from pathlib import Path

from qrest_agent.agent.agent import QrestAgent
from qrest_agent.agent.planner import ActionSpec, TurnPlan, rule_plan
from qrest_agent.agent.tasks import detect_task_intent, extract_paths
from qrest_agent.agent.tool_registry import ToolRegistry
from qrest_agent.resources import qrest_examples_root
from tests.conftest import write_json


def test_detects_qrest_data_generation_intent() -> None:
    intent = detect_task_intent("严格检查 metadata.json 和 data.txt 能不能生成 qREST")

    assert intent is not None
    assert intent.name == "qrest_data_generation"
    assert intent.skill_name == "qrest_data_generation"
    assert intent.mode == "preflight"
    assert intent.strict
    assert intent.metadata_json == "metadata.json"
    assert intent.data_txt == "data.txt"


def test_detects_qrest_data_loading_intent() -> None:
    intent = detect_task_intent("解析 input.qrest 并对比 metadata.json 后导入当前项目")

    assert intent is not None
    assert intent.name == "qrest_data_loading"
    assert intent.skill_name == "qrest_data_loading"
    assert intent.mode == "import"
    assert intent.input_qrest == "input.qrest"
    assert intent.compare_metadata_json == "metadata.json"


def test_extract_paths_keeps_order_and_deduplicates() -> None:
    paths = extract_paths("检查 ./a/metadata.json 和 ./b/data.txt，输出 output.qrest，再看 ./b/data.txt")

    assert paths == ["./a/metadata.json", "./b/data.txt", "output.qrest"]


def test_rule_plan_detects_generation_task() -> None:
    # 显式 metadata.json：直接用文件，不 export 当前状态
    plan = rule_plan("检查 metadata.json 和 data.txt 能不能生成 qREST", {"session_id": "s1"})

    assert plan.intent == "qrest_task"
    assert plan.skills == ["qrest_data"]
    assert plan.actions == [
        ActionSpec(
            type="tool",
            tool="preflight_generate_qrest",
            arguments={"metadata_json": "metadata.json", "data_txt": "data.txt", "session_id": "s1"},
        ),
    ]
    assert plan.source == "rule"


def test_rule_plan_generation_from_current_state_exports_first() -> None:
    plan = rule_plan("用当前项目状态和 data.txt 直接生成 qREST", {"session_id": "s1"})

    assert plan.intent == "qrest_task"
    assert plan.actions == [
        ActionSpec(type="export", arguments={}),
        ActionSpec(
            type="tool",
            tool="generate_qrest",
            arguments={"metadata_json": "$export.metadata_json", "data_txt": "data.txt", "session_id": "s1"},
        ),
    ]


def test_rule_plan_detects_loading_task() -> None:
    plan = rule_plan("解析 input.qrest 并导入当前项目", {"session_id": "s1"})

    assert plan.intent == "qrest_task"
    assert plan.actions[0] == ActionSpec(type="tool", tool="load_qrest", arguments={"input_qrest": "input.qrest", "session_id": "s1"})
    assert plan.actions[1] == ActionSpec(type="extract", arguments={"files": ["$tool:load_qrest.metadata_json"]})


def test_rule_plan_generation_without_data_asks_user() -> None:
    plan = rule_plan("用当前项目状态生成 qREST", {"session_id": "s1"})

    assert plan.intent == "qrest_task"
    assert plan.need_user_input is True
    assert plan.actions == [
        ActionSpec(type="export", arguments={}),
        ActionSpec(
            type="ask",
            arguments={
                "reason": "missing_data_txt",
                "request": "请提供用于生成 qREST 的时程数据文件 data.txt（文件路径或上传附件）",
                "expected": "path_or_attachment",
            },
        ),
    ]


def test_rule_plan_falls_back_to_collect_metadata_for_plain_text() -> None:
    plan = rule_plan("项目名称为 Demo。")
    assert plan.intent == "collect_metadata"
    assert plan.actions == [ActionSpec(type="extract")]
    assert plan.skills == ["metadata"]


def test_agent_executes_preflight_task_and_writes_artifacts(tmp_path: Path, artifact_dir: Path) -> None:
    agent = QrestAgent(
        tool_registry=ToolRegistry(artifact_root=tmp_path / "artifacts"),
        session_id="task-preflight",
    )
    example_dir = qrest_examples_root() / "kunming2"

    result = agent.run_turn(f"检查 {example_dir / 'metadata.json'} 和 {example_dir / 'data.txt'} 能不能生成 qREST")
    artifacts = agent.tools.artifacts.list("task-preflight")

    write_json(
        artifact_dir / "tasks" / "agent_preflight.json",
        {"result": result.to_dict(), "artifacts": artifacts},
    )

    assert result.plan is not None
    assert result.plan.intent == "qrest_task"
    preflight = result.action_results["tool:preflight_generate_qrest"]
    assert preflight["ok"] is True
    assert any("NPTS" in warning for warning in preflight["warnings"])
    assert any(item["name"] == "generate_qrest_preflight_report.json" for item in artifacts)
    assert "export" not in result.action_results


def test_agent_executes_loading_task_and_imports_metadata(tmp_path: Path, artifact_dir: Path) -> None:
    agent = QrestAgent(
        tool_registry=ToolRegistry(artifact_root=tmp_path / "artifacts"),
        session_id="task-loading",
    )
    example_dir = qrest_examples_root() / "kunming2"

    result = agent.run_turn(f"解析 {example_dir / 'kunming2.qrest'} 并导入当前项目")
    artifacts = agent.tools.artifacts.list("task-loading")

    write_json(
        artifact_dir / "tasks" / "agent_loading.json",
        {"result": result.to_dict(), "artifacts": artifacts},
    )

    assert result.plan is not None
    assert result.plan.intent == "qrest_task"
    assert result.action_results["tool:load_qrest"]["ok"] is True
    assert result.report.ready
    assert "BuildingInfo.ProjectName" in agent.working_state.records
    assert any(item["name"] == "loaded_metadata.json" for item in artifacts)
    assert any(item["name"] == "loaded_data.txt" for item in artifacts)
