from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from typing import Any

from qrest_agent.agent.agent import QrestAgent, TurnResult
from qrest_agent.core.models import Candidate, Evidence, ValidationReport
from qrest_agent.core.schema import QREST_FIELD_SPECS_BY_PATH
from qrest_agent.core.schema_gate import SchemaViolation
from qrest_agent.core.validator import validate_state
from qrest_agent.tools.qrest_data_tools import ToolResult


@dataclass(slots=True)
class DialogueTurn:
    role: str
    text: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "text": self.text, "payload": self.payload}


@dataclass(slots=True)
class DialogueResult:
    response: str
    report: ValidationReport
    candidates: list[Candidate] = field(default_factory=list)
    command: str | None = None
    tool_result: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    extractor: str | None = None
    fallback_reason: str | None = None
    turn: dict[str, Any] | None = None
    rejected_candidates: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "response": self.response,
            "report": self.report.to_dict(),
            "candidates": [item.to_dict() for item in self.candidates],
            "command": self.command,
            "tool_result": self.tool_result,
            "plan": self.plan,
            "extractor": self.extractor,
            "fallback_reason": self.fallback_reason,
            "turn": self.turn,
            "rejected_candidates": list(self.rejected_candidates),
        }


class ChatSession:
    """轻量对话壳：自然语言一律交给主 Agent（QrestAgent），命令保留为调试入口。

    主 Agent 的回复由 Responder 生成（LLM 自然回复 / 模板 fallback）。
    """

    def __init__(
        self,
        agent: QrestAgent | None = None,
        session_id: str = "default",
        runtime_info: dict[str, Any] | None = None,
    ) -> None:
        self.agent = agent or QrestAgent(session_id=session_id)
        if self.agent.session_id is None:
            self.agent.session_id = session_id
        self.session_id = session_id
        self.runtime_info = runtime_info or {"provider": "rule", "model": None, "extractor": "rule"}
        self.turns: list[DialogueTurn] = []
        # 附件模型（方案 §45-§48/§55）：upload 只登记为 pending，随消息一起发送才进入 Agent
        self.attachments: dict[str, dict[str, Any]] = {}
        self.last_turn: dict[str, Any] | None = None

    def add_attachment(self, name: str, path: str, size: int | None = None) -> str:
        attachment_id = f"att-{len(self.attachments) + 1}"
        self.attachments[attachment_id] = {
            "attachment_id": attachment_id,
            "name": name,
            "path": path,
            "size": size,
            "status": "pending",
        }
        return attachment_id

    def mark_attachments_used(self, attachment_ids: list[str]) -> None:
        for attachment_id in attachment_ids:
            attachment = self.attachments.get(attachment_id)
            if attachment is not None:
                attachment["status"] = "used"

    def handle(self, message: str, files: list[str] | None = None) -> DialogueResult:
        text = message.strip()
        self.turns.append(
            DialogueTurn(
                role="user",
                text=message,
                payload={"files": [str(item) for item in files or []]},
            )
        )
        if not text:
            result = self._command_help()
        elif text.startswith("/"):
            result = self._handle_command(text)
        else:
            turn_result = self.agent.run_turn(text=text, files=files)
            result = DialogueResult(
                response=turn_result.response,
                report=turn_result.report,
                candidates=turn_result.candidates,
                tool_result=turn_result.action_results or None,
                plan=turn_result.plan.to_dict() if turn_result.plan is not None else None,
                extractor=turn_result.extractor,
                fallback_reason=turn_result.fallback_reason,
                turn=_turn_summary(turn_result),
                rejected_candidates=turn_result.rejected_candidates,
            )
            self.last_turn = result.turn

        self.turns.append(DialogueTurn(role="assistant", text=result.response, payload=result.to_dict()))
        return result

    def handle_file(self, path: str) -> DialogueResult:
        self.turns.append(DialogueTurn(role="user", text=f"/file {path}"))
        turn_result = self.agent.run_turn(files=[path])
        result = DialogueResult(
            response=turn_result.response,
            report=turn_result.report,
            candidates=turn_result.candidates,
            plan=turn_result.plan.to_dict() if turn_result.plan is not None else None,
            extractor=turn_result.extractor,
            fallback_reason=turn_result.fallback_reason,
            turn=_turn_summary(turn_result),
            rejected_candidates=turn_result.rejected_candidates,
        )
        self.last_turn = result.turn
        self.turns.append(DialogueTurn(role="assistant", text=result.response, payload=result.to_dict()))
        return result

    def to_dict(self) -> dict[str, Any]:
        report = validate_state(self.agent.working_state)
        artifacts = self.agent.tools.artifacts.list(self.session_id)
        skills = self.agent.skills.list_skills()
        return {
            "session_id": self.session_id,
            "runtime": self.runtime_info,
            "report": report.to_dict(),
            "records": self.agent.working_state.to_audit_dict(),
            "artifacts": artifacts,
            "skills": [
                {
                    "name": skill.name,
                    "policy_name": skill.policy.get("name", skill.name),
                    "version": skill.policy.get("version"),
                    "description": skill.description,
                }
                for skill in skills
            ],
            "attachments": [dict(item) for item in self.attachments.values()],
            "last_turn": self.last_turn,
            "turns": [turn.to_dict() for turn in self.turns],
        }

    # ---- 命令 ----

    def _handle_command(self, text: str) -> DialogueResult:
        try:
            parts = shlex.split(text)
        except ValueError as exc:
            return self._command_result(f"命令解析失败：{exc}", command=text)
        if not parts:
            return self._command_help()

        command = parts[0].lower()
        if command in {"/help", "/?"}:
            return self._command_help()
        if command in {"/provider", "/debug"}:
            return self._command_result(_build_runtime_summary(self.runtime_info), command=command)
        if command in {"/state", "/status"}:
            return self._command_result(_build_state_summary(self.agent), command=command)
        if command == "/missing":
            return self._command_result(_build_missing_question(validate_state(self.agent.working_state)), command=command)
        if command == "/conflicts":
            return self._command_result(_build_conflict_question(self.agent), command=command)
        if command == "/file":
            return self._file(parts, command)
        if command == "/tools":
            return self._tools(command)
        if command == "/load-qrest":
            return self._load_qrest(parts, command)
        if command == "/generate-qrest":
            return self._generate_qrest(parts, command)
        if command in {"/confirm", "/set"}:
            return self._confirm(parts, command)
        if command in {"/quit", "/exit"}:
            return self._command_result("已结束当前命令行对话。", command=command)
        return self._command_result("未知命令。输入 /help 查看可用命令。", command=command)

    def _confirm(self, parts: list[str], command: str) -> DialogueResult:
        if len(parts) < 3:
            return self._command_result("用法：/confirm Field.Path value，例如 /confirm DataInfo.DT 0.02", command=command)

        field_path = parts[1]
        if field_path not in QREST_FIELD_SPECS_BY_PATH:
            return self._command_result(f"字段不在 qREST 必填路径中：{field_path}", command=command)

        raw_value = " ".join(parts[2:])
        value = _parse_confirmed_value(field_path, raw_value)
        evidence = [Evidence(source_id="user_confirmation", location="chat", text=raw_value)]
        try:
            self.agent.working_state.confirm(field_path, value, evidence, updated_by="user")
        except SchemaViolation as exc:
            # 方案 §24/§62：confirmed 也不能绕过 Schema
            return self._command_result(
                f"结构校验拒绝：{field_path} 期望 {exc.expected}，实际为 {exc.actual}。{exc.reason}",
                command=command,
            )
        report = validate_state(self.agent.working_state)
        response = f"已确认 {field_path} = {json.dumps(value, ensure_ascii=False)}。\n{_build_next_question(report, self.agent)}"
        return DialogueResult(response=response, report=report, command=command)

    def _file(self, parts: list[str], command: str) -> DialogueResult:
        if len(parts) != 2:
            return self._command_result("用法：/file path/to/source.pdf", command=command)
        try:
            turn = self.agent.run_turn(files=[parts[1]])
        except Exception as exc:
            return self._command_result(f"文件解析失败：{exc}", command=command)
        result = DialogueResult(
            response=turn.response,
            report=turn.report,
            candidates=turn.candidates,
            command=command,
        )
        return result

    def _tools(self, command: str) -> DialogueResult:
        skills = self.agent.skills.list_skills()
        lines = ["可用 skills："]
        if skills:
            for skill in skills:
                description = f" - {skill.description}" if skill.description else ""
                lines.append(f"- {skill.name}{description}: {skill.root}")
        else:
            lines.append("- 当前未注册 repo-native skill。")
        lines.append("Deterministic tools：")
        for spec in self.agent.tools.list_specs():
            lines.append(f"- {spec.name}: {spec.description}")
        lines.extend(
            [
                "低层快捷命令：",
                "/load-qrest input.qrest [source_metadata.json]",
                "/generate-qrest metadata.json data.txt [output.qrest]",
            ]
        )
        return self._command_result("\n".join(lines), command=command)

    def _load_qrest(self, parts: list[str], command: str) -> DialogueResult:
        if len(parts) not in {2, 3}:
            return self._command_result("用法：/load-qrest input.qrest [source_metadata.json]", command=command)
        arguments: dict[str, Any] = {"input_qrest": parts[1], "session_id": self.session_id}
        if len(parts) == 3:
            arguments["compare_metadata_json"] = parts[2]
        result = self.agent.tools.execute("load_qrest", arguments)
        dialogue = self._tool_result("load_qrest", result, command)
        metadata_path = result.outputs.get("metadata_json") if result.ok else None
        if metadata_path:
            turn = self.agent.run_turn(files=[metadata_path])
            dialogue.candidates = turn.candidates
            dialogue.report = turn.report
            imported = _format_candidates(turn.candidates)
            suffix = "已将解析出的 metadata 导入当前会话。"
            if imported:
                suffix = f"{suffix}\n{imported}"
            dialogue.response = f"{dialogue.response}\n{suffix}\n{_build_next_question(turn.report, self.agent)}"
        return dialogue

    def _generate_qrest(self, parts: list[str], command: str) -> DialogueResult:
        if len(parts) not in {3, 4}:
            return self._command_result("用法：/generate-qrest metadata.json data.txt [output.qrest]", command=command)
        arguments: dict[str, Any] = {"metadata_json": parts[1], "data_txt": parts[2], "session_id": self.session_id}
        if len(parts) == 4:
            arguments["output_qrest"] = parts[3]
        result = self.agent.tools.execute("generate_qrest", arguments)
        return self._tool_result("generate_qrest", result, command)

    def _tool_result(self, tool_name: str, result: ToolResult, command: str) -> DialogueResult:
        return DialogueResult(
            response=_format_tool_result(tool_name, result),
            report=validate_state(self.agent.working_state),
            command=command,
            tool_result=result.to_dict(),
        )

    def _command_help(self) -> DialogueResult:
        return self._command_result(
            "\n".join(
                [
                    "可直接输入 qREST 任务或工程描述；主 Agent 会自主选择 Skill、调用 Tool 并回复。",
                    _build_runtime_summary(self.runtime_info),
                    "自然语言任务示例：",
                    "解析 resources/qrest_data/examples/kunming2/kunming2.qrest 并导入当前项目",
                    "检查 metadata.json 和 data.txt 能不能生成 qREST",
                    "用当前项目状态和 data.txt 直接生成 qREST",
                    "可用命令：",
                    "/provider 查看当前模型/provider",
                    "/debug 查看当前模型/provider",
                    "/state 查看当前已知字段和校验状态",
                    "/missing 查看仍缺少的必要字段",
                    "/conflicts 查看冲突字段",
                    "/file path 解析上传资料",
                    "/tools 查看可用 skills 和 deterministic tools",
                    "/confirm Field.Path value 确认或修正字段值",
                    "低层快捷命令：",
                    "/load-qrest input.qrest [source_metadata.json] 解析 qREST 文件",
                    "/generate-qrest metadata.json data.txt [output.qrest] 生成 qREST 文件",
                    "/quit 结束命令行对话",
                ]
            ),
            command="/help",
        )

    def _command_result(self, response: str, command: str | None = None) -> DialogueResult:
        return DialogueResult(response=response, report=validate_state(self.agent.working_state), command=command)


