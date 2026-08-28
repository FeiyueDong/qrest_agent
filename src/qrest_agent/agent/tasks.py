from __future__ import annotations

import re
from typing import Any

from qrest_agent.agent.task_models import TaskIntent


def detect_task_intent(text: str) -> TaskIntent | None:
    """检测自然语言中的 qREST 数据加载/生成任务意图（主 Agent 规划器的规则兜底）。

    仅负责“识别”，不包含任何执行逻辑；执行由 QrestAgent 按计划调用 skill handler。
    """
    loading = parse_qrest_data_loading_intent(text)
    if loading is not None:
        return loading
    return parse_qrest_data_generation_intent(text)


def parse_qrest_data_loading_intent(text: str) -> TaskIntent | None:
    lower = text.lower()
    paths = extract_paths(text)
    input_qrest = next((path for path in paths if path.lower().endswith(".qrest")), None)
    if input_qrest is None:
        return None
    loading_words = ("解析", "加载", "导入", "读取", "转换", "提取", "查看")
    if not any(word in text for word in loading_words):
        return None
    compare_metadata_json = next((path for path in paths if path.lower().endswith(".json")), None)
    mode = "import" if any(word in text for word in ("导入", "加入当前", "当前项目", "当前会话")) else "load"
    return TaskIntent(
        name="qrest_data_loading",
        skill_name="qrest_data_loading",
        mode=mode,
        input_qrest=input_qrest,
        compare_metadata_json=compare_metadata_json,
    )


def parse_qrest_data_generation_intent(text: str) -> TaskIntent | None:
    lower = text.lower()
    mentions_qrest = "qrest" in lower or ".qrest" in lower
    action_words = ("生成", "产生", "预检", "检查", "能不能", "是否可以", "看看", "校验")
    if not mentions_qrest or not any(word in text for word in action_words):
        return None

    paths = extract_paths(text)
    metadata_json = next((path for path in paths if path.lower().endswith(".json")), None)
    data_txt = next((path for path in paths if path.lower().endswith(".txt")), None)
    output_qrest = next((path for path in paths if path.lower().endswith(".qrest")), None)
    strict = any(word in text for word in ("严格", "不一致就停止", "warning 也停止", "警告也停止"))
    preflight_only = any(word in text for word in ("预检", "检查", "能不能", "是否可以", "看看", "校验")) and not any(
        word in text for word in ("直接生成", "开始生成", "生成到", "输出到")
    )
    mode = "preflight" if preflight_only else "generate"
    return TaskIntent(
        name="qrest_data_generation",
        skill_name="qrest_data_generation",
        mode=mode,
        metadata_json=metadata_json,
        data_txt=data_txt,
        output_qrest=output_qrest,
        strict=strict,
    )


def extract_paths(text: str) -> list[str]:
    matches = re.findall(r"(?<![\w.-])([^\s，。；;：:]+?\.(?:json|txt|qrest))(?![\w.-])", text, flags=re.IGNORECASE)
    cleaned: list[str] = []
    for match in matches:
        path = match.strip("\"'“”‘’()（）[]【】")
        if path and path not in cleaned:
            cleaned.append(path)
    return cleaned


def intent_to_arguments(intent: TaskIntent) -> dict[str, Any]:
    """TaskIntent → AgentPlan.tool_arguments（供主 Agent 计划传递）。"""
    return {
        "mode": intent.mode,
        "metadata_json": intent.metadata_json,
        "data_txt": intent.data_txt,
        "output_qrest": intent.output_qrest,
        "input_qrest": intent.input_qrest,
        "compare_metadata_json": intent.compare_metadata_json,
        "strict": intent.strict,
    }


def intent_from_arguments(skill_name: str, arguments: dict[str, Any]) -> TaskIntent | None:
    """AgentPlan.tool_arguments → TaskIntent；skill 或参数非法时返回 None。"""
    if skill_name not in {"qrest_data_generation", "qrest_data_loading"}:
        return None
    mode = str(arguments.get("mode") or "")
    if skill_name == "qrest_data_generation":
        if mode not in {"preflight", "generate"}:
            mode = "preflight"
    elif mode not in {"load", "import"}:
        mode = "load"
    return TaskIntent(
        name=skill_name,
        skill_name=skill_name,
        mode=mode,
        metadata_json=_optional_string(arguments.get("metadata_json")),
        data_txt=_optional_string(arguments.get("data_txt")),
        output_qrest=_optional_string(arguments.get("output_qrest")),
        input_qrest=_optional_string(arguments.get("input_qrest")),
        compare_metadata_json=_optional_string(arguments.get("compare_metadata_json")),
        strict=bool(arguments.get("strict", False)),
    )


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None
