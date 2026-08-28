from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable

from qrest_agent.agent.agent import QrestAgent
from qrest_agent.agent.dialogue import ChatSession
from qrest_agent.agent.tool_registry import ToolRegistry
from qrest_agent.llm.clients import BaseLLMClient
from qrest_agent.storage.artifacts import ArtifactManager


class ApiService:
    def __init__(
        self,
        artifact_root: str | Path | None = None,
        llm_client_factory: Callable[[], BaseLLMClient | None] | None = None,
        runtime_info: dict[str, Any] | None = None,
    ) -> None:
        self.artifacts = ArtifactManager(artifact_root)
        self.sessions: dict[str, ChatSession] = {}
        self._llm_client_factory = llm_client_factory or (lambda: None)
        self.runtime_info = runtime_info or {"provider": "rule", "model": None, "extractor": "rule"}

    def create_session(self, session_id: str | None = None) -> dict[str, Any]:
        resolved = session_id or f"session-{uuid.uuid4().hex[:12]}"
        if resolved in self.sessions:
            raise ValueError(f"session already exists: {resolved}")
        agent = QrestAgent(
            llm_client=self._llm_client_factory(),
            tool_registry=ToolRegistry(self.artifacts.root),
            session_id=resolved,
        )
        session = ChatSession(agent, session_id=resolved, runtime_info=self.runtime_info)
        self.sessions[resolved] = session
        return session.to_dict()

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self._session(session_id).to_dict()

    def chat(self, session_id: str, message: str) -> dict[str, Any]:
        return self.turn(session_id, message, attachments=None)

    def upload_text(self, session_id: str, file_name: str, text: str) -> dict[str, Any]:
        """方案 §48：upload 只保存文件并登记 pending attachment，不立即触发 Agent Turn。"""
        session = self._session(session_id)
        path = self.artifacts.path(session_id, "uploads", file_name)
        path.write_text(text, encoding="utf-8")
        attachment_id = session.add_attachment(file_name, str(path), size=len(text.encode("utf-8")))
        return {
            "attachment_id": attachment_id,
            "name": file_name,
            "path": str(path),
            "size": len(text.encode("utf-8")),
            "status": "pending",
        }

    def upload_file_bytes(self, session_id: str, file_name: str, data: bytes) -> dict[str, Any]:
        """方案 §48：upload 只保存文件并登记 pending attachment，不立即触发 Agent Turn。"""
        session = self._session(session_id)
        path = self.artifacts.path(session_id, "uploads", file_name)
        path.write_bytes(data)
        attachment_id = session.add_attachment(file_name, str(path), size=len(data))
        return {
            "attachment_id": attachment_id,
            "name": file_name,
            "path": str(path),
            "size": len(data),
            "status": "pending",
        }

    def turn(self, session_id: str, message: str, attachments: list[str] | None = None) -> dict[str, Any]:
        """方案 §47：统一 Turn = message + attachments（附件随消息一起进入 Agent）。"""
        session = self._session(session_id)
        files: list[str] = []
        for attachment_id in attachments or []:
            attachment = session.attachments.get(attachment_id)
            if attachment is None:
                raise KeyError(f"unknown attachment: {attachment_id}")
            files.append(attachment["path"])
        session.mark_attachments_used(attachments or [])
        result = session.handle(message, files=files or None)
        return result.to_dict()

    def run_tool(self, session_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        session = self._session(session_id)
        args = dict(arguments)
        args.setdefault("session_id", session_id)
        result = session.agent.tools.execute(tool_name, args)
        payload = result.to_dict()
        metadata_path = result.outputs.get("metadata_json") if result.ok else None
        if metadata_path:
            update = session.agent.run_turn(files=[metadata_path])
            payload["state_update"] = update.to_dict()
        return payload

    def export_metadata(self, session_id: str, file_name: str = "metadata.json") -> dict[str, Any]:
        session = self._session(session_id)
        result = session.agent.prepare_metadata_export()
        report_path = self.artifacts.write_json(session_id, "metadata_export_report.json", result.to_dict(include_metadata=False))
        payload = result.to_dict(include_metadata=False)
        payload["artifacts"] = {"report": str(report_path)}
        if result.ok and result.metadata is not None:
            metadata_path = self.artifacts.write_json(session_id, file_name, result.metadata)
            payload["artifacts"]["metadata"] = str(metadata_path)
        return payload

    def list_artifacts(self, session_id: str) -> dict[str, Any]:
        self._session(session_id)
        return {"session_id": session_id, "artifacts": self.artifacts.list(session_id)}

    def read_artifact_text(self, session_id: str, name: str) -> dict[str, Any]:
        self._session(session_id)
        path = self.artifacts.path(session_id, *name.split("/"))
        return {"session_id": session_id, "name": name, "path": str(path), "text": path.read_text(encoding="utf-8")}

    def _session(self, session_id: str) -> ChatSession:
        try:
            return self.sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"unknown session: {session_id}") from exc