def _turn_summary(turn: TurnResult) -> dict[str, Any]:
    """方案 §41/§54：结构化 Turn 摘要（intent / skills / actions / tools / extractor）。"""
    plan = turn.plan
    return {
        "intent": plan.intent if plan is not None else "unknown",
        "skills": list(plan.skills) if plan is not None else [],
        "actions": [action.to_dict() for action in plan.actions] if plan is not None else [],
        "tools": [action.tool for action in plan.actions if action.type == "tool" and action.tool] if plan is not None else [],
        "extractor": turn.extractor,
        "fallback_reason": turn.fallback_reason,
    }


def _format_candidates(candidates: list[Candidate]) -> str:
    non_empty = [candidate for candidate in candidates if candidate.value is not None]
    if not non_empty:
        return ""
    lines = ["本轮提取到："]
    for candidate in non_empty:
        value = json.dumps(candidate.value, ensure_ascii=False)
        lines.append(f"- {candidate.field_path} = {value} ({candidate.status}, confidence={candidate.confidence:.2f})")
    return "\n".join(lines)


def _format_tool_result(tool_name: str, result: ToolResult) -> str:
    status = "成功" if result.ok else "失败"
    lines = [f"工具 {tool_name} 执行{status}。"]
    if result.summary.get("readable"):
        lines.append(str(result.summary["readable"]))
    if result.warnings:
        lines.append("警告：")
        lines.extend(f"- {warning}" for warning in result.warnings)
    if result.errors:
        lines.append("错误：")
        lines.extend(f"- {error}" for error in result.errors)
    if result.outputs:
        lines.append("输出文件：")
        for name, path in result.outputs.items():
            lines.append(f"- {name}: {path}")
    if not result.ok and result.stderr:
        lines.append(f"stderr: {result.stderr.strip()}")
    return "\n".join(lines)


