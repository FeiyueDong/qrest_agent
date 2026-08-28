from __future__ import annotations

import json
from pathlib import Path

from qrest_agent.agent.agent import QrestAgent
from qrest_agent.agent.dialogue import ChatSession
from qrest_agent.agent.tool_registry import ToolRegistry
from qrest_agent.cli import _load_cli_defaults, main
from qrest_agent.core.models import Candidate
from qrest_agent.resources import qrest_examples_root
from tests.conftest import write_json, write_text


def test_chat_session_extracts_and_reports_missing_fields(artifact_dir: Path) -> None:
    session = ChatSession()

    result = session.handle("项目名称为 DemoBuilding。事件名称为 2025_TEST_EVENT。采样间隔为 0.02s。")
    provider_result = session.handle("/provider")
    state_result = session.handle("/state")

    write_json(artifact_dir / "dialogue" / "basic_session_transcript.json", session.to_dict())
    write_text(artifact_dir / "dialogue" / "basic_state.txt", state_result.response)

    assert "BuildingInfo.ProjectName" in session.agent.working_state.records
    assert "DataInfo.DT" in session.agent.working_state.records
    assert not result.report.ready
    assert "缺少必要信息" in result.response or "缺失" in result.response
    assert "provider=rule" in provider_result.response
    assert "当前已知字段" in state_result.response


def test_chat_session_confirm_command_updates_state(artifact_dir: Path) -> None:
    session = ChatSession()

    result = session.handle("/confirm DataInfo.NPTS 30000")

    write_json(artifact_dir / "dialogue" / "confirm_command_result.json", result.to_dict())

    record = session.agent.working_state.records["DataInfo.NPTS"]
    assert record.value == 30000
    assert record.status == "confirmed"
    assert "已确认 DataInfo.NPTS" in result.response


def test_chat_session_confirm_command_accepts_json_values() -> None:
    session = ChatSession()

    session.handle('/confirm BuildingInfo.StructuralFootprint.Parameters \'{"Length": 42.0, "Width": 25.2}\'')

    record = session.agent.working_state.records["BuildingInfo.StructuralFootprint.Parameters"]
    assert record.value == {"Length": 42.0, "Width": 25.2}


