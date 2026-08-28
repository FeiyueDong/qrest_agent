from __future__ import annotations

"""Canonicalization Layer（方案 §3-§4）：自然语言值 → qREST 规范 ASCII 值。

- 受控字段（StructuralType/Shape/Measurand/Corrected 等）：确定性中文→英文映射；
- 自由字段（ProjectName/Provider/EventName/ChannelID 等）：不创造名称——
  非 ASCII 时保持原值并由调用方降级为 uncertain（不进最终 Metadata）；
- ASCII 是确定性约束：Exporter 最终检查、Validator 对导入值检查。
"""

from dataclasses import dataclass
from typing import Any

#: 受控字段的标准词汇（qREST 约定值；键为常见中文/别名，值为标准 ASCII）
CONTROLLED_VOCABULARY: dict[str, dict[str, str]] = {
    "StructuralType": {
        "钢框架": "SteelFrame",
        "钢结构": "SteelFrame",
        "钢筋混凝土框架": "RCFrame",
        "钢筋砼框架": "RCFrame",
        "混凝土框架": "RCFrame",
        "rc框架": "RCFrame",
        "剪力墙": "ShearWall",
        "砌体": "Masonry",
        "砖混": "Masonry",
        "钢混框架": "RCFrame",
    },
    "Shape": {
        "矩形": "Rectangular",
        "长方形": "Rectangular",
        "圆形": "Circular",
        "圆": "Circular",
        "多边形": "Polygon",
    },
    "Measurand": {
        "加速度": "Acceleration",
        "速度": "Velocity",
        "位移": "Displacement",
    },
    "Corrected": {
        "已校正": "yes",
        "已修正": "yes",
        "是": "yes",
        "校正": "yes",
        "否": "NULL",
        "未校正": "NULL",
        "无": "NULL",
    },
}

#: 受控字段路径后缀（嵌套字段按后缀识别，如 Channels[i].Measurand）
_CONTROLLED_SUFFIXES = ("StructuralType", "Shape", "Measurand", "Corrected")

#: 自由字段：资料有 ASCII 标识直接用；只有中文时不得自行翻译/创造
_FREE_TEXT_SUFFIXES = ("ProjectName", "Provider", "EventName", "ChannelID", "DeviceType")


@dataclass(slots=True)
class CanonicalizeResult:
    value: Any
    status: str  # "ok" | "mapped" | "failed"
    reason: str | None = None

    @property
    def changed(self) -> bool:
        return self.status == "mapped"


def is_ascii(text: str) -> bool:
    try:
        text.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def canonicalize_value(field_path: str, value: Any) -> CanonicalizeResult:
    """规范化单个字段值（递归处理 dict/list 中的字符串）。

    返回：
    - ok：本来就是 ASCII 标准值（或数字/结构值，或受控字段已命中标准值）；
    - mapped：中文受控值成功映射为标准英文值（value 已替换）；
    - failed：无法规范化（自由字段中文 / 受控字段未命中）——调用方应降级为 uncertain。
    """
    if isinstance(value, str):
        return _canonicalize_string(field_path, value)
    if isinstance(value, dict):
        changed = False
        output: dict[str, Any] = {}
        for key, item in value.items():
            child_path = f"{field_path}.{key}" if field_path else key
            result = canonicalize_value(child_path, item)
            output[key] = result.value
            if result.status == "mapped":
                changed = True
            elif result.status == "failed":
                return CanonicalizeResult(value, "failed", f"{child_path}: non-ASCII value cannot be canonicalized")
        return CanonicalizeResult(output, "mapped" if changed else "ok")
    if isinstance(value, list):
        output_list: list[Any] = []
        changed = False
        for index, item in enumerate(value):
            result = canonicalize_value(f"{field_path}[{index}]", item)
            output_list.append(result.value)
            if result.status == "mapped":
                changed = True
            elif result.status == "failed":
                return CanonicalizeResult(value, "failed", f"{field_path}[{index}]: non-ASCII value cannot be canonicalized")
        return CanonicalizeResult(output_list, "mapped" if changed else "ok")
    return CanonicalizeResult(value, "ok")


def _canonicalize_string(field_path: str, text: str) -> CanonicalizeResult:
    if is_ascii(text):
        return CanonicalizeResult(text, "ok")
    if text in {"NULL", "UNKNOWN"}:
        return CanonicalizeResult(text, "ok")

    suffix = _path_suffix(field_path)
    if suffix in _CONTROLLED_SUFFIXES:
        table = CONTROLLED_VOCABULARY.get(suffix, {})
        mapping = table.get(text.strip().lower()) or table.get(text.strip())
        if mapping is not None:
            return CanonicalizeResult(mapping, "mapped", f"{field_path}: mapped to {mapping}")
        return CanonicalizeResult(text, "failed", f"{field_path}: controlled value {text!r} is not in the standard vocabulary")
    if suffix in _FREE_TEXT_SUFFIXES:
        return CanonicalizeResult(text, "failed", f"{field_path}: non-ASCII free text {text!r}; do not invent an English name")
    return CanonicalizeResult(text, "failed", f"{field_path}: non-ASCII value {text!r} cannot be canonicalized")


def _path_suffix(field_path: str) -> str:
    """取路径最后一个有意义的名字（去掉数组下标）。"""
    parts = [part for part in field_path.replace("]", "").split("[") if part]
    if not parts:
        return ""
    return parts[-1].split(".")[-1]


def metadata_string_errors(metadata: dict[str, Any], field_path: str = "") -> list[str]:
    """确定性 ASCII / 受控值检查（方案 §4：Validator 与 Exporter 共用）。

    返回错误消息列表：
    - 任何字符串非 ASCII → error；
    - 受控字段（StructuralType/Shape/Measurand/Corrected）值不在标准词汇表
      （UNKNOWN/NULL 除外）→ error。
    """
    errors: list[str] = []
    _collect_string_errors(metadata, field_path, errors)
    return errors


def _collect_string_errors(value: Any, field_path: str, errors: list[str]) -> None:
    if isinstance(value, str):
        if not is_ascii(value):
            errors.append(f"{field_path}: non-ASCII string {value!r} is not allowed in metadata")
            return
        suffix = _path_suffix(field_path)
        if suffix in _CONTROLLED_SUFFIXES and value not in {"UNKNOWN", "NULL"}:
            table = CONTROLLED_VOCABULARY.get(suffix, {})
            if value not in table.values():
                errors.append(f"{field_path}: {value!r} is not a standard {suffix} value")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{field_path}.{key}" if field_path else str(key)
            _collect_string_errors(item, child_path, errors)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _collect_string_errors(item, f"{field_path}[{index}]", errors)
