from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from qrest_agent.agent.tasks import TaskIntent, detect_task_intent
from qrest_agent.agent.tool_registry import ToolRegistry
from qrest_agent.llm.clients import BaseLLMClient
from qrest_agent.skills import SkillRegistry

PlanIntent = Literal["collect_metadata", "correction", "question", "qrest_task", "status", "unknown"]
ActionType = Literal["extract", "tool", "ask", "respond", "export"]

_ALLOWED_INTENTS = {"collect_metadata", "correction", "question", "qrest_task", "status", "unknown"}
_ALLOWED_ACTION_TYPES = {"extract", "tool", "ask", "respond", "export"}


@dataclass(slots=True)
class ActionSpec:
    """Plan 中的单个基础动作（设计文档 §8：只允许 extract/tool/ask/respond/export）。"""

    type: ActionType
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "tool": self.tool, "arguments": self.arguments}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionSpec":
        return cls(
            type=data.get("type", "extract"),  # type: ignore[arg-type]
            tool=data.get("tool"),
            arguments=data.get("arguments") if isinstance(data.get("arguments"), dict) else {},
        )


@dataclass(slots=True)
class TurnPlan:
    """统一 Plan Schema：intent + skills + actions（设计文档 §7/§8）。"""

    intent: PlanIntent = "unknown"
    skills: list[str] = field(default_factory=list)
    actions: list[ActionSpec] = field(default_factory=list)
    need_user_input: bool = False
    reason: str = ""
    source: str = "rule"

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "skills": list(self.skills),
            "actions": [action.to_dict() for action in self.actions],
            "need_user_input": self.need_user_input,
            "reason": self.reason,
            "source": self.source,
        }


