from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from typing import Any

from qrest_agent.agent.metadata_agent import MetadataAgent, TurnResult
from qrest_agent.core.models import Candidate, Evidence, ValidationReport
from qrest_agent.core.schema import QREST_FIELD_SPECS_BY_PATH
from qrest_agent.core.validator import validate_state


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "response": self.response,
            "report": self.report.to_dict(),
            "candidates": [item.to_dict() for item in self.candidates],
            "command": self.command,
        }


class ChatSession:
    def __init__(self, agent: MetadataAgent | None = None) -> None:
        self.agent = agent or MetadataAgent()
        self.turns: list[DialogueTurn] = []

    def handle(self, message: str) -> DialogueResult:
        text = message.strip()
        self.turns.append(DialogueTurn(role="user", text=message))
        if not text:
            result = self._command_help()
        elif text.startswith("/"):
            result = self._handle_command(text)
        else:
            turn_result = self.agent.run_turn(text=text)
            result = _dialogue_from_agent_turn(turn_result, self.agent)

        self.turns.append(DialogueTurn(role="assistant", text=result.response, payload=result.to_dict()))
        return result

    def to_dict(self) -> dict[str, Any]:
        report = validate_state(self.agent.state)
        return {
            "report": report.to_dict(),
            "records": self.agent.state.to_audit_dict(),
            "turns": [turn.to_dict() for turn in self.turns],
        }

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
        if command in {"/state", "/status"}:
            return self._command_result(_build_state_summary(self.agent), command=command)
        if command == "/missing":
            return self._command_result(_build_missing_question(validate_state(self.agent.state)), command=command)
        if command == "/conflicts":
            return self._command_result(_build_conflict_question(self.agent), command=command)
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
        candidate = Candidate(
            field_path=field_path,
            value=value,
            status="confirmed",
            confidence=1.0,
            evidence=[Evidence(source_id="user_confirmation", location="chat", text=raw_value)],
        )
        self.agent.state.submit(candidate)
        report = validate_state(self.agent.state)
        response = f"已确认 {field_path} = {json.dumps(value, ensure_ascii=False)}。\n{_build_next_question(report, self.agent)}"
        return DialogueResult(response=response, report=report, candidates=[candidate], command=command)

    def _command_help(self) -> DialogueResult:
        return self._command_result(
            "\n".join(
                [
                    "可直接输入工程描述，我会提取 qREST 元信息候选值。",
                    "可用命令：",
                    "/state 查看当前已知字段和校验状态",
                    "/missing 查看仍缺少的必要字段",
                    "/conflicts 查看冲突字段",
                    "/confirm Field.Path value 确认或修正字段值",
                    "/quit 结束命令行对话",
                ]
            ),
            command="/help",
        )

    def _command_result(self, response: str, command: str | None = None) -> DialogueResult:
        return DialogueResult(response=response, report=validate_state(self.agent.state), command=command)


def _dialogue_from_agent_turn(turn: TurnResult, agent: MetadataAgent) -> DialogueResult:
    extracted = _format_candidates(turn.candidates)
    next_question = _build_next_question(turn.report, agent)
    if extracted:
        response = f"{extracted}\n{next_question}"
    else:
        response = f"我没有从这轮输入中提取到新的 qREST 候选字段。\n{next_question}"
    return DialogueResult(response=response, report=turn.report, candidates=turn.candidates)


def _format_candidates(candidates: list[Candidate]) -> str:
    non_empty = [candidate for candidate in candidates if candidate.value is not None]
    if not non_empty:
        return ""
    lines = ["本轮提取到："]
    for candidate in non_empty:
        value = json.dumps(candidate.value, ensure_ascii=False)
        lines.append(f"- {candidate.field_path} = {value} ({candidate.status}, confidence={candidate.confidence:.2f})")
    return "\n".join(lines)


def _build_next_question(report: ValidationReport, agent: MetadataAgent) -> str:
    if report.conflicts:
        return _build_conflict_question(agent)
    if report.missing_required:
        return _build_missing_question(report)
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


def _build_conflict_question(agent: MetadataAgent) -> str:
    report = validate_state(agent.state)
    if not report.conflicts:
        return "当前没有冲突字段。"
    lines = ["发现字段冲突，请使用 /confirm Field.Path value 指定采用值："]
    for path in report.conflicts:
        record = agent.state.records.get(path)
        lines.append(f"- {path}")
        if record is not None:
            lines.append(f"  当前值：{json.dumps(record.value, ensure_ascii=False)}")
            for alternative in record.alternatives:
                lines.append(f"  候选值：{json.dumps(alternative.value, ensure_ascii=False)}")
    return "\n".join(lines)


def _build_state_summary(agent: MetadataAgent) -> str:
    report = validate_state(agent.state)
    known = [
        (path, record)
        for path, record in sorted(agent.state.records.items())
        if record.value is not None and record.status not in {"missing", "empty"}
    ]
    lines = [f"ready={report.ready}; known={len(known)}; missing={len(report.missing_required)}; conflicts={len(report.conflicts)}"]
    if known:
        lines.append("当前已知字段：")
        for path, record in known:
            value = json.dumps(record.value, ensure_ascii=False)
            lines.append(f"- {path} = {value} ({record.status})")
    if report.missing_required:
        lines.append(_build_missing_question(report, limit=5))
    if report.conflicts:
        lines.append(_build_conflict_question(agent))
    return "\n".join(lines)


def _parse_confirmed_value(field_path: str, raw_value: str) -> Any:
    spec = QREST_FIELD_SPECS_BY_PATH[field_path]
    stripped = raw_value.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = stripped

    if spec.kind == "integer" and not isinstance(parsed, int):
        try:
            return int(stripped)
        except ValueError:
            return parsed
    if spec.kind == "number" and not isinstance(parsed, int | float):
        try:
            return float(stripped)
        except ValueError:
            return parsed
    return parsed
