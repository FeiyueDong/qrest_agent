from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from qrest_agent.core.schema import QREST_FIELD_SPECS_BY_PATH
from qrest_agent.core.validator import validate_state
from qrest_agent.llm.clients import BaseLLMClient
from qrest_agent.state import WorkingState

ActionName = Literal["none", "resolve_conflicts", "confirm_field"]
ConflictChoice = Literal["current", "alternative"]


@dataclass(slots=True)
class FieldUpdate:
    field_path: str
    value: Any


@dataclass(slots=True)
class ActionIntent:
    action: ActionName = "none"
    confidence: float = 0.0
    scope: Literal["all", "fields"] = "all"
    choice: ConflictChoice | None = None
    field_paths: list[str] = field(default_factory=list)
    updates: list[FieldUpdate] = field(default_factory=list)
    reason: str = ""
    source: str = "none"


class ActionInterpreter:
    def __init__(self, client: BaseLLMClient | None = None, confidence_threshold: float = 0.55) -> None:
        self.client = client
        self.confidence_threshold = confidence_threshold

    def interpret(self, text: str, state: WorkingState) -> ActionIntent:
        if self.client is None:
            return _fallback_interpret(text)

        try:
            parsed = self.client.complete_json(_build_action_messages(text, state), schema_hint=ACTION_SCHEMA_HINT)
        except Exception:
            return _fallback_interpret(text)

        intent = _intent_from_model(parsed)
        if intent.action == "none" or intent.confidence < self.confidence_threshold:
            fallback = _fallback_interpret(text)
            return fallback if fallback.action != "none" else intent
        intent.source = "llm"
        return _sanitize_intent(intent, state)


def should_interpret_action(text: str, state: WorkingState) -> bool:
    if validate_state(state).conflicts:
        return True
    compact = "".join(text.lower().split())
    action_tokens = (
        "确认",
        "采用",
        "使用",
        "保留",
        "更新",
        "修改",
        "更正",
        "设置",
        "设为",
        "改为",
        "按",
        "冲突",
        "候选",
        "当前值",
        "新值",
    )
    return any(token in compact for token in action_tokens)


ACTION_SCHEMA_HINT: dict[str, Any] = {
    "action": "none | resolve_conflicts | confirm_field",
    "confidence": "number between 0 and 1",
    "scope": "all | fields",
    "choice": "current | alternative | null",
    "field_paths": ["Field.Path"],
    "updates": [{"field_path": "Field.Path", "value": "confirmed value"}],
    "reason": "short explanation",
}


ACTION_SYSTEM_PROMPT = """You are an action parser for a qREST metadata agent.

Return one JSON object only. Do not answer in prose.

Your job is to decide whether the user's message is a command that should modify
metadata state. The program will execute the action after validation.

Allowed actions:
1. none
   Use this when the message is ordinary project information, a question, or
   ambiguous.

2. resolve_conflicts
   Use this only when the user wants to resolve existing conflicting fields.
   choice="alternative" means use candidate/new/imported/replacement values.
   choice="current" means keep current/existing/original values.
   scope="all" means all conflicts. scope="fields" must include field_paths.

3. confirm_field
   Use this when the user explicitly confirms or changes specific qREST fields
   and provides the target values.

Safety rules:
- Do not invent engineering values.
- Use only valid field paths from the context.
- If a field or value is unclear, return action="none".
- If the user is merely supplying new project facts, return action="none" so
  the extraction workflow can process them.
"""


def _build_action_messages(text: str, state: WorkingState) -> list[dict[str, str]]:
    report = validate_state(state)
    context = {
        "valid_field_paths": sorted(QREST_FIELD_SPECS_BY_PATH),
        "current_conflicts": [_conflict_summary(state, path) for path in report.conflicts],
    }
    return [
        {"role": "system", "content": ACTION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "Context:\n"
            + json.dumps(context, ensure_ascii=False)
            + "\n\nUser message:\n"
            + text
            + "\n\nReturn JSON with keys: action, confidence, scope, choice, field_paths, updates, reason.",
        },
    ]


