from __future__ import annotations

from pathlib import Path

from qrest_agent.api.app import create_app
from qrest_agent.api.service import ApiService
from qrest_agent.resources import qrest_examples_root
from tests.conftest import write_json


def test_api_service_chat_upload_and_artifacts(tmp_path: Path, artifact_dir: Path) -> None:
    service = ApiService(artifact_root=tmp_path / "api_artifacts")

    created = service.create_session("api-session")
    chat = service.chat("api-session", "项目名称为 DemoApi。采样间隔为 0.02s。")
    upload = service.upload_text("api-session", "event.txt", "事件名称为 API_EVENT。数据点数：30000。")
    artifacts = service.list_artifacts("api-session")

    write_json(
        artifact_dir / "api" / "service_chat_upload_artifacts.json",
        {
            "created": created,
            "chat": chat,
            "upload": upload,
            "artifacts": artifacts,
        },
    )

    assert created["session_id"] == "api-session"
    assert "BuildingInfo.ProjectName" in service.get_session("api-session")["records"]
    assert upload["uploaded"]["path"].endswith("event.txt")
    assert any(item["name"] == "uploads/event.txt" for item in artifacts["artifacts"])


def test_api_service_runs_qrest_tool(tmp_path: Path, artifact_dir: Path) -> None:
    service = ApiService(artifact_root=tmp_path / "api_artifacts")
    service.create_session("tool-session")

    result = service.run_tool(
        "tool-session",
        "load_qrest",
        {"input_qrest": qrest_examples_root() / "kunming2" / "kunming2.qrest"},
    )
    artifacts = service.list_artifacts("tool-session")

    write_json(
        artifact_dir / "api" / "service_tool_result.json",
        {"result": result, "artifacts": artifacts},
    )

    assert result["ok"]
    assert result["state_update"]["report"]["ready"]
    assert any(item["name"] == "loaded_metadata.json" for item in artifacts["artifacts"])
    assert any(item["name"] == "loaded_data.txt" for item in artifacts["artifacts"])


def test_fastapi_app_is_optional() -> None:
    try:
        app = create_app(ApiService())
    except RuntimeError as exc:
        assert "qrest-agent[api]" in str(exc)
    else:
        assert app.title == "qREST Agent API"
