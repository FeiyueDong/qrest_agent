from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from qrest_agent.core.schema import QREST_FIELD_SPECS_BY_PATH
from qrest_agent.resources import qrest_schema_path

#: JSON Schema 类型名 → Python 判定
_BOOL_IS_NOT_NUMBER = "bool is not accepted for integer/number"


class SchemaViolation(Exception):
    """结构非法值写入 Working State 时抛出（方案 §23/§25：confirmed/derived 也不能绕过）。"""

    def __init__(self, field_path: str, expected: str | None, actual: str | None, reason: str) -> None:
        super().__init__(f"{field_path}: {reason or 'schema violation'}")
        self.field_path = field_path
        self.expected = expected
        self.actual = actual
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_path": self.field_path,
            "expected": self.expected,
            "actual": self.actual,
            "reason": self.reason,
            "rejected": True,
        }


@dataclass(slots=True)
class FieldValidationResult:
    """方案 §67：字段值校验结果（Candidate Gate / Validator / Exporter 共用）。"""

    valid: bool
    field_path: str
    expected: str | None = None
    actual: str | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "field_path": self.field_path,
            "expected": self.expected,
            "actual": self.actual,
            "errors": list(self.errors),
        }


@lru_cache(maxsize=1)
def metadata_schema() -> dict[str, Any]:
    """权威 Schema（方案 §7）：resources/qrest_data/schema/metadata_schema.json。"""
    return json.loads(qrest_schema_path().read_text(encoding="utf-8"))


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "boolean":
        return isinstance(value, bool)
    return True


def _node_for_path(field_path: str) -> dict[str, Any] | None:
    """沿 JSON Schema properties 链解析字段路径节点。

    支持数组 items 嵌套（如 InstrumentInfo.Channels 的 items）。
    只解析到 field_path 本身；items 内部的子路径（如 Channels.ChannelNo）
    由校验器在数组元素上执行。
    """
    schema = metadata_schema()
    current: Any = schema
    for part in field_path.split("."):
        if not isinstance(current, dict):
            return None
        if "properties" in current and isinstance(current["properties"], dict):
            if part in current["properties"]:
                current = current["properties"][part]
                continue
        # array items 内部：继续沿 items.properties
        if "items" in current and isinstance(current["items"], dict):
            items = current["items"]
            if "properties" in items and isinstance(items["properties"], dict) and part in items["properties"]:
                current = items["properties"][part]
                continue
        return None
    return current if isinstance(current, dict) else None


def validate_field_value(
    field_path: str,
    value: Any,
    *,
    shape_only: bool = False,
) -> FieldValidationResult:
    """方案 §12/§67：统一字段校验。

    - shape_only=True：Candidate Gate / Working State 用。只检查最外层类型与
      数组元素基本类型（§13/§17-§18 的基础形状；§54 完整 mandatory key 留给 Validator）。
    - shape_only=False：Validator / Exporter 用。完整结构校验
      （nested required keys、properties 类型、prefixItems/minItems 等）。
    """
    if value is None:
        return FieldValidationResult(valid=True, field_path=field_path)

    node = _node_for_path(field_path)
    if node is None:
        return _validate_from_field_spec(field_path, value)

    errors: list[str] = []
    if shape_only:
        _validate_shape(value, node, field_path, errors)
    else:
        _validate_node(value, node, field_path, errors)
    if errors:
        return FieldValidationResult(
            valid=False,
            field_path=field_path,
            expected=_expected_summary(node),
            actual=type_name(value),
            errors=errors,
        )
    return FieldValidationResult(valid=True, field_path=field_path)


def validate_shape(field_path: str, value: Any) -> FieldValidationResult:
    """形状门（Candidate / Working State 写入前，方案 §12-§18）。"""
    return validate_field_value(field_path, value, shape_only=True)


def validate_full(field_path: str, value: Any) -> FieldValidationResult:
    """完整结构门（Validator / Export Final Gate，方案 §26-§34）。"""
    return validate_field_value(field_path, value, shape_only=False)


