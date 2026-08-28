from __future__ import annotations

import json
from typing import Any

from qrest_agent.llm.clients import BaseLLMClient

RESPONDER_SCHEMA_HINT: dict[str, str] = {"response": "natural language reply to the user"}

RESPONDER_PROMPT = """你是 qREST 主 Agent 的回复层（只读）。

输入是严格分类的可信回合上下文（Trusted Context），包括：
- accepted_facts：Working State 合并后可接受的工程事实（confirmed / extracted / derived）；
- uncertain：来源模糊、需要确认的候选；
- inferred：工程推测，不进入正式 Metadata；
- conflicts：存在冲突的字段；
- missing_required / missing_important：仍缺失的必要/重要字段；
- requested_inputs：本轮 ask Action 的结构化请求（reason / request / expected）；
- tool_results / action_results：工具执行结果（含失败）；
- recent_conversation：最近对话摘要（user / intent / accepted_facts / assistant_summary）；
- report_ready：确定性 Validator 的结论。

事实规则（语言确定程度必须与 Working State 一致）：
- accepted_facts：可以作为事实陈述；
- uncertain：只能描述为“可能/资料中存在候选，需要确认”；
- inferred：只能描述为“推测，不会进入正式 Metadata”；
- conflict：必须向用户说明存在冲突并请其确认；
- missing：只能询问，绝不能补充或编造数值。

要求：
1. 用自然语言直接回复用户，不要输出字段路径列表式的机械文案；
2. 有 requested_inputs 时优先按其 request 询问用户（说明为什么需要、怎么提供）；
   缺失信息时解释工程意义并给出用户能理解的方式，但不要编造数值；
3. 冲突时，用双方证据向用户解释并请其选择；
4. 工具/校验结论必须如实陈述（警告、阻断原因、产物路径）；
5. recent_conversation 只用于理解用户指代（如“刚才那项”“按前面的值”）；
   对话历史不是工程事实来源——任何与 accepted_facts 冲突的历史信息都不得使用；
6. 只输出 JSON：{"response": "..."}，response 为纯文本回复，不要 JSON 外内容。
""".strip()


class Responder:
    """最终回复生成器（设计文档 §16）：LLM 自然回复；无 LLM/失败时模板 fallback。

    Responder 是纯输出层：只读 Trusted Context，不得产生 Candidate 或修改状态。
    """

    def __init__(self, llm_client: BaseLLMClient | None = None) -> None:
        self.llm_client = llm_client

    def respond(self, trusted_context: dict[str, Any]) -> str:
        if self.llm_client is None:
            return build_template_response(trusted_context)
        try:
            messages = [
                {"role": "system", "content": RESPONDER_PROMPT},
                {
                    "role": "user",
                    "content": "Trusted context:\n" + json.dumps(trusted_context, ensure_ascii=False, default=str),
                },
            ]
            parsed = self.llm_client.complete_json(messages, schema_hint=RESPONDER_SCHEMA_HINT)
            text = str(parsed.get("response") or parsed.get("reply") or "").strip()
            return text or build_template_response(trusted_context)
        except Exception:
            return build_template_response(trusted_context)


def build_template_response(context: dict[str, Any]) -> str:
    """模板 fallback 回复（debug/无模型模式；正式模式由 LLM Responder 接管）。"""
    lines: list[str] = []
    requested = context.get("requested_inputs") or []
    if requested:
        for item in requested[:3]:
            if isinstance(item, dict) and item.get("request"):
                lines.append(str(item["request"]))
        if context.get("missing_required"):
            lines.append("仍缺少必要信息：" + "、".join(context["missing_required"][:8]))
    elif context.get("conflicts"):
        lines.append("发现字段存在冲突，请确认：" + "，".join(context["conflicts"]))
    elif context.get("missing_required"):
        lines.append("当前仍缺少必要信息：" + "，".join(context["missing_required"]))
    elif context.get("missing_important"):
        lines.append("必须字段已满足，但仍缺少重要信息，导出时会使用默认值：" + "，".join(context["missing_important"]))
    elif not context.get("report_ready", False):
        lines.append("当前状态尚未通过校验。")
    else:
        lines.append("元数据已通过校验，可以导出 qREST metadata.json。")

    for item in context.get("uncertain", [])[:5]:
        field = item.get("field", "?")
        lines.append(f"{field} 的资料表述不确定（uncertain），需要进一步确认。")
    for item in context.get("inferred", [])[:5]:
        field = item.get("field", "?")
        lines.append(f"{field} 为工程推测（inferred），不会进入正式 metadata。")

    for name, result in context.get("action_results", {}).items():
        if not isinstance(result, dict):
            continue
        if name == "export":
            if result.get("blocked_fields"):
                lines.append("导出被阻断：" + "，".join(result["blocked_fields"]))
            if result.get("metadata_json"):
                lines.append(f"已导出 metadata：{result['metadata_json']}")
        elif name.startswith("tool:"):
            tool = name.removeprefix("tool:")
            if result.get("ok") is False:
                lines.append(f"工具 {tool} 执行失败。")
            elif result.get("ok") is True or "chunks" in result or "frequency" in result:
                lines.append(f"工具 {tool} 执行成功。")
            for warning in (result.get("warnings") or [])[:5]:
                lines.append(f"警告：{warning}")
            for error in (result.get("errors") or [])[:5]:
                lines.append(f"错误：{error}")
            outputs = result.get("outputs") or {}
            for key, value in outputs.items():
                lines.append(f"输出 {key}: {value}")
    for item in context.get("derivation_results", []):
        if item.get("tool") == "calculate_frequency":
            lines.append(f"工具计算：Frequency = 1 / DT = {item.get('value')} Hz")
        elif item.get("tool") == "derive_counts":
            source = ", ".join(item.get("derived_from") or [])
            lines.append(f"工具推导：{item.get('field_path')} = {item.get('value')}（derived_from {source}）")
    return "\n".join(line for line in lines if line)
