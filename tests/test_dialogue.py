from __future__ import annotations

import json
from pathlib import Path

from qrest_agent.agent.dialogue import ChatSession
from qrest_agent.cli import main
from tests.conftest import write_json, write_text


def test_chat_session_extracts_and_reports_missing_fields(artifact_dir: Path) -> None:
    session = ChatSession()

    result = session.handle("项目名称为 DemoBuilding。事件名称为 2025_TEST_EVENT。采样间隔为 0.02s。")
    state_result = session.handle("/state")

    write_json(artifact_dir / "dialogue" / "basic_session_transcript.json", session.to_dict())
    write_text(artifact_dir / "dialogue" / "basic_state.txt", state_result.response)

    assert "本轮提取到" in result.response
    assert "BuildingInfo.ProjectName" in session.agent.state.records
    assert "DataInfo.DT" in session.agent.state.records
    assert not result.report.ready
    assert "当前已知字段" in state_result.response


def test_chat_session_confirm_command_updates_state(artifact_dir: Path) -> None:
    session = ChatSession()

    result = session.handle("/confirm DataInfo.NPTS 30000")

    write_json(artifact_dir / "dialogue" / "confirm_command_result.json", result.to_dict())

    record = session.agent.state.records["DataInfo.NPTS"]
    assert record.value == 30000
    assert record.status == "confirmed"
    assert "已确认 DataInfo.NPTS" in result.response


def test_chat_session_confirm_command_accepts_json_values() -> None:
    session = ChatSession()

    session.handle('/confirm BuildingInfo.StructuralFootprint.Parameters \'{"Length": 42.0, "Width": 25.2}\'')

    record = session.agent.state.records["BuildingInfo.StructuralFootprint.Parameters"]
    assert record.value == {"Length": 42.0, "Width": 25.2}


def test_cli_chat_scripted_messages_write_transcript(tmp_path: Path, artifact_dir: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    transcript = tmp_path / "chat_transcript.json"

    exit_code = main(
        [
            "chat",
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
