from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from qrest_agent.api.service import ApiService

#: 静态前端资源（方案 §50-§53：server.py 只负责路由，前端拆分为 index/app/style）。
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".ico": "image/x-icon",
}


@dataclass(slots=True)
class WebServerState:
    service: ApiService


def build_server(host: str = "127.0.0.1", port: int = 8000, service: ApiService | None = None) -> ThreadingHTTPServer:
    state = WebServerState(service=service or ApiService())
    handler = _make_handler(state)
    return ThreadingHTTPServer((host, port), handler)


def serve(host: str = "127.0.0.1", port: int = 8000, service: ApiService | None = None) -> None:
    server = build_server(host=host, port=port, service=service)
    actual_host, actual_port = server.server_address[:2]
    display_host = "127.0.0.1" if actual_host in {"0.0.0.0", "::"} else actual_host
    print(f"qREST Agent web UI: http://{display_host}:{actual_port}/", flush=True)
    if host in {"0.0.0.0", "::"}:
        print(f"LAN access: http://<linux-ip>:{actual_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _make_handler(state: WebServerState) -> type[BaseHTTPRequestHandler]:
    class QrestAgentWebHandler(BaseHTTPRequestHandler):
        server_version = "QrestAgentWeb/0.1"

        def do_GET(self) -> None:  # noqa: N802
            route = urlsplit(self.path)
            if route.path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
                return
            if route.path == "/api/health":
                self._send_json({"ok": True, "service": "qrest-agent-web"})
                return
            if route.path == "/api/session":
                query = parse_qs(route.query)
                try:
                    session_id = _single_query_value(query, "session_id")
                    self._send_json(state.service.get_session(session_id))
                except KeyError as exc:
                    self._send_error(HTTPStatus.NOT_FOUND, str(exc))
                return
            if route.path == "/api/artifacts":
                query = parse_qs(route.query)
                try:
                    session_id = _single_query_value(query, "session_id")
                    self._send_json(state.service.list_artifacts(session_id))
                except KeyError as exc:
                    self._send_error(HTTPStatus.NOT_FOUND, str(exc))
                return
            if route.path == "/api/artifact":
                query = parse_qs(route.query)
                try:
                    session_id = _single_query_value(query, "session_id")
                    name = _single_query_value(query, "name")
                    self._send_json(state.service.read_artifact_text(session_id, name))
                except KeyError as exc:
                    self._send_error(HTTPStatus.NOT_FOUND, str(exc))
                except OSError as exc:
                    self._send_error(HTTPStatus.NOT_FOUND, str(exc))
                except UnicodeDecodeError as exc:
                    self._send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, f"artifact is not text: {exc}")
                return
            if route.path in {"/", "/index.html"}:
                self._send_static("index.html")
                return
            if route.path.startswith("/"):
                name = route.path.lstrip("/")
                if "/" not in name and (name.endswith(".js") or name.endswith(".css") or name.endswith(".html")):
                    self._send_static(name)
                    return
            self._send_error(HTTPStatus.NOT_FOUND, f"unknown route: {route.path}")

        def do_POST(self) -> None:  # noqa: N802
            route = urlsplit(self.path)
            try:
                payload = self._read_json()
            except ValueError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return

            if route.path == "/api/sessions":
                try:
                    self._send_json(state.service.create_session(payload.get("session_id")))
                except ValueError as exc:
                    self._send_error(HTTPStatus.CONFLICT, str(exc))
                return
            if route.path == "/api/turn":
                try:
                    session_id = str(payload["session_id"])
                    message = str(payload.get("message", ""))
                    attachments = payload.get("attachments")
                    if attachments is not None and not isinstance(attachments, list):
                        raise ValueError("attachments must be a list of attachment ids")
                    self._send_json(state.service.turn(session_id, message, attachments))
                except KeyError as exc:
                    self._send_error(HTTPStatus.NOT_FOUND, str(exc))
                except ValueError as exc:
                    self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            if route.path == "/api/chat":
                # 兼容旧端点：等价于无附件的 turn
                try:
                    session_id = str(payload["session_id"])
                    message = str(payload.get("message", ""))
                    self._send_json(state.service.chat(session_id, message))
                except KeyError as exc:
                    self._send_error(HTTPStatus.NOT_FOUND, str(exc))
                return
            if route.path == "/api/upload":
                try:
                    session_id = str(payload["session_id"])
                    file_name = str(payload["file_name"])
                    data = base64.b64decode(str(payload["content_base64"]), validate=True)
                    self._send_json(state.service.upload_file_bytes(session_id, file_name, data))
                except (KeyError, ValueError, binascii.Error) as exc:
                    self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                except FileNotFoundError as exc:
                    self._send_error(HTTPStatus.NOT_FOUND, str(exc))
                except Exception as exc:
                    self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
                return
            if route.path == "/api/export-metadata":
                try:
                    session_id = str(payload["session_id"])
                    file_name = str(payload.get("file_name", "metadata.json"))
                    self._send_json(state.service.export_metadata(session_id, file_name))
                except KeyError as exc:
                    self._send_error(HTTPStatus.NOT_FOUND, str(exc))
                return
            self._send_error(HTTPStatus.NOT_FOUND, f"unknown route: {route.path}")

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_static(self, name: str) -> None:
            try:
                text = (_STATIC_DIR / name).read_text(encoding="utf-8")
            except FileNotFoundError as exc:
                self._send_error(HTTPStatus.NOT_FOUND, f"static file not found: {name}")
                return
            content_type = _STATIC_TYPES.get(Path(name).suffix, "text/plain; charset=utf-8")
            self._send_text(text, content_type=content_type)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON body: {exc}") from exc
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
            return data

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
            body = text.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, status: HTTPStatus, message: str) -> None:
            self._send_json({"ok": False, "error": message, "status": status.value}, status=status)

    return QrestAgentWebHandler


def _single_query_value(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name)
    if not values or values[0] == "":
        raise KeyError(name)
    return values[0]
