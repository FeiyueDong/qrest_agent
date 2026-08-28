from __future__ import annotations

from pathlib import Path

from qrest_agent.api.app import create_app
from qrest_agent.api.service import ApiService
from qrest_agent.core.models import Candidate, Evidence
from qrest_agent.resources import qrest_examples_root
from tests.conftest import write_json


def test_api_service_chat_upload_and_artifacts(tmp_path: Path, artifact_dir: Path) -> None:
    service = ApiService(artifact_root=tmp_path / "api_artifacts")

    created = service.create_session("api-session")
    chat = service.chat("api-session", "项目名称为 DemoApi。采样间隔为 0.02s。")
    # upload 只保存为 pending attachment，不触发 Agent Turn（方案 §48）
    upload = service.upload_text("api-session", "event.txt", "事件名称为 API_EVENT。数据点数：30000。")
    session_before = service.get_session("api-session")
    turn = service.turn("api-session", "请整理这些资料", [upload["attachment_id"]])
    session_after = service.get_session("api-session")
    artifacts = service.list_artifacts("api-session")
    preview = service.read_artifact_text("api-session", "uploads/event.txt")

    write_json(
        artifact_dir / "api" / "service_chat_upload_artifacts.json",
        {
            "created": created,
            "chat": chat,
            "upload": upload,
            "turn": turn,
            "session_after": session_after,
            "artifacts": artifacts,
            "preview": preview,
        },
    )

    assert created["session_id"] == "api-session"
    assert "BuildingInfo.ProjectName" in service.get_session("api-session")["records"]
    assert upload["attachment_id"]
    assert upload["status"] == "pending"
    # upload 本身不触发提取：EventName 尚未进入状态
    assert session_before["records"].get("DataInfo.EventName") is None
    # turn 携带附件后 Agent 真正处理
    assert session_after["records"]["DataInfo.EventName"]["value"] == "API_EVENT"
    assert session_after["attachments"][0]["status"] == "used"
    assert turn["turn"]["intent"] == "collect_metadata"
    assert turn["turn"]["skills"]
    assert preview["text"] == "事件名称为 API_EVENT。数据点数：30000。"
    assert any(item["name"] == "uploads/event.txt" for item in artifacts["artifacts"])


def test_api_service_binary_docx_upload(tmp_path: Path, artifact_dir: Path) -> None:
    service = ApiService(artifact_root=tmp_path / "api_artifacts")
    service.create_session("binary-session")
    docx = Path("resources/input_doc/Kunming_building_metadata_test_case.docx")

    result = service.upload_file_bytes("binary-session", docx.name, docx.read_bytes())
    assert result["status"] == "pending"
    turn = service.turn("binary-session", "请根据附件整理当前项目的信息", [result["attachment_id"]])
    session = service.get_session("binary-session")

    write_json(
        artifact_dir / "api" / "service_binary_docx_upload.json",
        {
            "upload": result,
            "turn": turn,
            "report": session["report"],
            "records": {k: v.get("value") for k, v in session["records"].items()},
        },
    )

    assert result["name"] == docx.name
    assert result["size"] == docx.stat().st_size
    assert session["records"]["DataInfo.DT"]["value"] == 0.02
    assert session["records"]["DataInfo.NPTS"]["value"] == 30000
    assert session["attachments"][0]["status"] == "used"


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


def test_api_service_runs_preflight_tool(tmp_path: Path, artifact_dir: Path) -> None:
    service = ApiService(artifact_root=tmp_path / "api_artifacts")
    service.create_session("preflight-session")
    example_dir = qrest_examples_root() / "kunming2"

    result = service.run_tool(
        "preflight-session",
        "preflight_generate_qrest",
        {
            "metadata_json": example_dir / "metadata.json",
            "data_txt": example_dir / "data.txt",
        },
    )
    artifacts = service.list_artifacts("preflight-session")

    write_json(
        artifact_dir / "api" / "service_preflight_tool_result.json",
        {"result": result, "artifacts": artifacts},
    )

    assert result["ok"]
    assert "state_update" not in result
    assert any("DataInfo.NPTS=30000" in warning for warning in result["warnings"])
    assert any(item["name"] == "generate_qrest_preflight_report.json" for item in artifacts["artifacts"])


def test_api_service_exports_weighted_metadata(tmp_path: Path, artifact_dir: Path) -> None:
    service = ApiService(artifact_root=tmp_path / "api_artifacts")
    service.create_session("export-session")
    session = service._session("export-session")
    evidence = [Evidence(source_id="test", text="manual candidate")]
    for candidate in [
        Candidate(field_path="BuildingInfo.ElevationNum", value=1, status="confirmed", evidence=evidence),
        Candidate(field_path="BuildingInfo.Elevation", value=[0.0], status="confirmed", evidence=evidence),
        Candidate(field_path="InstrumentInfo.ChannelNum", value=1, status="confirmed", evidence=evidence),
        Candidate(
            field_path="InstrumentInfo.Channels",
            value=[{"ChannelNo": 1, "Azimuth": 90.0, "LocationXYZ": [0.0, 0.0, 0.0]}],
            status="confirmed",
            evidence=evidence,
        ),
        Candidate(field_path="DataInfo.NPTS", value=30000, status="confirmed", evidence=evidence),
        Candidate(field_path="DataInfo.DT", value=0.02, status="confirmed", evidence=evidence),
    ]:
        session.agent.working_state.submit(candidate)

    result = service.export_metadata("export-session")
    metadata_text = service.read_artifact_text("export-session", "metadata.json")["text"]
    artifacts = service.list_artifacts("export-session")

    write_json(
        artifact_dir / "api" / "service_weighted_export_result.json",
        {"result": result, "metadata": metadata_text, "artifacts": artifacts},
    )

    assert result["ok"]
    assert result["defaulted_fields"]
    assert result["blank_fields"]
    assert any(item["name"] == "metadata.json" for item in artifacts["artifacts"])
    assert any(item["name"] == "metadata_export_report.json" for item in artifacts["artifacts"])


def test_api_service_blocks_export_when_mandatory_missing(tmp_path: Path, artifact_dir: Path) -> None:
    service = ApiService(artifact_root=tmp_path / "api_artifacts")
    service.create_session("blocked-export")

    result = service.export_metadata("blocked-export")
    artifacts = service.list_artifacts("blocked-export")

    write_json(
        artifact_dir / "api" / "service_blocked_export_result.json",
        {"result": result, "artifacts": artifacts},
    )

    assert not result["ok"]
    assert "BuildingInfo.Elevation" in result["blocked_fields"]
    assert any(item["name"] == "metadata_export_report.json" for item in artifacts["artifacts"])
    assert not any(item["name"] == "metadata.json" for item in artifacts["artifacts"])


def test_fastapi_app_is_optional() -> None:
    try:
        app = create_app(ApiService())
    except RuntimeError as exc:
        assert "qrest-agent[api]" in str(exc)
    else:
        assert app.title == "qREST Agent API"