def schema_context_text() -> str:
    """方案 §9-§10/§76：给 LLM 的字段结构上下文（Extraction 时注入）。"""
    lines: list[str] = ["Field schema (structure is a hard contract; do not invent shapes):"]
    for spec in QREST_FIELD_SPECS_BY_PATH.values():
        node = _node_for_path(spec.path)
        if node is not None:
            lines.append(f"- {spec.path}: {_schema_summary(node, spec.description)}")
        else:
            lines.append(f"- {spec.path}: {spec.kind} ({spec.description})")

    channels_node = _node_for_path("InstrumentInfo.Channels")
    if channels_node is not None:
        lines.append("InstrumentInfo.Channels structure: array of objects, each requires: " + ", ".join(
            f"{key} ({_schema_summary(sub, '')})" for key, sub in channels_node.get("items", {}).get("properties", {}).items()
        ))

    lines.extend(
        [
            "",
            "Distinguish count fields from array fields (never substitute one for the other):",
            "- InstrumentInfo.ChannelNum: integer = number of monitoring channels.",
            "  '系统共布置18个传感器' supports ChannelNum=18 only. Channels must be an array of channel objects; never write Channels=18.",
            "- BuildingInfo.ElevationNum: integer = number of elevation entries.",
            "  '建筑有16个标高层' supports ElevationNum=16 only. Elevation must be an array of numbers; never write Elevation=16.",
            "- BuildingInfo.StructuralFootprint.Parameters / BoundingBox: objects, never numbers or strings.",
        ]
    )
    return "\n".join(lines)


def _validate_shape(value: Any, node: dict[str, Any], path: str, errors: list[str]) -> None:
    if "type" in node:
        expected = node["type"]
        if expected == "array":
            if not isinstance(value, list):
                errors.append(f"{path}: expected array, got {type_name(value)}")
                return
            item_type = (node.get("items") or {}).get("type")
            if item_type is not None:
                for index, item in enumerate(value):
                    if not _matches_type(item, item_type):
                        errors.append(f"{path}[{index}]: expected item type {item_type}, got {type_name(item)}")
            return
        if expected == "object":
            if not isinstance(value, dict):
                errors.append(f"{path}: expected object, got {type_name(value)}")
            return
        if not _matches_type(value, expected):
            errors.append(f"{path}: expected {expected}, got {type_name(value)}")
        return
    if "const" in node and value != node["const"]:
        errors.append(f"{path}: expected const {node['const']!r}, got {value!r}")


def _validate_node(value: Any, node: dict[str, Any], path: str, errors: list[str]) -> None:
    """轻量 JSON Schema 子集校验（type/const/items/prefixItems/minItems/maxItems/required/properties）。"""
    if "const" in node:
        if value != node["const"]:
            errors.append(f"{path}: expected const {node['const']!r}, got {value!r}")
        return
    if "type" in node:
        expected = node["type"]
        if not _matches_type(value, expected):
            errors.append(f"{path}: expected {expected}, got {type_name(value)}")
            return

    if isinstance(value, list):
        items = node.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                _validate_node(item, items, f"{path}[{index}]", errors)
        prefix_items = node.get("prefixItems")
        if isinstance(prefix_items, list):
            for index, item in enumerate(value):
                if index < len(prefix_items) and isinstance(prefix_items[index], dict):
                    _validate_node(item, prefix_items[index], f"{path}[{index}]", errors)
                elif index >= len(prefix_items):
                    errors.append(f"{path}[{index}]: unexpected extra item")
        if "minItems" in node and len(value) < node["minItems"]:
            errors.append(f"{path}: expected at least {node['minItems']} items, got {len(value)}")
        if "maxItems" in node and len(value) > node["maxItems"]:
            errors.append(f"{path}: expected at most {node['maxItems']} items, got {len(value)}")

    if isinstance(value, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            for key, sub_node in properties.items():
                if key in value:
                    _validate_node(value[key], sub_node, f"{path}.{key}", errors)
        for key in node.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required key {key!r}")


def _validate_from_field_spec(field_path: str, value: Any) -> FieldValidationResult:
    """JSON Schema 未覆盖时的 FieldSpec 类型兜底（保持单一来源优先，仅作防御）。"""
    spec = QREST_FIELD_SPECS_BY_PATH.get(field_path)
    if spec is None:
        return FieldValidationResult(valid=True, field_path=field_path)
    mapping = {
        "string": "string",
        "integer": "integer",
        "number": "number",
        "array": "array",
        "object": "object",
    }
    expected = mapping.get(spec.kind)
    if expected is not None and not _matches_type(value, expected):
        return FieldValidationResult(
            valid=False,
            field_path=field_path,
            expected=expected,
            actual=type_name(value),
            errors=[f"{field_path}: expected {expected}, got {type_name(value)}"],
        )
    return FieldValidationResult(valid=True, field_path=field_path)


def _expected_summary(node: dict[str, Any]) -> str:
    if "type" in node:
        if node["type"] == "array" and isinstance(node.get("items"), dict):
            return f"array<{node['items'].get('type', 'any')}>"
        return str(node["type"])
    if "const" in node:
        return f"const {node['const']!r}"
    return "unknown"


def _schema_summary(node: dict[str, Any], description: str) -> str:
    summary = _expected_summary(node)
    if description:
        return f"{summary} ({description})"
    return summary
