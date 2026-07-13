from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from qrest_agent.agent.dialogue import ChatSession
from qrest_agent.agent.metadata_agent import MetadataAgent
from qrest_agent.agent.tool_registry import ToolRegistry
from qrest_agent.storage.artifacts import ArtifactManager


class ApiService:
    def __init__(self, artifact_root: str | Path | None = None) -> None:
        self.artifacts = ArtifactManager(artifact_root)
        self.sessions: dict[str, ChatSession] = {}

    def create_session(self, session_id: str | None = None) -> dict[str, Any]:
        resolved = session_id or f"session-{uuid.uuid4().hex[:12]}"
        if resolved in self.sessions:
            raise ValueError(f"session already exists: {resolved}")
        agent = MetadataAgent(tool_registry=ToolRegistry(self.artifacts.root))
        session = ChatSession(agent, session_id=resolved)
        self.sessions[resolved] = session
        return session.to_dict()

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self._session(session_id).to_dict()

    def chat(self, session_id: str, message: str) -> dict[str, Any]:
        result = self._session(session_id).handle(message)
        return result.to_dict()

    def upload_text(self, session_id: str, file_name: str, text: str) -> dict[str, Any]:
        session = self._session(session_id)
        path = self.artifacts.path(session_id, "uploads", file_name)
        path.write_text(text, encoding="utf-8")
        result = session.handle_file(str(path))
        payload = result.to_dict()
        payload["uploaded"] = {"file_name": file_name, "path": str(path)}
        return payload

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

    def list_artifacts(self, session_id: str) -> dict[str, Any]:
        self._session(session_id)
        return {"session_id": session_id, "artifacts": self.artifacts.list(session_id)}

    def read_artifact_text(self, session_id: str, name: str) -> dict[str, Any]:
        self._session(session_id)
        path = self.artifacts.path(session_id, name)
        return {"session_id": session_id, "name": name, "path": str(path), "text": path.read_text(encoding="utf-8")}

    def _session(self, session_id: str) -> ChatSession:
        try:
            return self.sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"unknown session: {session_id}") from exc