def _build_runtime_summary(runtime_info: dict[str, Any]) -> str:
    provider = runtime_info.get("provider", "unknown")
    model = runtime_info.get("model")
    extractor = runtime_info.get("extractor", "unknown")
    if model:
        return f"当前运行模式：provider={provider}; model={model}; extractor={extractor}"
    return f"当前运行模式：provider={provider}; extractor={extractor}"


def _build_next_question(report: ValidationReport, agent: QrestAgent) -> str:
    if report.conflicts:
        return _build_conflict_question(agent)
    if report.missing_required:
        return _build_missing_question(report)
    if report.missing_important:
        return _build_important_warning(report)
    if report.missing_optional:
        return _build_optional_note(report)
    if any(issue.level == "warning" for issue in report.issues):
        return "元数据已基本完整，但仍有警告需要复核。输入 /state 查看详情。"
    return "元数据已通过校验，可以进入导出或后续算法配置。"


def _build_missing_question(report: ValidationReport, limit: int = 6) -> str:
    if not report.missing_required:
        return "当前没有缺失的必要字段。"
    lines = ["当前仍缺少必要字段，请继续补充："]
    for path in report.missing_required[:limit]:
        spec = QREST_FIELD_SPECS_BY_PATH.get(path)
        description = f"：{spec.description}" if spec else ""
        lines.append(f"- {path}{description}")
    remaining = len(report.missing_required) - limit
    if remaining > 0:
        lines.append(f"... 还有 {remaining} 个字段未显示。输入 /missing 查看。")
    return "\n".join(lines)


