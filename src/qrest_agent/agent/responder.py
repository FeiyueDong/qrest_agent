from __future__ import annotations

import json
from typing import Any

from qrest_agent.llm.clients import BaseLLMClient

RESPONDER_SCHEMA_HINT: dict[str, str] = {"response": "natural language reply to the user"}

RESPONDER_PROMPT = """你是 qREST 主 Agent 的回复层（只读）。

输入是可信的回合上下文（Trusted Context），包括：
- 本轮新确认的事实（new_facts）；
- 仍缺失的必要/重要字段（missing_required / missing_important）；
- 冲突字段（conflicts）；
- 工具执行结果（action_results）；
- 校验结论（report_ready）。

要求：
1. 用自然语言直接回复用户，不要输出字段路径列表式的机械文案；
2. 缺失信息时，解释为什么需要该信息（工程意义），并给出用户能理解的方式
   提供（如"告诉我局部 Y 轴与正北方向的夹角"），但不要编造数值；
3. 冲突时，用双方证据向用户解释并请其选择；
4. 工具/校验结论必须如实陈述（警告、阻断原因、产物路径）；
5. 只输出 JSON：{"response": "..."}，response 为纯文本回复，不要 JSON 外内容。
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
    if context.get("conflicts"):
        lines.append("发现字段存在冲突，请确认：" + "，".join(context["conflicts"]))
    elif context.get("missing_required"):
        lines.append("当前仍缺少必要信息：" + "，".join(context["missing_required"]))
    elif context.get("missing_important"):
        lines.append("必须字段已满足，但仍缺少重要信息，导出时会使用默认值：" + "，".join(context["missing_important"]))
    elif not context.get("report_ready", False):
        lines.append("当前状态尚未通过校验。")
    else:
        lines.append("元数据已通过校验，可以导出 qREST metadata.json。")

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
