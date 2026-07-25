from __future__ import annotations

import base64
from email.message import Message
from io import BytesIO
import json
import urllib.parse
from pathlib import Path
from typing import Any

from qrest_agent.api.service import ApiService
from qrest_agent.web.server import WebServerState, _make_handler
from tests.conftest import write_json, write_text


def test_web_server_smoke_flow(tmp_path: Path, artifact_dir: Path) -> None:
    service = ApiService(artifact_root=tmp_path / "web_artifacts")
    handler = _make_handler(WebServerState(service))

    index_html = _request_text(handler, "/")
    created = _request_json(handler, "/api/sessions", method="POST", payload={"session_id": "web-session"})
    chat = _request_json(
        handler,
        "/api/chat",
        method="POST",
        payload={"session_id": "web-session", "message": "项目名称为 WebDemo，采样间隔为 0.02s。"},
    )
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
    session = _request_json(handler, "/api/session?session_id=web-session")
    artifacts = _request_json(handler, "/api/artifacts?session_id=web-session")
    preview = _request_json(
        handler,
        "/api/artifact?session_id=web-session&name=" + urllib.parse.quote("uploads/web_note.txt", safe=""),
    )

    write_text(artifact_dir / "web" / "index.html", index_html)
    write_json(
        artifact_dir / "web" / "server_smoke_flow.json",
        {
            "created": created,
            "chat": chat,
            "upload": upload,
            "session": session,
            "artifacts": artifacts,
            "preview": preview,
        },
    )

    assert "qREST Agent" in index_html
    assert 'id="recordsTree"' in index_html
    assert 'data-record-filter="known"' in index_html
    assert 'data-record-filter="missing"' in index_html
    assert 'data-record-filter="conflict"' in index_html
    assert 'id="missingList"' not in index_html
    assert "function buildRecordTree" in index_html
    assert created["session_id"] == "web-session"
    assert "BuildingInfo.ProjectName" in session["records"]
    assert upload["uploaded"]["file_name"] == "web_note.txt"
    assert preview["text"] == "事件名称为 WEB_EVENT。数据点数：30000。"
    assert any(item["name"] == "uploads/web_note.txt" for item in artifacts["artifacts"])


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
