from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from qrest_agent.core.path import get_path
from qrest_agent.core.schema import CHANNEL_REQUIRED_KEYS, QREST_FIELD_SPECS
from qrest_agent.resources import qrest_metadata_policy_path

FieldImportance = Literal["mandatory", "important", "optional"]

_COMMENT_IMPORTANCE: tuple[tuple[str, FieldImportance], ...] = (
    ("不重要", "optional"),
    ("必须", "mandatory"),
    ("重要", "important"),
)

_IMPORTANCE_RANK: dict[FieldImportance, int] = {
    "optional": 0,
    "important": 1,
    "mandatory": 2,
}


@dataclass(frozen=True, slots=True)
class FieldPolicy:
    path: str
    importance: FieldImportance
    default: Any = None


@lru_cache(maxsize=1)
def policy_template() -> dict[str, Any]:
    text = qrest_metadata_policy_path().read_text(encoding="utf-8")
    return json.loads(_strip_json_line_comments(text))


@lru_cache(maxsize=1)
def annotated_importance_map() -> dict[str, FieldImportance]:
    text = qrest_metadata_policy_path().read_text(encoding="utf-8")
    return _extract_importance_comments(text)


@lru_cache(maxsize=1)
def field_policies_by_path() -> dict[str, FieldPolicy]:
    template = policy_template()
    comments = annotated_importance_map()
    return {
        spec.path: FieldPolicy(
            path=spec.path,
            importance=_importance_for_path(spec.path, comments),
            default=deepcopy(get_path(template, spec.path)),
        )
        for spec in QREST_FIELD_SPECS
    }


def field_policy(path: str) -> FieldPolicy:
    return field_policies_by_path()[path]


def channel_key_importance(key: str) -> FieldImportance:
    comments = annotated_importance_map()
    path = f"InstrumentInfo.Channels.{key}"
    if path in comments:
        return comments[path]
    if key in CHANNEL_REQUIRED_KEYS:
        return "mandatory"
    return "optional"


def channel_key_default(key: str) -> Any:
    channels = get_path(policy_template(), "InstrumentInfo.Channels")
    if isinstance(channels, list) and channels and isinstance(channels[0], dict):
        return deepcopy(channels[0].get(key))
    return None


def channel_policy_keys() -> list[str]:
    prefix = "InstrumentInfo.Channels."
    keys = {path.removeprefix(prefix) for path in annotated_importance_map() if path.startswith(prefix)}
    keys.update(CHANNEL_REQUIRED_KEYS)
    return sorted(keys)


def is_blank(value: Any) -> bool:
    return value is None


def _importance_for_path(path: str, comments: dict[str, FieldImportance]) -> FieldImportance:
    parts = path.split(".")
    for count in range(len(parts), 0, -1):
        ancestor = ".".join(parts[:count])
        if ancestor in comments:
            return comments[ancestor]

    descendant_prefix = path + "."
    descendant_values = [importance for comment_path, importance in comments.items() if comment_path.startswith(descendant_prefix)]
    if descendant_values:
        return max(descendant_values, key=lambda importance: _IMPORTANCE_RANK[importance])
    return "optional"


def _extract_importance_comments(text: str) -> dict[str, FieldImportance]:
    result: dict[str, FieldImportance] = {}
    stack: list[tuple[int, str]] = []
    key_pattern = re.compile(r'^\s*"([^"]+)"\s*:\s*(.*)$')

    for raw_line in text.splitlines():
        code, comment = _split_line_comment(raw_line)
        stripped = code.strip()
        if not stripped:
            continue
        indent = len(code) - len(code.lstrip(" "))
        while stack and indent <= stack[-1][0]:
            stack.pop()

        match = key_pattern.match(code)
        if match is None:
            continue

        key = match.group(1)
        value_part = match.group(2)
        path = ".".join([item for _, item in stack] + [key])
        importance = _importance_from_comment(comment)
        if importance is not None:
            result[path] = importance
        if value_part.lstrip().startswith(("{", "[")):
            stack.append((indent, key))
    return result


def _importance_from_comment(comment: str | None) -> FieldImportance | None:
    if not comment:
        return None
    for token, importance in _COMMENT_IMPORTANCE:
        if token in comment:
            return importance
    return None


def _strip_json_line_comments(text: str) -> str:
    return "\n".join(_split_line_comment(line)[0] for line in text.splitlines())


def _split_line_comment(line: str) -> tuple[str, str | None]:
    in_string = False
    escape = False
    for index, char in enumerate(line):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "/" and index + 1 < len(line) and line[index + 1] == "/":
            return line[:index].rstrip(), line[index + 2 :].strip()
    return line.rstrip(), None