def test_cli_chat_scripted_messages_write_transcript(tmp_path: Path, artifact_dir: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    transcript = tmp_path / "chat_transcript.json"

    exit_code = main(
        [
            "chat",
            "--provider",
            "rule",
            "--message",
            "项目名称为 DemoBuilding。采样间隔为 0.02s。",
            "--message",
            "/confirm DataInfo.NPTS 30000",
            "--message",
            "/state",
            "--transcript",
            str(transcript),
        ]
    )
    captured = capsys.readouterr()

    artifact_transcript = artifact_dir / "dialogue" / "cli_chat_transcript.json"
    artifact_output = artifact_dir / "dialogue" / "cli_chat_output.txt"
    artifact_transcript.write_text(transcript.read_text(encoding="utf-8"), encoding="utf-8")
    write_text(artifact_output, captured.out)

    payload = json.loads(transcript.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert "> /state" in captured.out
    assert payload["turns"]
    assert "DataInfo.NPTS" in payload["records"]
    assert payload["runtime"]["provider"] == "rule"


def test_chat_session_file_command_ingests_document(artifact_dir: Path) -> None:
    session = ChatSession()

    result = session.handle(f"/file {qrest_examples_root() / 'kunming2' / 'metadata.json'}")

    write_json(artifact_dir / "dialogue" / "file_command_result.json", result.to_dict())

    assert result.report.ready
    assert "BuildingInfo.ProjectName" in session.agent.working_state.records


def test_chat_session_tool_commands_use_registry(tmp_path: Path, artifact_dir: Path) -> None:
    agent = QrestAgent(tool_registry=ToolRegistry(artifact_root=tmp_path / "artifacts"))
    session = ChatSession(agent, session_id="dialogue-tools")

    tools_result = session.handle("/tools")
    load_result = session.handle(f"/load-qrest {qrest_examples_root() / 'kunming2' / 'kunming2.qrest'}")
    generate_result = session.handle(
        f"/generate-qrest {qrest_examples_root() / 'kunming2' / 'metadata.json'} {qrest_examples_root() / 'kunming2' / 'data.txt'}"
    )

    write_json(artifact_dir / "dialogue" / "tool_command_transcript.json", session.to_dict())

    assert "可用 skills" in tools_result.response
    assert "qrest_data_generation" in tools_result.response
    assert "Deterministic tools" in tools_result.response
    assert "generate_qrest" in tools_result.response
    assert "低层快捷命令" in tools_result.response
    assert load_result.tool_result is not None
    assert load_result.tool_result["ok"]
    assert load_result.report.ready
    assert generate_result.tool_result is not None
    assert generate_result.tool_result["ok"]
    assert "警告" in generate_result.response


def test_chat_session_help_is_skill_first(artifact_dir: Path) -> None:
    session = ChatSession()

    result = session.handle("/help")

    write_json(artifact_dir / "dialogue" / "skill_first_help.json", result.to_dict())

    assert "自然语言任务示例" in result.response
    assert "主 Agent 会自主选择 Skill、调用 Tool 并回复" in result.response
    assert "检查 metadata.json 和 data.txt 能不能生成 qREST" in result.response
    assert "/tools 查看可用 skills 和 deterministic tools" in result.response
    assert "低层快捷命令" in result.response


def test_chat_session_natural_language_preflights_qrest_generation(tmp_path: Path, artifact_dir: Path) -> None:
    agent = QrestAgent(tool_registry=ToolRegistry(artifact_root=tmp_path / "artifacts"))
    session = ChatSession(agent, session_id="dialogue-preflight")
    example_dir = qrest_examples_root() / "kunming2"

    result = session.handle(f"检查 {example_dir / 'metadata.json'} 和 {example_dir / 'data.txt'} 能不能生成 qREST")
    artifacts = session.to_dict()["artifacts"]

    write_json(
        artifact_dir / "dialogue" / "natural_language_preflight.json",
        {"result": result.to_dict(), "artifacts": artifacts},
    )

    assert result.tool_result is not None
    assert result.tool_result["tool:preflight_generate_qrest"]["ok"]
    assert any("NPTS" in warning for warning in result.tool_result["tool:preflight_generate_qrest"]["warnings"])
    assert "工具 preflight_generate_qrest 执行成功" in result.response
    assert any(item["name"] == "generate_qrest_preflight_report.json" for item in artifacts)


def test_chat_session_natural_language_generates_from_current_metadata(tmp_path: Path, artifact_dir: Path) -> None:
    agent = QrestAgent(tool_registry=ToolRegistry(artifact_root=tmp_path / "artifacts"))
    session = ChatSession(agent, session_id="dialogue-generate-current")
    example_dir = qrest_examples_root() / "kunming2"
    session.handle(f"/file {example_dir / 'metadata.json'}")

    result = session.handle(f"用当前项目状态和 {example_dir / 'data.txt'} 直接生成 qREST")
    artifacts = session.to_dict()["artifacts"]

    write_json(
        artifact_dir / "dialogue" / "natural_language_generate_current_metadata.json",
        {"result": result.to_dict(), "artifacts": artifacts},
    )

    assert result.tool_result is not None
    assert result.tool_result["export"]["ok"]
    assert result.tool_result["export"]["metadata_json"].endswith("metadata.json")
    assert result.tool_result["tool:generate_qrest"]["ok"]
    assert "工具 generate_qrest 执行成功" in result.response
    assert any(item["name"] == "metadata.json" for item in artifacts)
    assert any(item["name"] == "generated.qrest" for item in artifacts)


def test_chat_session_natural_language_generation_missing_data_path_blocks(tmp_path: Path, artifact_dir: Path) -> None:
    agent = QrestAgent(tool_registry=ToolRegistry(artifact_root=tmp_path / "artifacts"))
    session = ChatSession(agent, session_id="dialogue-missing-data")

    result = session.handle("用当前项目状态生成 qREST")
    artifacts = session.to_dict()["artifacts"]

    write_json(
        artifact_dir / "dialogue" / "natural_language_generation_missing_data.json",
        {"result": result.to_dict(), "artifacts": artifacts},
    )

    assert result.tool_result is not None
    assert "export" in result.tool_result
    assert "BuildingInfo.Elevation" in result.tool_result["export"]["blocked_fields"]
    assert "导出被阻断" in result.response
    assert any(item["name"] == "metadata_export_report.json" for item in artifacts)


def test_chat_session_natural_language_loads_qrest(tmp_path: Path, artifact_dir: Path) -> None:
    agent = QrestAgent(tool_registry=ToolRegistry(artifact_root=tmp_path / "artifacts"))
    session = ChatSession(agent, session_id="dialogue-loading")
    example_dir = qrest_examples_root() / "kunming2"

    result = session.handle(f"解析 {example_dir / 'kunming2.qrest'} 并导入当前项目")
    artifacts = session.to_dict()["artifacts"]

    write_json(
        artifact_dir / "dialogue" / "natural_language_loading.json",
        {"result": result.to_dict(), "artifacts": artifacts},
    )

    assert result.tool_result is not None
    assert result.tool_result["tool:load_qrest"]["ok"]
    assert result.report.ready
    assert "BuildingInfo.ProjectName" in session.agent.working_state.records
    assert any(item["name"] == "loaded_metadata.json" for item in artifacts)
    assert any(item["name"] == "loaded_data.txt" for item in artifacts)


def test_cli_defaults_use_provider_config() -> None:
    defaults = _load_cli_defaults()

    assert defaults["provider"] == "ollama-cli"
    assert defaults["model"] == "qwen3:4b-instruct"
