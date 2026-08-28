from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from qrest_agent.api.service import ApiService


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
            if route.path == "/":
                self._send_text(INDEX_HTML, content_type="text/html; charset=utf-8")
                return
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
            if route.path == "/api/chat":
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
                except Exception as exc:  # The response should expose ingestion failures to the UI.
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


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>qREST Agent</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f4;
      --panel: #ffffff;
      --ink: #20252d;
      --muted: #68707c;
      --line: #d8ddd7;
      --accent: #0f766e;
      --accent-strong: #115e59;
      --warn: #b45309;
      --bad: #b91c1c;
      --soft: #eef5f2;
      --shadow: 0 12px 34px rgba(32, 37, 45, 0.08);
    }
    * { box-sizing: border-box; }
    html, body {
      height: 100%;
    }
    body {
      margin: 0;
      min-height: 100vh;
      overflow: hidden;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    button, input, textarea {
      font: inherit;
    }
    button {
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      cursor: pointer;
      padding: 7px 11px;
    }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }
    .app {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 390px;
      gap: 14px;
      height: 100vh;
      min-height: 0;
      padding: 14px;
      overflow: hidden;
    }
    .workspace, .side {
      min-width: 0;
      min-height: 0;
    }
    .workspace {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      gap: 12px;
    }
    .topbar, .messages, .composer, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 12px;
    }
    h1, h2 {
      margin: 0;
      font-size: 15px;
      line-height: 1.2;
    }
    h1 {
      font-size: 18px;
    }
    .badges {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 6px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 27px;
      max-width: 100%;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 9px;
      color: var(--muted);
      background: #fff;
      white-space: nowrap;
    }
    .badge.ready {
      color: var(--accent-strong);
      background: var(--soft);
      border-color: #9ccbc2;
    }
    .messages {
      min-height: 0;
      overflow: auto;
      padding: 12px;
    }
    .message {
      max-width: 920px;
      margin: 0 0 10px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
    }
    .message.user {
      margin-left: auto;
      background: #eef5f2;
      border-color: #b7d7ce;
    }
    .role {
      margin-bottom: 4px;
      color: var(--muted);
      font-size: 12px;
    }
    .message pre {
      margin: 0;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }
    .composer {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      grid-template-areas:
        "input send"
        "tools tools";
      gap: 10px;
      padding: 10px;
    }
    .composer textarea {
      grid-area: input;
    }
    .composer #sendButton {
      grid-area: send;
      align-self: start;
      min-width: 76px;
    }
    .composer-tools {
      grid-area: tools;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      min-width: 0;
      padding-top: 8px;
      border-top: 1px solid var(--line);
    }
    .file-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      flex: 1 1 auto;
    }
    .export-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex: 0 0 auto;
    }
    textarea {
      min-height: 76px;
      max-height: 220px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 9px 10px;
      color: var(--ink);
      background: #fff;
    }
    .side {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      gap: 12px;
      overflow: hidden;
    }
    .panel {
      min-width: 0;
      min-height: 0;
      padding: 11px;
    }
    .panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
    }
    .meta-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .metric {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 8px;
      background: #fbfcfb;
      text-align: left;
      cursor: pointer;
    }
    .metric.active {
      border-color: #7db8ae;
      background: var(--soft);
      color: var(--accent-strong);
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: 12px;
    }
    .metric strong {
      display: block;
      margin-top: 3px;
      font-size: 18px;
    }
    .metric.active span {
      color: var(--accent-strong);
    }
    input[type="file"] {
      width: 100%;
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 7px;
      background: #fff;
    }
    .records-tree {
      flex: 1 1 auto;
      min-height: 0;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fbfcfb;
    }
    .records-panel {
      display: flex;
      flex-direction: column;
    }
    .skill-list, .task-log-list {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 8px;
    }
    .task-log-list {
      display: grid;
      grid-template-columns: 1fr;
    }
    .skill-item, .task-log-item {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 8px;
      color: var(--accent-strong);
      background: var(--soft);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .task-log-item {
      border-radius: 7px;
      color: var(--muted);
      background: #fbfcfb;
    }
    .tree-node, .tree-leaf {
      border-bottom: 1px solid var(--line);
    }
    .tree-node:last-child, .tree-leaf:last-child {
      border-bottom: 0;
    }
    .tree-summary {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 34px;
      padding: 7px 8px;
      cursor: pointer;
      list-style: none;
      overflow-wrap: anywhere;
    }
    .tree-summary::-webkit-details-marker {
      display: none;
    }
    .tree-summary::before {
      content: ">";
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 16px;
      color: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      transform: rotate(0deg);
      transition: transform 120ms ease;
    }
    details[open] > .tree-summary::before {
      transform: rotate(90deg);
    }
    .tree-name {
      min-width: 0;
      flex: 1 1 auto;
      font-weight: 600;
    }
    .tree-count, .status-chip {
      flex: 0 0 auto;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 1px 7px;
      color: var(--muted);
      background: #fff;
      font-size: 12px;
      white-space: nowrap;
    }
    .tree-children {
      margin-left: 17px;
      border-left: 1px solid var(--line);
    }
    .tree-leaf {
      padding: 7px 8px 8px 25px;
      background: #fff;
    }
    .leaf-head {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }
    .leaf-name {
      min-width: 0;
      flex: 1 1 auto;
      font-weight: 600;
      overflow-wrap: anywhere;
    }
    .leaf-value, .value-json {
      margin-top: 5px;
      overflow-wrap: anywhere;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }
    .value-json {
      max-height: 220px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 8px;
      background: #f7f8f6;
      white-space: pre-wrap;
    }
    .value-details {
      margin-top: 5px;
    }
    .value-details summary {
      cursor: pointer;
      color: var(--accent-strong);
      overflow-wrap: anywhere;
    }
    .muted {
      color: var(--muted);
    }
    .warn {
      color: var(--warn);
    }
    .bad {
      color: var(--bad);
    }
    @media (max-width: 980px) {
      body {
        overflow: auto;
      }
      .app {
        grid-template-columns: 1fr;
        height: auto;
        min-height: 100vh;
        overflow: visible;
      }
      .workspace {
        grid-template-rows: auto minmax(280px, 52vh) auto;
      }
      .side {
        grid-template-rows: auto;
        overflow: visible;
      }
    }
    @media (max-width: 560px) {
      .app {
        padding: 8px;
      }
      .topbar, .composer, .composer-tools, .file-actions, .export-actions {
        grid-template-columns: 1fr;
        flex-direction: column;
        align-items: stretch;
      }
      .composer {
        display: grid;
        grid-template-columns: 1fr;
        grid-template-areas:
          "input"
          "tools"
          "send";
      }
      .composer #sendButton {
        justify-self: stretch;
      }
      .badges {
        justify-content: flex-start;
      }
      .meta-grid {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <main class="app">
    <section class="workspace">
      <header class="topbar">
        <h1>qREST Agent</h1>
        <div class="badges">
          <span class="badge" id="sessionBadge">session: ...</span>
          <span class="badge" id="runtimeBadge">runtime: ...</span>
          <span class="badge" id="readyBadge">ready: ...</span>
        </div>
      </header>

      <section class="messages" id="messages" aria-live="polite"></section>

      <form class="composer" id="chatForm">
        <textarea id="messageInput" placeholder="输入 qREST 任务，例如：解析 demo.qrest 并导入当前项目；检查 metadata.json 和 data.txt 能不能生成 qREST"></textarea>
        <button class="primary" id="sendButton" type="submit">发送</button>
        <div class="composer-tools">
          <div class="file-actions">
            <input id="fileInput" type="file" accept=".txt,.md,.json,.pdf,.docx,.xlsx,.csv,.qrest">
            <button id="uploadButton" type="button">导入文件</button>
          </div>
          <div class="export-actions">
            <button id="exportButton" type="button">导出 metadata.json</button>
          </div>
        </div>
      </form>
    </section>

    <aside class="side">
      <section class="panel">
        <div class="panel-header">
          <h2>校验</h2>
          <button id="refreshButton" type="button">刷新</button>
        </div>
        <div class="meta-grid">
          <button class="metric active" data-record-filter="known" type="button"><span>已知</span><strong id="knownCount">0</strong></button>
          <button class="metric" data-record-filter="missing" type="button"><span>缺失</span><strong id="missingCount">0</strong></button>
          <button class="metric" data-record-filter="conflict" type="button"><span>冲突</span><strong id="conflictCount">0</strong></button>
        </div>
      </section>

      <section class="panel records-panel">
        <div class="panel-header">
          <h2>字段</h2>
          <span class="muted" id="fieldCount"></span>
        </div>
        <div class="records-tree" id="recordsTree"></div>
      </section>

      <section class="panel">
        <div class="panel-header">
          <h2>Skills</h2>
          <span class="muted" id="skillCount"></span>
        </div>
        <div class="muted">自然语言任务会优先由 skill handler 处理。</div>
        <div class="skill-list" id="skillList"></div>
        <div class="muted" style="margin-top: 10px;">Task logs</div>
        <div class="task-log-list" id="taskLogList"></div>
      </section>
    </aside>
  </main>

  <script>
    const state = {
      sessionId: localStorage.getItem("qrest-agent-session-id") || "",
      session: null,
      recordFilter: localStorage.getItem("qrest-agent-record-filter") || "known"
    };
    const recordFilterLabels = {known: "已知", missing: "缺失", conflict: "冲突"};

    const messages = document.querySelector("#messages");
    const chatForm = document.querySelector("#chatForm");
    const messageInput = document.querySelector("#messageInput");
    const sendButton = document.querySelector("#sendButton");
    const fileInput = document.querySelector("#fileInput");
    const uploadButton = document.querySelector("#uploadButton");
    const exportButton = document.querySelector("#exportButton");
    const refreshButton = document.querySelector("#refreshButton");
    const recordFilterButtons = Array.from(document.querySelectorAll("[data-record-filter]"));
    const skillList = document.querySelector("#skillList");
    const taskLogList = document.querySelector("#taskLogList");

    async function api(path, options = {}) {
      const headers = Object.assign({"Content-Type": "application/json"}, options.headers || {});
      const response = await fetch(path, Object.assign({}, options, {headers}));
      const text = await response.text();
      const data = text ? JSON.parse(text) : {};
      if (!response.ok) {
        const error = new Error(data.error || response.statusText);
        error.status = response.status;
        error.payload = data;
        throw error;
      }
      return data;
    }

    async function ensureSession() {
      const payload = state.sessionId ? {session_id: state.sessionId} : {};
      try {
        state.session = await api("/api/sessions", {method: "POST", body: JSON.stringify(payload)});
      } catch (error) {
        if (error.status !== 409 || !state.sessionId) throw error;
        state.session = await api("/api/session?session_id=" + encodeURIComponent(state.sessionId));
      }
      state.sessionId = state.session.session_id;
      localStorage.setItem("qrest-agent-session-id", state.sessionId);
      appendMessage("assistant", "会话已就绪。");
      renderSession();
    }

    async function refreshSession() {
      if (!state.sessionId) return;
      state.session = await api("/api/session?session_id=" + encodeURIComponent(state.sessionId));
      renderSession();
    }

    chatForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const message = messageInput.value.trim();
      if (!message) return;
      appendMessage("user", message);
      messageInput.value = "";
      sendButton.disabled = true;
      try {
        const result = await api("/api/chat", {
          method: "POST",
          body: JSON.stringify({session_id: state.sessionId, message})
        });
        appendMessage("assistant", result.response, result);
        await refreshSession();
      } catch (error) {
        appendMessage("assistant", "请求失败：" + error.message);
      } finally {
        sendButton.disabled = false;
        messageInput.focus();
      }
    });

    uploadButton.addEventListener("click", async () => {
      const file = fileInput.files && fileInput.files[0];
      if (!file) return;
      uploadButton.disabled = true;
      try {
        const contentBase64 = await fileToBase64(file);
        const result = await api("/api/upload", {
          method: "POST",
          body: JSON.stringify({
            session_id: state.sessionId,
            file_name: file.name,
            content_base64: contentBase64
          })
        });
        appendMessage("user", "/file " + file.name);
        appendMessage("assistant", result.response, result);
        fileInput.value = "";
        await refreshSession();
      } catch (error) {
        appendMessage("assistant", "文件导入失败：" + error.message);
      } finally {
        uploadButton.disabled = false;
      }
    });

    exportButton.addEventListener("click", async () => {
      exportButton.disabled = true;
      try {
        const result = await api("/api/export-metadata", {
          method: "POST",
          body: JSON.stringify({session_id: state.sessionId, file_name: "metadata.json"})
        });
        const lines = result.messages || [];
        if (result.ok) {
          appendMessage("assistant", ["metadata.json 已导出。"].concat(lines).join("\n"), result);
        } else {
          appendMessage("assistant", ["metadata.json 未导出。"].concat(lines).join("\n"), result);
        }
        await refreshSession();
      } catch (error) {
        appendMessage("assistant", "导出失败：" + error.message);
      } finally {
        exportButton.disabled = false;
      }
    });

    refreshButton.addEventListener("click", () => {
      refreshSession().catch((error) => appendMessage("assistant", "刷新失败：" + error.message));
    });

    for (const button of recordFilterButtons) {
      button.addEventListener("click", () => {
        state.recordFilter = button.dataset.recordFilter || "known";
        localStorage.setItem("qrest-agent-record-filter", state.recordFilter);
        renderSession();
      });
    }

    function appendMessage(role, text, payload) {
      const item = document.createElement("article");
      item.className = "message " + (role === "user" ? "user" : "assistant");
      const label = document.createElement("div");
      label.className = "role";
      label.textContent = role === "user" ? "你" : "Agent";
      const body = document.createElement("pre");
      body.textContent = text || "";
      item.append(label, body);
      if (payload && payload.extractor) {
        const detail = document.createElement("div");
        detail.className = "role";
        detail.textContent = "extractor=" + payload.extractor + (payload.fallback_reason ? "; fallback=" + payload.fallback_reason : "");
        item.append(detail);
      }
      messages.append(item);
      messages.scrollTop = messages.scrollHeight;
    }

    function renderSession() {
      const session = state.session || {};
      const report = session.report || {};
      const records = session.records || {};
      const runtime = session.runtime || {};
      const recordSets = collectRecordSets(records, report);
      document.querySelector("#sessionBadge").textContent = "session: " + (session.session_id || "...");
      document.querySelector("#runtimeBadge").textContent = runtime.model ? "runtime: " + runtime.provider + " / " + runtime.model : "runtime: " + (runtime.provider || "rule");
      const readyBadge = document.querySelector("#readyBadge");
      readyBadge.textContent = "ready: " + (report.ready ? "yes" : "no");
      readyBadge.classList.toggle("ready", !!report.ready);
      document.querySelector("#knownCount").textContent = String(recordSets.known.length);
      document.querySelector("#missingCount").textContent = String(recordSets.missing.length);
      document.querySelector("#conflictCount").textContent = String(recordSets.conflict.length);
      renderFilterButtons();
      renderSkills(session);
      renderRecords(recordSets[state.recordFilter] || recordSets.known, state.recordFilter);
    }

    function renderSkills(session) {
      const skills = session.skills || [];
      const handlers = session.skill_handlers || [];
      const taskLogs = session.task_logs || [];
      document.querySelector("#skillCount").textContent = skills.length + " skills / " + handlers.length + " handlers";
      skillList.replaceChildren();
      const entries = skills.length ? skills : handlers.map((name) => ({name, policy_name: name}));
      if (!entries.length) {
        const empty = document.createElement("span");
        empty.className = "skill-item";
        empty.textContent = "暂无 skill";
        skillList.append(empty);
      } else {
        for (const skill of entries) {
          const item = document.createElement("span");
          item.className = "skill-item";
          const name = skill.policy_name || skill.name;
          item.textContent = skill.version ? name + " v" + skill.version : name;
          skillList.append(item);
        }
      }
      taskLogList.replaceChildren();
      if (!taskLogs.length) {
        const empty = document.createElement("div");
        empty.className = "task-log-item";
        empty.textContent = "暂无 task log";
        taskLogList.append(empty);
      } else {
        for (const log of taskLogs.slice(-4).reverse()) {
          const item = document.createElement("div");
          item.className = "task-log-item";
          item.textContent = log.name;
          taskLogList.append(item);
        }
      }
    }

    function collectRecordSets(records, report) {
      const conflicts = new Set(report.conflicts || []);
      const known = Object.entries(records).filter(([, record]) => {
        return record.value !== null && record.status !== "missing" && record.status !== "empty" && record.status !== "conflict";
      });
      const missingPaths = []
        .concat(report.missing_required || [])
        .concat(report.missing_important || [])
        .concat(report.missing_optional || []);
      const missing = missingPaths.map((path) => {
        return [path, records[path] || makeSyntheticRecord(null, "missing")];
      });
      const conflict = Array.from(conflicts).map((path) => {
        return [path, records[path] || makeSyntheticRecord(null, "conflict")];
      });
      return {known, missing, conflict};
    }

    function makeSyntheticRecord(value, status) {
      return {value, status, confidence: 0, evidence: [], alternatives: []};
    }

    function renderFilterButtons() {
      for (const button of recordFilterButtons) {
        button.classList.toggle("active", button.dataset.recordFilter === state.recordFilter);
      }
    }

    function renderRecords(records, filterName) {
      const label = recordFilterLabels[filterName] || "字段";
      document.querySelector("#fieldCount").textContent = label + " " + records.length + " 项";
      const tree = document.querySelector("#recordsTree");
      tree.replaceChildren();
      if (!records.length) {
        const empty = document.createElement("div");
        empty.className = "tree-leaf muted";
        empty.textContent = "暂无字段";
        tree.append(empty);
        return;
      }
      const root = buildRecordTree(records);
      for (const [name, node] of sortedChildren(root)) {
        tree.append(renderTreeNode(name, node, 0));
      }
    }

    function buildRecordTree(records) {
      const root = {children: new Map(), record: null, path: ""};
      for (const [path, record] of records.sort(([a], [b]) => a.localeCompare(b))) {
        const parts = path.split(".");
        let current = root;
        let currentPath = "";
        for (const part of parts) {
          currentPath = currentPath ? currentPath + "." + part : part;
          if (!current.children.has(part)) {
            current.children.set(part, {children: new Map(), record: null, path: currentPath});
          }
          current = current.children.get(part);
        }
        current.record = record;
      }
      return root;
    }

    function renderTreeNode(name, node, depth) {
      if (!node.children.size) {
        return renderRecordLeaf(name, node.record);
      }
      const details = document.createElement("details");
      details.className = "tree-node";
      details.open = depth < 1;
      const summary = document.createElement("summary");
      summary.className = "tree-summary";
      const label = document.createElement("span");
      label.className = "tree-name";
      label.textContent = name;
      const count = document.createElement("span");
      count.className = "tree-count";
      count.textContent = countLeaves(node) + " 项";
      summary.append(label, count);
      details.append(summary);

      const children = document.createElement("div");
      children.className = "tree-children";
      for (const [childName, childNode] of sortedChildren(node)) {
        children.append(renderTreeNode(childName, childNode, depth + 1));
      }
      if (node.record) {
        children.append(renderRecordLeaf("_value", node.record));
      }
      details.append(children);
      return details;
    }

    function renderRecordLeaf(name, record) {
      const item = document.createElement("div");
      item.className = "tree-leaf";
      const head = document.createElement("div");
      head.className = "leaf-head";
      const label = document.createElement("span");
      label.className = "leaf-name";
      label.textContent = name;
      const status = document.createElement("span");
      status.className = "status-chip";
      status.textContent = record && record.status ? record.status : "";
      head.append(label, status);
      item.append(head);

      if (!record) {
        return item;
      }
      if (record.status === "missing") {
        const value = document.createElement("div");
        value.className = "leaf-value muted";
        value.textContent = "未提供";
        item.append(value);
      } else if (record.status === "conflict") {
        const details = document.createElement("details");
        details.className = "value-details";
        details.open = true;
        const summary = document.createElement("summary");
        const alternatives = record.alternatives || [];
        summary.textContent = "当前值与 " + alternatives.length + " 个候选值冲突";
        const pre = document.createElement("pre");
        pre.className = "value-json";
        pre.textContent = JSON.stringify(
          {
            current: record.value,
            alternatives: alternatives.map((item) => item.value)
          },
          null,
          2
        );
        details.append(summary, pre);
        item.append(details);
      } else if (isStructuredValue(record.value)) {
        const details = document.createElement("details");
        details.className = "value-details";
        const summary = document.createElement("summary");
        summary.textContent = valueSummary(record.value);
        const pre = document.createElement("pre");
        pre.className = "value-json";
        pre.textContent = JSON.stringify(record.value, null, 2);
        details.append(summary, pre);
        item.append(details);
      } else {
        const value = document.createElement("div");
        value.className = "leaf-value";
        value.textContent = JSON.stringify(record.value);
        item.append(value);
      }
      return item;
    }

    function sortedChildren(node) {
      return Array.from(node.children.entries()).sort(([a], [b]) => a.localeCompare(b));
    }

    function countLeaves(node) {
      let count = node.record ? 1 : 0;
      for (const child of node.children.values()) {
        count += countLeaves(child);
      }
      return count;
    }

    function isStructuredValue(value) {
      return value !== null && typeof value === "object";
    }

    function valueSummary(value) {
      if (Array.isArray(value)) {
        return "Array(" + value.length + ")";
      }
      return "Object(" + Object.keys(value || {}).length + ")";
    }

    function fileToBase64(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const bytes = new Uint8Array(reader.result);
          let binary = "";
          const chunkSize = 32768;
          for (let offset = 0; offset < bytes.length; offset += chunkSize) {
            const chunk = bytes.subarray(offset, offset + chunkSize);
            binary += String.fromCharCode.apply(null, chunk);
          }
          resolve(btoa(binary));
        };
        reader.onerror = () => reject(reader.error);
        reader.readAsArrayBuffer(file);
      });
    }

    ensureSession().catch((error) => {
      appendMessage("assistant", "初始化失败：" + error.message);
    });
  </script>
</body>
</html>
"""
