from __future__ import annotations

import base64
from email.message import Message
from io import BytesIO
import json
from pathlib import Path
from typing import Any

from qrest_agent.api.service import ApiService
from qrest_agent.core.models import Candidate, Evidence
from qrest_agent.resources import qrest_examples_root
from qrest_agent.web.server import WebServerState, _make_handler
from tests.conftest import write_json, write_text


def test_web_server_smoke_flow(tmp_path: Path, artifact_dir: Path) -> None:
    service = ApiService(artifact_root=tmp_path / "web_artifacts")
    handler = _make_handler(WebServerState(service))

    index_html = _request_text(handler, "/")
    app_js = _request_text(handler, "/app.js")
    style_css = _request_text(handler, "/style.css")
    created = _request_json(handler, "/api/sessions", method="POST", payload={"session_id": "web-session"})
    upload = _request_json(
        handler,
        "/api/upload",
        method="POST",
        payload={
            "session_id": "web-session",
            "file_name": "web_note.txt",
            "content_base64": base64.b64encode("事件名称为 WEB_EVENT。数据点数：30000。".encode("utf-8")).decode("ascii"),
        },
    )
    turn = _request_json(
        handler,
        "/api/turn",
        method="POST",
        payload={
            "session_id": "web-session",
            "message": "请根据这些资料整理当前项目的信息",
            "attachments": [upload["attachment_id"]],
        },
    )
    export = _request_json(
        handler,
        "/api/export-metadata",
        method="POST",
        payload={"session_id": "web-session", "file_name": "metadata.json"},
    )
    session = _request_json(handler, "/api/session?session_id=web-session")
    artifacts = _request_json(handler, "/api/artifacts?session_id=web-session")

    write_text(artifact_dir / "web" / "index.html", index_html)
    write_json(
        artifact_dir / "web" / "server_smoke_flow.json",
        {
            "created": created,
            "upload": upload,
            "turn": turn,
            "export": export,
            "session": session,
            "artifacts": artifacts,
        },
    )

    # 静态资源拆分（§50-§53）
    assert "qREST Agent" in index_html
    assert '<link rel="stylesheet" href="/style.css">' in index_html
    assert '<script src="/app.js"></script>' in index_html
    assert "recordsTree" in app_js
    assert "collectRecordSets" in app_js
    assert "turnActivity" in index_html
    assert "artifactList" in index_html
    assert "attachmentChips" in index_html
    assert ".messages" in style_css

    # 新状态模型（§34-§35）：已确认 / 待确认 / 缺失 / 冲突
    for key in ("accepted", "pending", "missing", "conflict"):
        assert f'data-record-filter="{key}"' in index_html
    assert 'id="acceptedCount"' in index_html
    assert 'id="pendingCount"' in index_html
    assert 'id="missingCount"' in index_html
    assert 'id="conflictCount"' in index_html

    # 三栏布局：最左侧 Agent Activity 栏（This Turn/Recent Turns/Inputs/Skills/Artifacts），
    # 中间 Conversation，右侧 Project State + Fields
    assert 'class="activity"' in index_html
    assert 'class="workspace"' in index_html
    assert '<details class="panel collapsible" id="turnPanel" open>' in index_html
    assert '<details class="panel collapsible" id="recentTurnsPanel">' in index_html
    assert '<details class="panel collapsible" id="inputsPanel">' in index_html
    assert '<details class="panel collapsible" id="skillsPanel">' in index_html
    assert '<details class="panel collapsible" id="artifactsPanel">' in index_html
    # 折叠面板默认不带 open 属性（折叠时只占一行）；This Turn 默认展开
    assert '<details class="panel collapsible" id="skillsPanel" open>' not in index_html
    assert '<details class="panel collapsible" id="artifactsPanel" open>' not in index_html
    assert '<details class="panel collapsible" id="recentTurnsPanel" open>' not in index_html
    assert '<details class="panel collapsible" id="inputsPanel" open>' not in index_html
    # DOM 顺序：Activity 栏在最前（This Turn 不再夹在消息区与输入框之间）
    assert index_html.index('class="activity"') < index_html.index('class="workspace"')
    assert index_html.index('id="turnPanel"') < index_html.index('id="chatForm"')
    assert index_html.index('id="turnPanel"') < index_html.index('id="recentTurnsPanel"')
    assert index_html.index('id="recentTurnsPanel"') < index_html.index('id="inputsPanel"')
    assert index_html.index('id="inputsPanel"') < index_html.index('id="skillsPanel"')
    assert index_html.index('id="skillsPanel"') < index_html.index('id="artifactsPanel"')
    # 右侧 side 只剩 Project State + Fields；Skills/Artifacts 不再在右侧
    assert index_html.index('id="artifactsPanel"') < index_html.index('id="recordsTree"')
    # 布局保护：只有 Fields 允许伸缩，防止内容多时挤压/遮盖 Project State
    assert ".side > .panel:not(.records-panel)" in style_css
    assert "grid-template-columns: 250px minmax(0, 1fr) 420px" in style_css
    # 左侧新输出：Recent Turns / Inputs 渲染逻辑存在
    assert "renderRecentTurns" in app_js
    assert "renderInputs" in app_js

    # 旧概念已删除（§42-§44）
    assert "taskLogList" not in index_html
    assert "skill_handlers" not in index_html
    assert "task_logs" not in index_html
    assert "skill_handlers" not in app_js
    assert "task_logs" not in app_js
    assert "task-log" not in style_css

    # upload 只登记 pending，turn 携带附件后 Agent 使用
    assert upload["status"] == "pending"
    assert upload["attachment_id"]
    assert turn["turn"]["intent"] == "collect_metadata"
    assert turn["turn"]["skills"]
    assert session["attachments"][0]["status"] == "used"
    assert "DataInfo.EventName" in session["records"]
    assert session["records"]["DataInfo.EventName"]["value"] == "WEB_EVENT"
    assert "skill_handlers" not in session
    assert "task_logs" not in session
    assert session["last_turn"]["intent"] == "collect_metadata"
    assert "skills" in session
    assert not export["ok"]
    assert any(item["name"] == "metadata_export_report.json" for item in artifacts["artifacts"])
    assert any(item["name"] == "uploads/web_note.txt" for item in artifacts["artifacts"])