class AgentPlanner:
    """LLM 决策 + Skill 动态选择的规划器（设计文档 §7/§8）。

    正常路径：
      1. LLM 根据 Skill 摘要选择 intent + skills；
      2. 程序加载完整 SKILL.md；
      3. LLM 阅读 Skill 后生成 actions。

    LLM 不可用/失败时使用规则兜底（只允许作为 fallback）。
    """

    def __init__(
        self,
        skill_registry: SkillRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.skills = skill_registry or SkillRegistry()
        self.tools = tool_registry or ToolRegistry()

    def plan(self, text: str, context: dict[str, Any], llm_client: BaseLLMClient | None) -> TurnPlan:
        if llm_client is None:
            return rule_plan(text, context)
        try:
            selection = llm_client.complete_json(
                _intent_selection_messages(text, context, self.skills.summaries()),
                schema_hint=INTENT_SCHEMA_HINT,
            )
            intent, selected_skills, need_user_input, reason = _sanitize_selection(selection, self.skills)
            if not selected_skills:
                selected_skills = ["metadata"]
            skill_texts = [
                {"name": skill_name, "instructions": self.skills.load(skill_name).instructions}
                for skill_name in selected_skills
            ]
            planning = llm_client.complete_json(
                _action_planning_messages(text, context, skill_texts, intent),
                schema_hint=ACTION_SCHEMA_HINT,
            )
            return _plan_from_model(planning, self.tools, intent=intent, skills=selected_skills,
                                    need_user_input=need_user_input, reason=reason)
        except Exception:
            return rule_plan(text, context)


def rule_plan(text: str, context: dict[str, Any] | None = None) -> TurnPlan:
    """规则兜底：识别 qREST 加载/生成任务 → 相应 Tool actions；否则 collect_metadata + extract。

    仅用于 LLM 不可用/失败的 fallback 路径（设计文档 §6）。
    """
    intent = detect_task_intent(text)
    if intent is not None:
        return _qrest_rule_plan(intent, context or {})
    return TurnPlan(
        intent="collect_metadata",
        skills=["metadata"],
        actions=[ActionSpec(type="extract")],
        reason="rule fallback: collect metadata",
        source="rule",
    )


def _qrest_rule_plan(intent: TaskIntent, context: dict[str, Any]) -> TurnPlan:
    session_id = context.get("session_id")
    session_args = {"session_id": session_id} if session_id else {}

    if intent.name == "qrest_data_loading":
        actions = [
            ActionSpec(
                type="tool",
                tool="load_qrest",
                arguments={"input_qrest": intent.input_qrest, **session_args},
            ),
            ActionSpec(type="extract", arguments={"files": ["$tool:load_qrest.metadata_json"]}),
        ]
        return TurnPlan(
            intent="qrest_task",
            skills=["qrest_data"],
            actions=actions,
            reason="rule fallback: load .qrest and import metadata",
            source="rule",
        )

    # qrest_data_generation
    actions: list[ActionSpec] = []
    if intent.metadata_json is not None:
        metadata_source = intent.metadata_json
    else:
        actions.append(ActionSpec(type="export", arguments={}))
        metadata_source = "$export.metadata_json"
    if intent.data_txt is None:
        return TurnPlan(
            intent="qrest_task",
            skills=["qrest_data"],
            actions=actions,
            need_user_input=True,
            reason="missing data_txt path; ask the user",
            source="rule",
        )
    if intent.mode == "preflight":
        actions.append(
            ActionSpec(
                type="tool",
                tool="preflight_generate_qrest",
                arguments={"metadata_json": metadata_source, "data_txt": intent.data_txt, **session_args},
            )
        )
    else:
        actions.append(
            ActionSpec(
                type="tool",
                tool="generate_qrest",
                arguments={"metadata_json": metadata_source, "data_txt": intent.data_txt, **session_args},
            )
        )
    return TurnPlan(
        intent="qrest_task",
        skills=["qrest_data"],
        actions=actions,
        reason="rule fallback: qREST generation task",
        source="rule",
    )


INTENT_SCHEMA_HINT: dict[str, str] = {
    "intent": "collect_metadata | correction | question | qrest_task | status | unknown",
    "skills": ["skill names from the provided list"],
    "need_user_input": "bool",
    "reason": "short explanation",
}

ACTION_SCHEMA_HINT: dict[str, Any] = {
    "actions": [
        {
            "type": "extract | tool | ask | respond | export",
            "tool": "registered tool name or null",
            "arguments": {"tool argument": "value"},
        }
    ],
    "reason": "short explanation",
}

AGENT_INTENT_PROMPT = """你是 qREST 主 Agent 的意图与 Skill 选择步骤。

给定用户消息与当前状态，选择意图类型：
- collect_metadata：用户提供新的工程资料/描述，需要提取信息；
- correction：用户修改或纠正之前的信息（应产生 confirmed 候选）；
- question：用户询问当前状态或解释；
- qrest_task：用户要求读取/生成 .qrest 文件；
- status：用户查看状态（等价 question）；
- unknown：无法判断。

同时从可用 Skill 摘要中选择相关 Skill（最多 4 个）。Skill 将在下一步以完整
内容提供给你阅读，因此只选与当前任务专业相关的。

只输出 JSON：{"intent": ..., "skills": [...], "need_user_input": bool, "reason": "..."}
""".strip()

AGENT_ACTION_PROMPT = """你是 qREST 主 Agent 的规划步骤。你已经阅读了所选 Skill 的完整内容。

生成本轮动作列表，基础动作只允许：
- extract：从用户消息/文件提取候选事实（evidence 必须来自资料原文）；
- tool：调用已注册 Tool（输入必须来自用户消息或当前状态，禁止编造）；
- ask：需要用户补充信息（如缺失的必要字段、文件路径）；
- respond：基于当前可信状态直接回复；
- export：按导出策略从 Working State 生成 metadata（写 artifacts/metadata.json）。

规则：
1. 用户提供资料 → 先 extract；需要先读文件 → 先 tool(read_document) 再 extract。
2. 用户修正 → extract 并返回 status="confirmed" 的候选（evidence 为用户消息）。
3. 缺失关键信息无法继续 → ask + need_user_input=true。
4. qREST 文件任务 → 按 qrest_data Skill 的流程生成 tool actions（export 后再
   preflight/generate 或 load_qrest 后 extract）。
5. 不要创造工程数值、不要猜测文件路径、不要声称数据可信——Validator 决定。
6. 若无需更多动作即可回复 → respond。

只输出 JSON：{"actions": [{"type": ..., "tool": ..., "arguments": {...}}], "reason": "..."}
""".strip()


def _intent_selection_messages(text: str, context: dict[str, Any], summaries: list[dict[str, str]]) -> list[dict[str, str]]:
    payload = {
        "user_message": text,
        "current_state": _compact_state(context),
        "available_skills": summaries,
    }
    return [
        {"role": "system", "content": AGENT_INTENT_PROMPT},
        {"role": "user", "content": "Context:\n" + json.dumps(payload, ensure_ascii=False, default=str)},
    ]


def _action_planning_messages(
    text: str,
    context: dict[str, Any],
    skill_texts: list[dict[str, str]],
    intent: str,
) -> list[dict[str, str]]:
    payload = {
        "user_message": text,
        "intent": intent,
        "current_state": _compact_state(context),
        "selected_skills": skill_texts,
        "available_tools": context.get("tool_schemas") or context.get("tool_names", []),
    }
    return [
        {"role": "system", "content": AGENT_ACTION_PROMPT},
        {"role": "user", "content": "Context:\n" + json.dumps(payload, ensure_ascii=False, default=str)},
    ]


def _compact_state(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "known_fields": context.get("known_fields", {}),
        "missing_required": context.get("missing_required", []),
        "missing_important": context.get("missing_important", []),
        "conflicts": context.get("conflicts", []),
        "recent_turns": context.get("recent_turns", [])[-4:],
    }


def _sanitize_selection(
    data: dict[str, Any], registry: SkillRegistry
) -> tuple[PlanIntent, list[str], bool, str]:
    intent = str(data.get("intent", "unknown"))
    if intent not in _ALLOWED_INTENTS:
        intent = "unknown"
    known = set(registry.list_names())
    skills = [str(item) for item in data.get("skills", []) if isinstance(item, str) and item in known]
    skills = list(dict.fromkeys(skills))[:4]
    need_user_input = bool(data.get("need_user_input", False))
    reason = str(data.get("reason", ""))
    return intent, skills, need_user_input, reason  # type: ignore[return-value]


def _plan_from_model(
    data: dict[str, Any],
    tools: ToolRegistry,
    *,
    intent: PlanIntent,
    skills: list[str],
    need_user_input: bool,
    reason: str,
) -> TurnPlan:
    known_tools = {spec.name for spec in tools.list_specs()}
    actions: list[ActionSpec] = []
    raw_actions = data.get("actions", [])
    if not isinstance(raw_actions, list):
        raw_actions = []
    for item in raw_actions:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type", ""))
        if action_type not in _ALLOWED_ACTION_TYPES:
            continue
        spec = ActionSpec.from_dict(item)
        if spec.type == "tool":
            if spec.tool not in known_tools:
                continue
            if not isinstance(spec.arguments, dict):
                spec.arguments = {}
        actions.append(spec)
    if not actions:
        actions = [ActionSpec(type="extract")]
    return TurnPlan(
        intent=intent,
        skills=skills,
        actions=actions,
        need_user_input=need_user_input,
        reason=reason or str(data.get("reason", "")),
        source="llm",
    )
