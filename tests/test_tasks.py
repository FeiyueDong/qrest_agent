from __future__ import annotations

from pathlib import Path

from qrest_agent.agent.agent import QrestAgent
from qrest_agent.agent.task_handlers import (
    QrestDataGenerationHandler,
    QrestDataLoadingHandler,
    TaskHandlerRegistry,
    create_default_handler_registry,
)
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


def test_default_handler_registry_registers_qrest_data_generation(tmp_path: Path) -> None:
    agent = QrestAgent(tool_registry=ToolRegistry(artifact_root=tmp_path / "artifacts"))

    registry = create_default_handler_registry(agent, "handler-session")

    assert registry.list_names() == ["qrest_data_generation", "qrest_data_loading"]
    assert isinstance(registry.get("qrest_data_generation"), QrestDataGenerationHandler)
    assert isinstance(registry.get("qrest_data_loading"), QrestDataLoadingHandler)


def test_rule_plan_detects_generation_task() -> None:
    agent = QrestAgent()
    plan = agent.plan("严格检查 metadata.json 和 data.txt 能不能生成 qREST")

    assert plan.action == "task"
    assert plan.skill_name == "qrest_data_generation"
    assert plan.source == "rule"
    assert plan.tool_arguments["mode"] == "preflight"
    assert plan.tool_arguments["strict"] is True
    assert plan.tool_arguments["metadata_json"] == "metadata.json"
    assert plan.tool_arguments["data_txt"] == "data.txt"


def test_rule_plan_detects_loading_task() -> None:
    agent = QrestAgent()
    plan = agent.plan("解析 input.qrest 并导入当前项目")

    assert plan.action == "task"
    assert plan.skill_name == "qrest_data_loading"
    assert plan.tool_arguments["input_qrest"] == "input.qrest"


def test_rule_plan_falls_back_to_extract_for_plain_text() -> None:
    agent = QrestAgent()
    plan = agent.plan("项目名称为 Demo。")
    assert plan.action == "extract"
    assert plan.skill_name is None


def test_agent_executes_preflight_task_and_logs(tmp_path: Path, artifact_dir: Path) -> None:
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
    assert result.plan.action == "task"
    assert result.task_result is not None
    assert result.task_result["skill"] == "qrest_data_generation"
    assert result.task_result["mode"] == "preflight"
    assert result.task_result["preflight"]["ok"]
    assert "可以生成，但输入并非完全一致" in result.response
    assert any(item["name"] == "qrest_data_generation_task_log.json" for item in artifacts)
    log_path = tmp_path / "artifacts" / "task-preflight" / "qrest_data_generation_task_log.json"
    assert '"status": "warning"' in log_path.read_text(encoding="utf-8")


def test_agent_executes_loading_task_and_logs(tmp_path: Path, artifact_dir: Path) -> None:
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
    assert result.plan.action == "task"
    assert result.task_result is not None
    assert result.task_result["skill"] == "qrest_data_loading"
    assert result.task_result["load"]["ok"]
    assert result.report.ready
    assert "已将解析出的 metadata 导入当前会话" in result.response
    assert any(item["name"] == "loaded_metadata.json" for item in artifacts)
    assert any(item["name"] == "loaded_data.txt" for item in artifacts)
    assert any(item["name"] == "qrest_data_loading_task_log.json" for item in artifacts)
    log_path = tmp_path / "artifacts" / "task-loading" / "qrest_data_loading_task_log.json"
    assert '"status": "success"' in log_path.read_text(encoding="utf-8")