def _build_important_warning(report: ValidationReport, limit: int = 6) -> str:
    lines = ["必须字段已满足，但仍缺少重要字段；导出时会使用默认值："]
    for path in report.missing_important[:limit]:
        spec = QREST_FIELD_SPECS_BY_PATH.get(path)
        description = f"：{spec.description}" if spec else ""
        lines.append(f"- {path}{description}")
    remaining = len(report.missing_important) - limit
    if remaining > 0:
        lines.append(f"... 还有 {remaining} 个重要字段未显示。")
    return "\n".join(lines)


def _build_optional_note(report: ValidationReport) -> str:
    return f"必须字段已满足，仍有 {len(report.missing_optional)} 个非关键字段缺失；导出时会留空。"


def _build_conflict_question(agent: QrestAgent) -> str:
    report = validate_state(agent.working_state)
    if not report.conflicts:
        return "当前没有冲突字段。"
    lines = ["发现字段冲突，请使用 /confirm Field.Path value 指定采用值："]
    for path in report.conflicts:
        record = agent.working_state.records.get(path)
        lines.append(f"- {path}")
        if record is not None:
            lines.append(f"  当前值：{json.dumps(record.value, ensure_ascii=False)}")
            for alternative in record.alternatives:
                lines.append(f"  候选值：{json.dumps(alternative.value, ensure_ascii=False)}")
    return "\n".join(lines)


def _build_state_summary(agent: QrestAgent) -> str:
    report = validate_state(agent.working_state)
    known = [
        (path, record)
        for path, record in sorted(agent.working_state.records.items())
        if record.value is not None and record.status not in {"missing", "empty"}
    ]
    missing_count = len(report.missing_required) + len(report.missing_important) + len(report.missing_optional)
    lines = [f"ready={report.ready}; known={len(known)}; missing={missing_count}; conflicts={len(report.conflicts)}"]
    if known:
        lines.append("当前已知字段：")
        for path, record in known:
            value = json.dumps(record.value, ensure_ascii=False)
            lines.append(f"- {path} = {value} ({record.status})")
    if report.missing_required:
        lines.append(_build_missing_question(report, limit=5))
    if report.missing_important:
        lines.append(_build_important_warning(report, limit=5))
    if report.missing_optional:
        lines.append(_build_optional_note(report))
    if report.conflicts:
        lines.append(_build_conflict_question(agent))
    return "\n".join(lines)


def _parse_confirmed_value(field_path: str, raw_value: str) -> Any:
    stripped = raw_value.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = stripped
    return _coerce_confirmed_value(field_path, parsed)


def _coerce_confirmed_value(field_path: str, value: Any) -> Any:
    spec = QREST_FIELD_SPECS_BY_PATH[field_path]
    if spec.kind == "integer" and not isinstance(value, int):
        try:
            return int(str(value).strip())
        except ValueError:
            return value
    if spec.kind == "number" and not isinstance(value, int | float):
        try:
            return float(str(value).strip())
        except ValueError:
            return value
    return value
