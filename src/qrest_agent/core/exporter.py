from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from qrest_agent.core.metadata_policy import (
    channel_key_default,
    channel_key_importance,
    channel_policy_keys,
    field_policies_by_path,
    is_blank,
)
from qrest_agent.core.models import ValidationReport
from qrest_agent.core.path import get_path, set_path
from qrest_agent.core.schema import DEFAULT_METADATA
from qrest_agent.core.validator import validate_state


@dataclass(slots=True)
class MetadataExportResult:
    ok: bool
    metadata: dict[str, Any] | None
    report: ValidationReport
    defaulted_fields: list[str] = field(default_factory=list)
    blank_fields: list[str] = field(default_factory=list)
    blocked_fields: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    #: 每个受管字段的处理标注：blocked / defaulted / blank / evidenced
    field_annotations: dict[str, str] = field(default_factory=dict)

    def to_dict(self, include_metadata: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "report": self.report.to_dict(),
            "defaulted_fields": self.defaulted_fields,
            "blank_fields": self.blank_fields,
            "blocked_fields": self.blocked_fields,
            "messages": self.messages,
            "field_annotations": dict(self.field_annotations),
        }
        if include_metadata:
            payload["metadata"] = self.metadata
        return payload


def prepare_metadata_export(state: Any, include_reserved_analysis: bool = True) -> MetadataExportResult:
    report = validate_state(state)
    blocked = list(report.missing_required) + list(report.conflicts) + list(report.evidence_gaps)
    blocked.extend(issue.field_path for issue in report.issues if issue.level == "error" and issue.field_path not in blocked)
    if blocked:
        return MetadataExportResult(
            ok=False,
            metadata=None,
            report=report,
            blocked_fields=blocked,
            field_annotations={path: "blocked" for path in blocked},
            messages=["存在必须字段缺失、冲突或错误字段，未生成 metadata.json。"],
        )

    metadata = state.to_metadata()
    if include_reserved_analysis and "analysis" not in metadata:
        metadata["analysis"] = deepcopy(DEFAULT_METADATA["analysis"])
    if not include_reserved_analysis:
        metadata.pop("analysis", None)
    defaulted: list[str] = []
    blanked: list[str] = []

    for path, policy in field_policies_by_path().items():
        if not is_blank(get_path(metadata, path)):
            continue
        if policy.importance == "important":
            set_path(metadata, path, deepcopy(policy.default))
            defaulted.append(path)
        elif policy.importance == "optional":
            set_path(metadata, path, None)
            blanked.append(path)

    _apply_channel_field_policy(metadata, defaulted, blanked)

    annotations: dict[str, str] = {}
    for path in defaulted:
        annotations[path] = "defaulted"
    for path in blanked:
        annotations[path] = "blank"
    for path, policy in field_policies_by_path().items():
        if path not in annotations and not is_blank(get_path(metadata, path)):
            annotations[path] = "evidenced"

    messages: list[str] = []
    if defaulted:
        messages.append(f"{len(defaulted)} 个重要字段缺失，已写入默认值。")
    if blanked:
        messages.append(f"{len(blanked)} 个非关键字段缺失，已留空。")
    if not messages:
        messages.append("metadata.json 已生成。")
    return MetadataExportResult(
        ok=True,
        metadata=metadata,
        report=report,
        defaulted_fields=defaulted,
        blank_fields=blanked,
        field_annotations=annotations,
        messages=messages,
    )


def _apply_channel_field_policy(metadata: dict[str, Any], defaulted: list[str], blanked: list[str]) -> None:
    channels = get_path(metadata, "InstrumentInfo.Channels")
    if not isinstance(channels, list):
        return

    for index, channel in enumerate(channels):
        if not isinstance(channel, dict):
            continue
        for key in channel_policy_keys():
            if not is_blank(channel.get(key)):
                continue
            path = f"InstrumentInfo.Channels[{index}].{key}"
            importance = channel_key_importance(key)
            if importance == "important":
                channel[key] = channel_key_default(key)
                defaulted.append(path)
            elif importance == "optional":
                channel[key] = None
                blanked.append(path)
