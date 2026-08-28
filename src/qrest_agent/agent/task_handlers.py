from __future__ import annotations

from typing import Any, Protocol

from qrest_agent.agent.metadata_agent import MetadataAgent
from qrest_agent.agent.task_models import TaskExecutionResult, TaskIntent
from qrest_agent.core.models import Candidate
from qrest_agent.core.validator import validate_state
from qrest_agent.skills import SkillRegistry
from qrest_agent.tools.qrest_data_tools import ToolResult


class TaskHandler(Protocol):
    name: str

    def handle(self, text: str, intent: TaskIntent) -> TaskExecutionResult:
        ...


class TaskHandlerRegistry:
    def __init__(self, handlers: list[TaskHandler] | None = None) -> None:
        self._handlers: dict[str, TaskHandler] = {}
        for handler in handlers or []:
            self.register(handler)

    def register(self, handler: TaskHandler) -> None:
        self._handlers[handler.name] = handler

    def get(self, name: str) -> TaskHandler | None:
        return self._handlers.get(name)

    def list_names(self) -> list[str]:
        return sorted(self._handlers)


class QrestDataGenerationHandler:
    name = "qrest_data_generation"

    def __init__(
        self,
        agent: MetadataAgent,
        session_id: str,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self.agent = agent
        self.session_id = session_id
        self.skills = skill_registry or SkillRegistry()

    def handle(self, text: str, intent: TaskIntent) -> TaskExecutionResult:
        try:
            skill = self.skills.load(intent.skill_name)
        except KeyError:
            return self._result(
                response=f"数据产生 skill 未注册：{intent.skill_name}，无法执行该工作流。",
                payload={"skill": intent.skill_name, "error": "skill_not_registered"},
            )

        metadata_json = intent.metadata_json
        exported_metadata_path: str | None = None
        export_payload: dict[str, Any] | None = None
        if metadata_json is None:
            export = self.agent.prepare_metadata_export()
            report_path = self.agent.tools.artifacts.write_json(
                self.session_id,
                "metadata_export_report.json",
                export.to_dict(include_metadata=False),
            )
            export_payload = export.to_dict(include_metadata=False)
            export_payload["artifacts"] = {"report": str(report_path)}
            if not export.ok or export.metadata is None:
                payload = {"skill": skill.name, "export": export_payload}
                response = format_blocked_generation_from_export(export_payload, skill.name)
                self._write_task_log(text, skill.name, intent.mode, "blocked", {"export": export_payload})
                return self._result(response=response, payload=payload)
            metadata_path = self.agent.tools.artifacts.write_json(self.session_id, "metadata.json", export.metadata)
            metadata_json = str(metadata_path)
            exported_metadata_path = str(metadata_path)
            export_payload["artifacts"]["metadata"] = exported_metadata_path

        if intent.data_txt is None:
            response = "数据产生工作流已识别，但还缺少 data.txt 路径。请提供明确的数据文本文件路径。"
            if exported_metadata_path:
                response = f"{response}\n已先导出当前会话 metadata：{exported_metadata_path}"
            payload = {"skill": skill.name, "reason": "missing_data_txt", "metadata_json": metadata_json}
            self._write_task_log(
                text,
                skill.name,
                intent.mode,
                "blocked",
                {"reason": "missing_data_txt", "metadata_json": metadata_json, "export": export_payload},
            )
            return self._result(response=response, payload=payload)

        preflight = self.agent.tools.execute(
            "preflight_generate_qrest",
            {"metadata_json": metadata_json, "data_txt": intent.data_txt, "session_id": self.session_id},
        )
        if intent.mode == "preflight" or not preflight.ok:
            status = _status_from_preflight(preflight)
            payload = {
                "skill": skill.name,
                "mode": intent.mode,
                "metadata_json": metadata_json,
                "data_txt": intent.data_txt,
                "preflight": preflight.to_dict(),
                "export": export_payload,
            }
            self._write_task_log(text, skill.name, intent.mode, status, payload)
            return self._result(
                response=format_data_generation_preflight_response(preflight, metadata_json, intent.data_txt, skill.name),
                payload=payload,
            )

        arguments: dict[str, Any] = {
            "metadata_json": metadata_json,
            "data_txt": intent.data_txt,
            "session_id": self.session_id,
            "strict": intent.strict,
        }
        if intent.output_qrest is not None:
            arguments["output_qrest"] = intent.output_qrest
        generation = self.agent.tools.execute("generate_qrest", arguments)
        status = _status_from_generation(generation)
        payload = {
            "skill": skill.name,
            "mode": intent.mode,
            "metadata_json": metadata_json,
            "data_txt": intent.data_txt,
            "strict": intent.strict,
            "preflight": preflight.to_dict(),
            "generation": generation.to_dict(),
            "export": export_payload,
        }
        self._write_task_log(text, skill.name, intent.mode, status, payload)
        return self._result(
            response=format_data_generation_generate_response(generation, preflight, skill.name),
            payload=payload,
        )

    def _result(self, response: str, payload: dict[str, Any]) -> TaskExecutionResult:
        return TaskExecutionResult(
            response=response,
            report=validate_state(self.agent.state),
            command=self.name,
            tool_result=payload,
        )

    def _write_task_log(
        self,
        user_request: str,
        skill_name: str,
        mode: str,
        status: str,
        payload: dict[str, Any],
    ) -> None:
        self.agent.tools.artifacts.write_json(
            self.session_id,
            "qrest_data_generation_task_log.json",
            {
                "user_request": user_request,
                "skill": skill_name,
                "mode": mode,
                "status": status,
                "payload": payload,
            },
        )


def create_default_handler_registry(
    agent: MetadataAgent,
    session_id: str,
    skill_registry: SkillRegistry | None = None,
) -> TaskHandlerRegistry:
    registry = TaskHandlerRegistry()
    registry.register(QrestDataGenerationHandler(agent, session_id, skill_registry=skill_registry))
    registry.register(QrestDataLoadingHandler(agent, session_id, skill_registry=skill_registry))
    return registry


def format_blocked_generation_from_export(export_payload: dict[str, Any], skill_name: str) -> str:
    blocked = export_payload.get("blocked_fields", [])
    lines = [f"已选择 skill：{skill_name}。", "当前会话 metadata 尚不能用于 qREST 数据产生，生成已停止。"]
    if blocked:
        lines.append("阻塞字段：")
        lines.extend(f"- {path}" for path in blocked)
    messages = export_payload.get("messages", [])
    if messages:
        lines.extend(str(message) for message in messages)
    return "\n".join(lines)


def format_data_generation_preflight_response(
    preflight: ToolResult,
    metadata_json: str,
    data_txt: str,
    skill_name: str,
) -> str:
    lines = [f"已选择 skill：{skill_name}。", "已完成 qREST 数据生成预检。"]
    lines.append(f"metadata: {metadata_json}")
    lines.append(f"data: {data_txt}")
    if preflight.ok:
        if preflight.warnings:
            lines.append("结论：可以生成，但输入并非完全一致。")
        else:
            lines.append("结论：可以生成，未发现预检警告。")
    else:
        lines.append("结论：预检存在硬错误，暂不生成。")
    if preflight.warnings:
        lines.append("警告：")
        lines.extend(f"- {warning}" for warning in preflight.warnings)
    if preflight.errors:
        lines.append("错误：")
        lines.extend(f"- {error}" for error in preflight.errors)
    return "\n".join(lines)


def format_data_generation_generate_response(
    generation: ToolResult,
    preflight: ToolResult,
    skill_name: str,
) -> str:
    lines = [f"已选择 skill：{skill_name}。"]
    if generation.ok:
        lines.append("qREST 数据生成已完成。")
        if preflight.warnings or generation.warnings:
            lines.append("注意：生成成功，但输入并非完全一致。")
    else:
        lines.append("qREST 数据生成失败。")
    if generation.outputs:
        lines.append("输出文件：")
        for name, path in generation.outputs.items():
            lines.append(f"- {name}: {path}")
    warnings = list(dict.fromkeys([*preflight.warnings, *generation.warnings]))
    if warnings:
        lines.append("警告：")
        lines.extend(f"- {warning}" for warning in warnings)
    if generation.errors:
        lines.append("错误：")
        lines.extend(f"- {error}" for error in generation.errors)
    return "\n".join(lines)


def _status_from_preflight(preflight: ToolResult) -> str:
    if not preflight.ok:
        return "blocked"
    return "warning" if preflight.warnings else "success"


def _status_from_generation(generation: ToolResult) -> str:
    if not generation.ok:
        return "failed"
    return "warning" if generation.warnings else "success"


class QrestDataLoadingHandler:
    name = "qrest_data_loading"

    def __init__(
        self,
        agent: MetadataAgent,
        session_id: str,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self.agent = agent
        self.session_id = session_id
        self.skills = skill_registry or SkillRegistry()

    def handle(self, text: str, intent: TaskIntent) -> TaskExecutionResult:
        try:
            skill = self.skills.load(intent.skill_name)
        except KeyError:
            return self._result(
                response=f"数据加载 skill 未注册：{intent.skill_name}，无法执行该工作流。",
                payload={"skill": intent.skill_name, "error": "skill_not_registered"},
            )

        if intent.input_qrest is None:
            payload = {"skill": skill.name, "reason": "missing_input_qrest"}
            self._write_task_log(text, skill.name, intent.mode, "blocked", payload)
            return self._result(
                response="数据加载工作流已识别，但还缺少 .qrest 文件路径。请提供明确的输入文件路径。",
                payload=payload,
            )

        arguments: dict[str, Any] = {
            "input_qrest": intent.input_qrest,
            "session_id": self.session_id,
        }
        if intent.compare_metadata_json is not None:
            arguments["compare_metadata_json"] = intent.compare_metadata_json
        load_result = self.agent.tools.execute("load_qrest", arguments)
        imported_candidates: list[Candidate] = []
        state_update: dict[str, Any] | None = None
        metadata_path = load_result.outputs.get("metadata_json") if load_result.ok else None
        if metadata_path:
            turn = self.agent.run_turn(files=[metadata_path])
            imported_candidates = turn.candidates
            state_update = turn.to_dict()

        status = _status_from_load(load_result)
        payload = {
            "skill": skill.name,
            "mode": intent.mode,
            "input_qrest": intent.input_qrest,
            "compare_metadata_json": intent.compare_metadata_json,
            "load": load_result.to_dict(),
            "state_update": state_update,
        }
        self._write_task_log(text, skill.name, intent.mode, status, payload)
        return TaskExecutionResult(
            response=format_data_loading_response(load_result, imported_candidates, skill.name),
            report=validate_state(self.agent.state),
            command=self.name,
            tool_result=payload,
        )

    def _result(self, response: str, payload: dict[str, Any]) -> TaskExecutionResult:
        return TaskExecutionResult(
            response=response,
            report=validate_state(self.agent.state),
            command=self.name,
            tool_result=payload,
        )

    def _write_task_log(
        self,
        user_request: str,
        skill_name: str,
        mode: str,
        status: str,
        payload: dict[str, Any],
    ) -> None:
        self.agent.tools.artifacts.write_json(
            self.session_id,
            "qrest_data_loading_task_log.json",
            {
                "user_request": user_request,
                "skill": skill_name,
                "mode": mode,
                "status": status,
                "payload": payload,
            },
        )


def format_data_loading_response(load_result: ToolResult, imported_candidates: list[Candidate], skill_name: str) -> str:
    lines = [f"已选择 skill：{skill_name}。"]
    if load_result.ok:
        lines.append("qREST 文件解析完成。")
    else:
        lines.append("qREST 文件解析失败。")
    readable = load_result.summary.get("readable")
    if readable:
        lines.append(str(readable))
    if imported_candidates:
        lines.append(f"已将解析出的 metadata 导入当前会话，共导入 {len(imported_candidates)} 个候选字段。")
    elif load_result.ok:
        lines.append("未从解析出的 metadata 中导入新的候选字段。")
    if load_result.warnings:
        lines.append("警告：")
        lines.extend(f"- {warning}" for warning in load_result.warnings)
    if load_result.errors:
        lines.append("错误：")
        lines.extend(f"- {error}" for error in load_result.errors)
    if load_result.outputs:
        lines.append("输出文件：")
        for name, path in load_result.outputs.items():
            lines.append(f"- {name}: {path}")
    return "\n".join(lines)


def _status_from_load(load_result: ToolResult) -> str:
    if not load_result.ok:
        return "failed"
    return "warning" if load_result.warnings else "success"
