from __future__ import annotations

from typing import Any

from qrest_agent.api.service import ApiService


def create_app(service: ApiService | None = None) -> Any:
    try:
        from fastapi import FastAPI, HTTPException
    except ModuleNotFoundError as exc:
        raise RuntimeError("FastAPI is optional. Install qrest-agent[api] to use the web API.") from exc

    api = service or ApiService()
    app = FastAPI(title="qREST Agent API", version="0.1.0")

    @app.post("/sessions")
    def create_session(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return api.create_session((payload or {}).get("session_id"))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        try:
            return api.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/turn")
    def turn(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return api.turn(
                session_id,
                str(payload.get("message", "")),
                payload.get("attachments"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/chat")
    def chat(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return api.chat(session_id, str(payload.get("message", "")))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/uploads")
    def upload_text(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return api.upload_text(session_id, str(payload["file_name"]), str(payload.get("text", "")))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/tools/{tool_name}")
    def run_tool(session_id: str, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return api.run_tool(session_id, tool_name, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/sessions/{session_id}/exports/metadata")
    def export_metadata(session_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return api.export_metadata(session_id, str((payload or {}).get("file_name", "metadata.json")))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/artifacts")
    def list_artifacts(session_id: str) -> dict[str, Any]:
        try:
            return api.list_artifacts(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/artifacts/{name}")
    def read_artifact(session_id: str, name: str) -> dict[str, Any]:
        try:
            return api.read_artifact_text(session_id, name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app
