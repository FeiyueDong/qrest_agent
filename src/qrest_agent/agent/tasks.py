from __future__ import annotations

import re

from qrest_agent.agent.metadata_agent import MetadataAgent
from qrest_agent.agent.task_handlers import TaskHandlerRegistry, create_default_handler_registry
from qrest_agent.agent.task_models import TaskExecutionResult, TaskIntent
from qrest_agent.skills import SkillRegistry


class TaskCoordinator:
    def __init__(
        self,
        agent: MetadataAgent,
        session_id: str,
        skill_registry: SkillRegistry | None = None,
        handler_registry: TaskHandlerRegistry | None = None,
    ) -> None:
        self.handlers = handler_registry or create_default_handler_registry(agent, session_id, skill_registry=skill_registry)

    def handle(self, text: str) -> TaskExecutionResult | None:
        intent = detect_task_intent(text)
        if intent is None:
            return None
        handler = self.handlers.get(intent.name)
        if handler is None:
            return None
        return handler.handle(text, intent)


def detect_task_intent(text: str) -> TaskIntent | None:
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