def _conflict_summary(state: WorkingState, field_path: str) -> dict[str, Any]:
    record = state.records.get(field_path)
    if record is None:
        return {"field_path": field_path, "alternative_count": 0}
    return {
        "field_path": field_path,
        "current": _compact_value(record.value),
        "alternative_count": len(record.alternatives),
        "alternatives": [_compact_value(item.value) for item in record.alternatives[-3:]],
    }


def _compact_value(value: Any, limit: int = 500) -> Any:
    text = json.dumps(value, ensure_ascii=False)
    if len(text) <= limit:
        return value
    return {"summary": text[:limit] + "...", "type": type(value).__name__}


def _intent_from_model(data: dict[str, Any]) -> ActionIntent:
    action = str(data.get("action", "none"))
    if action not in {"none", "resolve_conflicts", "confirm_field"}:
        action = "none"

    scope = str(data.get("scope", "all"))
    if scope not in {"all", "fields"}:
        scope = "all"

    choice = data.get("choice")
    if choice not in {"current", "alternative", None}:
        choice = None

    updates = []
    raw_updates = data.get("updates", [])
    if not isinstance(raw_updates, list):
        raw_updates = []
    for item in raw_updates:
        if isinstance(item, dict) and "field_path" in item and "value" in item:
            updates.append(FieldUpdate(field_path=str(item["field_path"]), value=item["value"]))

    field_paths = [str(item) for item in data.get("field_paths", []) if isinstance(item, str)]
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return ActionIntent(
        action=action,  # type: ignore[arg-type]
        confidence=confidence,
        scope=scope,  # type: ignore[arg-type]
        choice=choice,  # type: ignore[arg-type]
        field_paths=field_paths,
        updates=updates,
        reason=str(data.get("reason", "")),
        source="llm",
    )


def _sanitize_intent(intent: ActionIntent, state: WorkingState) -> ActionIntent:
    valid_paths = set(QREST_FIELD_SPECS_BY_PATH)
    report = validate_state(state)
    conflicts = set(report.conflicts)
    intent.field_paths = [path for path in intent.field_paths if path in valid_paths]
    intent.updates = [item for item in intent.updates if item.field_path in valid_paths]

    if intent.action == "resolve_conflicts":
        if intent.choice not in {"current", "alternative"}:
            return ActionIntent(source=intent.source)
        if intent.scope == "fields":
            intent.field_paths = [path for path in intent.field_paths if path in conflicts]
            if not intent.field_paths:
                return ActionIntent(source=intent.source)
        elif not conflicts:
            return ActionIntent(source=intent.source)
    if intent.action == "confirm_field" and not intent.updates:
        return ActionIntent(source=intent.source)
    return intent


def _fallback_interpret(text: str) -> ActionIntent:
    choice = _parse_conflict_resolution_intent(text)
    if choice is None:
        return ActionIntent(source="fallback")
    return ActionIntent(action="resolve_conflicts", confidence=0.7, scope="all", choice=choice, source="fallback")


def _parse_conflict_resolution_intent(text: str) -> ConflictChoice | None:
    compact = "".join(text.lower().split())
    if "冲突" not in compact:
        return None
    all_conflicts = any(token in compact for token in ("全部", "所有", "都", "统一", "全都"))
    if not all_conflicts:
        return None

    alternative_tokens = (
        "候选值",
        "候选项",
        "备选值",
        "新值",
        "更新值",
        "后者",
        "替代值",
        "alternative",
        "candidate",
    )
    current_tokens = (
        "当前值",
        "原值",
        "已有值",
        "保留",
        "不更新",
        "前者",
        "current",
    )
    if any(token in compact for token in alternative_tokens):
        return "alternative"
    if any(token in compact for token in current_tokens):
        return "current"
    return None