def test_web_server_state_statuses_are_separated(tmp_path: Path, artifact_dir: Path) -> None:
    """方案 §62：confirmed/extracted/derived 与 uncertain/inferred/missing/conflict 分类正确。"""
    service = ApiService(artifact_root=tmp_path / "web_artifacts")
    service.create_session("status-session")
    session = service._session("status-session")
    evidence = [Evidence(source_id="doc", text="evidence")]
    for candidate in [
        Candidate(field_path="BuildingInfo.ProjectName", value="Demo", status="confirmed", evidence=evidence),
        Candidate(field_path="BuildingInfo.StructuralType", value="RCFrame", status="extracted", evidence=evidence),
        Candidate(field_path="BuildingInfo.ElevationNum", value=3, status="derived", evidence=evidence, confidence=1.0),
        Candidate(field_path="BuildingInfo.GeoLocation.NorthAngle", value=15.0, status="uncertain", evidence=evidence),
        Candidate(field_path="BuildingInfo.StructuralFootprint.Shape", value="Rect", status="inferred", evidence=evidence),
        Candidate(field_path="BuildingInfo.Elevation", value=None, status="missing"),
        Candidate(field_path="BuildingInfo.StructuralFootprint.Parameters", value={"Length": 42.0}, status="extracted", evidence=evidence),
        Candidate(field_path="BuildingInfo.StructuralFootprint.Parameters", value={"Length": 46.9}, status="extracted", evidence=evidence),
    ]:
        session.agent.working_state.submit(candidate)

    payload = service.get_session("status-session")
    records = payload["records"]

    write_json(artifact_dir / "web" / "status_classification.json", payload)

    accepted = {path for path, record in records.items() if record["status"] in {"confirmed", "extracted", "derived"}}
    pending = {path for path, record in records.items() if record["status"] in {"uncertain", "inferred"}}
    missing = set(payload["report"]["missing_required"])
    conflicts = set(payload["report"]["conflicts"])

    assert "BuildingInfo.ProjectName" in accepted
    assert "BuildingInfo.StructuralType" in accepted
    assert "BuildingInfo.ElevationNum" in accepted
    assert "BuildingInfo.GeoLocation.NorthAngle" in pending
    assert "BuildingInfo.StructuralFootprint.Shape" in pending
    assert "BuildingInfo.GeoLocation.NorthAngle" not in accepted
    assert "BuildingInfo.StructuralFootprint.Shape" not in accepted
    assert "BuildingInfo.Elevation" in missing or "BuildingInfo.ElevationNum" in missing
    assert "BuildingInfo.StructuralFootprint.Parameters" in conflicts
    # inferred 不得进入可导出 metadata
    metadata = session.agent.to_metadata()
    assert "StructuralFootprint" not in metadata.get("BuildingInfo", {}) or "Shape" not in metadata["BuildingInfo"]["StructuralFootprint"]


def _request_json(
    handler: type,
    path: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = _invoke_handler(handler, path=path, method=method, payload=payload)
    return json.loads(response["body"].decode("utf-8"))


def _request_text(handler: type, path: str) -> str:
    response = _invoke_handler(handler, path=path)
    return response["body"].decode("utf-8")


def _invoke_handler(
    handler_class: type,
    path: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    handler = handler_class.__new__(handler_class)
    handler.rfile = BytesIO(body)
    handler.wfile = BytesIO()
    headers = Message()
    headers["Content-Length"] = str(len(body))
    if body:
        headers["Content-Type"] = "application/json"
    handler.headers = headers
    handler.command = method
    handler.path = path
    handler.request_version = "HTTP/1.1"
    handler.requestline = f"{method} {path} HTTP/1.1"
    handler.client_address = ("127.0.0.1", 0)
    handler.server = None
    handler.close_connection = True

    if method == "GET":
        handler.do_GET()
    elif method == "POST":
        handler.do_POST()
    else:
        raise AssertionError(f"unsupported test method: {method}")

    raw = handler.wfile.getvalue()
    header_bytes, response_body = raw.split(b"\r\n\r\n", 1)
    status_line = header_bytes.splitlines()[0].decode("ascii")
    status = int(status_line.split()[1])
    assert status < 400, response_body.decode("utf-8")
    return {"status": status, "headers": header_bytes, "body": response_body}
