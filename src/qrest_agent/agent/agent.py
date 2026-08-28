from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from qrest_agent.agent.extractor import LLMExtractor, RuleBasedExtractor
from qrest_agent.agent.prompts import (
    AGENT_PLANNING_PROMPT,
    AGENT_SYSTEM_PROMPT,
    PLANNING_SCHEMA_HINT,
)
from qrest_agent.agent.task_handlers import TaskHandlerRegistry, create_default_handler_registry
from qrest_agent.agent.task_models import TaskIntent
from qrest_agent.agent.tasks import detect_task_intent, intent_from_arguments, intent_to_arguments
from qrest_agent.agent.tool_registry import ToolRegistry
from qrest_agent.core.exporter import MetadataExportResult, prepare_metadata_export as _prepare_metadata_export
from qrest_agent.core.models import Candidate, ValidationReport
from qrest_agent.core.schema import QREST_TRACKED_PATHS
from qrest_agent.core.validator import validate_state
from qrest_agent.ingestion.sources import SourceChunk, SourceManager
from qrest_agent.llm.clients import BaseLLMClient
from qrest_agent.skills import SkillRegistry
from qrest_agent.state.evidence import Evidence
from qrest_agent.state.working_state import EXPORTABLE_STATUSES, WorkingState

AgentAction = Literal["resolve_conflicts", "ask_missing", "review_warnings", "ready", "task_done"]
PlanAction = Literal["extract", "tool", "ask", "export", "none", "task"]

#: 字段路径前缀 → 专业知识 Skill 名（Phase 6：决策前读取相关 Skill）。
_SKILL_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("BuildingInfo.", "building_info"),
    ("InstrumentInfo.", "instrument_info"),
    ("DataInfo.", "data_info"),
)


@dataclass(slots=True)
class AgentDecision:
    """主 Agent 对当前状态的下一步决策（含 Skill 指导）。"""

    action: AgentAction
    reason: str
    details: list[str] = field(default_factory=list)
    guidance: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "details": list(self.details),
            "guidance": list(self.guidance),
        }


@dataclass(slots=True)
class AgentPlan:
    """主 Agent 的回合计划（Phase 6：LLM 规划，规则兜底）。"""

    action: PlanAction = "extract"
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    skills: list[str] = field(default_factory=list)
    skill_name: str | None = None
    reason: str = ""
    source: str = "rule"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "tool_name": self.tool_name,
            "tool_arguments": self.tool_arguments,
            "skills": list(self.skills),
            "skill_name": self.skill_name,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass(slots=True)
class TurnResult:
    candidates: list[Candidate]
    report: ValidationReport
    response: str
    decision: AgentDecision
    extractor: str = "unknown"
    fallback_reason: str | None = None
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    plan: AgentPlan | None = None
    task_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [item.to_dict() for item in self.candidates],
            "report": self.report.to_dict(),
            "response": self.response,
            "decision": self.decision.to_dict(),
            "extractor": self.extractor,
            "fallback_reason": self.fallback_reason,
            "tool_results": list(self.tool_results),
            "plan": self.plan.to_dict() if self.plan is not None else None,
            "task_result": self.task_result,
        }


class QrestAgent:
    """Phase 1-6 主 Agent：系统的决策主体。

    回合循环（Phase 6）：
    1. 理解：接收消息/文件，可选 LLM 规划（plan）；
    2. 执行：按计划调用 Tool（如 read_document），提取候选事实；
    3. 更新：所有候选先进入 Working State（submit_all）；
    4. 推导：自动调用确定性计算 Tool 补齐可推导字段（derive_counts /
       calculate_frequency），以 derived + 证据落库；
    5. 校验：确定性 Validator 生成报告；
    6. 决策：读取相关专业知识 Skill，输出 AgentDecision
       （继续处理 / 询问用户 / 可导出）。

    程序不预先规定用户的信息输入顺序；每一步都由当前 Working State 驱动。
    """

    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        tool_registry: ToolRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        working_state: WorkingState | None = None,
        session_id: str | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.tools = tool_registry or ToolRegistry()
        self.skills = skill_registry or SkillRegistry()
        self.session_id = session_id
        self._handler_registry: TaskHandlerRegistry | None = None
        self.working_state = working_state or WorkingState.empty()
        self.working_state.tracked_paths = list(QREST_TRACKED_PATHS)
        self.sources = SourceManager()
        self.extractor = LLMExtractor(llm_client) if llm_client is not None else RuleBasedExtractor()
        self._skill_text_cache: dict[str, str] = {}

    @property
    def system_prompt(self) -> str:
        return AGENT_SYSTEM_PROMPT

    @property
    def handlers(self) -> TaskHandlerRegistry:
        """qREST 数据生成/加载 skill handlers（主 Agent 计划执行的确定性工作流）。"""
        if self._handler_registry is None:
            self._handler_registry = create_default_handler_registry(self, self.session_id or "default")
        return self._handler_registry

    # ---- 理解 ----

    def ingest_text(self, text: str, source_id: str = "user_message") -> list[SourceChunk]:
        return self.sources.add_text(text, source_id=source_id)

    def ingest_file(self, path: str | Path) -> list[SourceChunk]:
        return self.sources.add_file(path)

    # ---- 规划与执行（Phase 6） ----

    def plan(self, text: str) -> AgentPlan:
        """生成回合计划：LLM 可用时由模型决策，否则规则兜底为 extract。"""
        if self.llm_client is None:
            return _rule_plan(text)
        try:
            parsed = self.llm_client.complete_json(
                _build_planning_messages(text, self),
                schema_hint=PLANNING_SCHEMA_HINT,
            )
        except Exception:
            return AgentPlan(action="extract", reason="LLM planning failed; rule fallback", source="rule")
        return _plan_from_model(parsed, self.tools)

    def execute_plan(self, plan: AgentPlan) -> dict[str, Any]:
        if plan.action != "tool" or not plan.tool_name:
            return {"action": plan.action, "executed": False}
        try:
            output = self.tools.execute(plan.tool_name, dict(plan.tool_arguments))
        except Exception as exc:
            return {"action": "tool", "tool": plan.tool_name, "ok": False, "error": str(exc)}
        return {"action": "tool", "tool": plan.tool_name, "ok": True, "output": output}

    def context_summary(self) -> dict[str, Any]:
        report = validate_state(self.working_state)
        known: dict[str, dict[str, Any]] = {}
        for path, state in self.working_state.fields.items():
            if state.value is not None and state.status in EXPORTABLE_STATUSES:
                known[path] = {"value": state.value, "status": state.status, "confidence": state.confidence}
        return {
            "known_fields": known,
            "missing_required": report.missing_required,
            "missing_important": report.missing_important,
            "conflicts": report.conflicts,
            "skills": self.skills.list_names(),
            "tools": [spec.name for spec in self.tools.list_specs()],
        }

    # ---- 回合循环 ----

    def run_turn(self, text: str | None = None, files: list[str | Path] | None = None) -> TurnResult:
        chunks: list[SourceChunk] = []
        if text:
            chunks.extend(self.ingest_text(text))
        for path in files or []:
            chunks.extend(self.ingest_file(path))

        plan = self.plan(text or "")
        if plan.action == "task":
            return self._run_task(text or "", plan)
        tool_results: list[dict[str, Any]] = []
        if plan.action == "tool" and plan.tool_name:
            plan_result = self.execute_plan(plan)
            tool_results.append(plan_result)
            if plan_result.get("ok") and plan.tool_name == "read_document":
                for item in (plan_result.get("output") or {}).get("chunks", []):
                    if isinstance(item, dict):
                        chunk = SourceChunk.from_dict(item)
                        if chunk.text.strip():
                            chunks.append(chunk)

        candidates, extractor_name, fallback_reason = self._extract(chunks)
        self.working_state.submit_all(candidates)
        tool_results.extend(self._apply_derivation_tools())

        report = validate_state(self.working_state)
        decision = self.decide(report)
        return TurnResult(
            candidates=candidates,
            report=report,
            response=build_agent_response(report, decision, tool_results=tool_results),
            decision=decision,
            extractor=extractor_name,
            fallback_reason=fallback_reason,
            tool_results=tool_results,
            plan=plan,
        )

    def decide(self, report: ValidationReport) -> AgentDecision:
        if report.conflicts:
            decision = AgentDecision(
                "resolve_conflicts",
                "存在冲突字段，需要用户确认采用哪个值",
                list(report.conflicts),
            )
        elif report.missing_required:
            decision = AgentDecision(
                "ask_missing",
                "必要字段缺失，需要用户补充证据",
                list(report.missing_required),
            )
        elif report.missing_important:
            decision = AgentDecision(
                "review_warnings",
                "重要字段缺失，导出时将使用默认值并明确标注",
                list(report.missing_important),
            )
        else:
            decision = AgentDecision("ready", "工作状态满足校验，可以进入导出或后续算法配置", [])
        decision.guidance = self._skill_guidance(decision)
        return decision

    def _run_task(self, text: str, plan: AgentPlan) -> TurnResult:
        intent = intent_from_arguments(plan.skill_name or "", plan.tool_arguments)
        handler = self.handlers.get(plan.skill_name or "") if intent is not None else None
        if handler is None or intent is None:
            return TurnResult(
                candidates=[],
                report=validate_state(self.working_state),
                response="任务无法执行：skill 或参数无效，请重试。",
                decision=AgentDecision("ready", "invalid task plan", []),
                extractor="task",
                plan=plan,
                fallback_reason="invalid task plan",
            )
        result = handler.handle(text, intent)
        return TurnResult(
            candidates=[],
            report=result.report,
            response=result.response,
            decision=AgentDecision("task_done", f"task {result.command} executed", []),
            extractor="task",
            plan=plan,
            task_result=result.tool_result,
        )

    def can_export(self) -> bool:
        return validate_state(self.working_state).ready

    def prepare_metadata_export(self, include_reserved_analysis: bool = True) -> MetadataExportResult:
        return _prepare_metadata_export(self.working_state, include_reserved_analysis=include_reserved_analysis)

    def export_metadata(self, include_reserved_analysis: bool = True) -> dict[str, Any]:
        result = self.prepare_metadata_export(include_reserved_analysis=include_reserved_analysis)
        if not result.ok or result.metadata is None:
            blocked = ", ".join(result.blocked_fields)
            raise ValueError(f"metadata cannot be exported; blocked=[{blocked}]")
        return result.metadata

    def export_audit(self) -> dict[str, Any]:
        report = validate_state(self.working_state)
        export = self.prepare_metadata_export()
        return {
            "ready": report.ready,
            "validation": report.to_dict(),
            "export": export.to_dict(include_metadata=False),
            "records": self.working_state.to_audit_dict(),
            "tool_specs": [spec.to_dict() for spec in self.tools.list_specs()],
        }

    def export_artifacts(self, metadata_path: str | Path, audit_path: str | Path) -> ValidationReport:
        export = self.prepare_metadata_export()
        report = export.report
        Path(audit_path).write_text(_to_json(self.export_audit()), encoding="utf-8")
        if export.ok and export.metadata is not None:
            Path(metadata_path).write_text(_to_json(export.metadata), encoding="utf-8")
        return report

    def to_metadata(self, require_evidence: bool = True) -> dict[str, Any]:
        return self.working_state.to_metadata(require_evidence=require_evidence)

    def to_audit_dict(self) -> dict[str, Any]:
        return self.working_state.to_audit_dict()

    # ---- 内部 ----

    def _apply_derivation_tools(self) -> list[dict[str, Any]]:
        """回合内的确定性推导微循环：数组长度 → 计数；DT → Frequency（仅报告）。

        推导结果以 derived + tool 证据写入 Working State（方案 §8.3）。
        """
        results: list[dict[str, Any]] = []
        state = self.working_state

        elevation = state.get("BuildingInfo.Elevation")
        if elevation is not None and isinstance(elevation.value, list) and elevation.value:
            current = state.get("BuildingInfo.ElevationNum")
            count = len(elevation.value)
            if current is None or current.value is None or (current.status != "confirmed" and current.value != count):
                output = self.tools.execute("derive_counts", {"elevations": elevation.value})
                derived = output["ElevationNum"]
                state.derive(
                    "BuildingInfo.ElevationNum",
                    derived,
                    derived_from=["BuildingInfo.Elevation"],
                    evidence=[Evidence(source_id="tool:derive_counts", source_type="tool",
                                        text="ElevationNum = len(Elevation)")],
                    confidence=1.0,
                    updated_by="tool",
                )
                results.append({"tool": "derive_counts", "field_path": "BuildingInfo.ElevationNum",
                                "value": derived, "derived_from": ["BuildingInfo.Elevation"]})

        channels = state.get("InstrumentInfo.Channels")
        if channels is not None and isinstance(channels.value, list) and channels.value:
            current = state.get("InstrumentInfo.ChannelNum")
            count = len(channels.value)
            if current is None or current.value is None or (current.status != "confirmed" and current.value != count):
                output = self.tools.execute("derive_counts", {"channels": channels.value})
                derived = output["ChannelNum"]
                state.derive(
                    "InstrumentInfo.ChannelNum",
                    derived,
                    derived_from=["InstrumentInfo.Channels"],
                    evidence=[Evidence(source_id="tool:derive_counts", source_type="tool",
                                        text="ChannelNum = len(Channels)")],
                    confidence=1.0,
                    updated_by="tool",
                )
                results.append({"tool": "derive_counts", "field_path": "InstrumentInfo.ChannelNum",
                                "value": derived, "derived_from": ["InstrumentInfo.Channels"]})

        dt = state.get("DataInfo.DT")
        if dt is not None and isinstance(dt.value, int | float) and dt.value > 0:
            output = self.tools.execute("calculate_frequency", {"dt": dt.value})
            results.append({"tool": "calculate_frequency", "value": output["frequency"], "from": "DataInfo.DT"})

        return results

    def _skill_guidance(self, decision: AgentDecision) -> list[str]:
        """根据决策涉及的字段读取相关专业知识 Skill，返回简短指导。"""
        skills: list[str] = []
        for field_path in decision.details:
            for prefix, skill_name in _SKILL_BY_PREFIX:
                if field_path.startswith(prefix) and skill_name not in skills:
                    skills.append(skill_name)
                    break
        if not skills:
            return []

        guidance: list[str] = []
        for skill_name in skills:
            try:
                text = self._skill_text(skill_name)
            except KeyError:
                continue
            excerpt = _extract_skill_guidance(text)
            if excerpt:
                guidance.append(f"{skill_name}: {excerpt}")
        return guidance[:2]

    def _skill_text(self, skill_name: str) -> str:
        if skill_name not in self._skill_text_cache:
            self._skill_text_cache[skill_name] = self.skills.load(skill_name).instructions
        return self._skill_text_cache[skill_name]

    def _extract(self, chunks: list[SourceChunk]) -> tuple[list[Candidate], str, str | None]:
        using_llm = isinstance(self.extractor, LLMExtractor)
        fallback_reason: str | None = None
        rule_extractor = RuleBasedExtractor()
        if using_llm:
            try:
                llm_candidates = self.extractor.extract(chunks)
            except Exception as exc:
                fallback_reason = f"LLM extraction failed: {exc}"
                llm_candidates = []

            rule_candidates = rule_extractor.extract(chunks)
            if llm_candidates:
                candidates = llm_candidates + rule_candidates
                extractor_name = "llm+rule" if rule_candidates else "llm"
            else:
                fallback_reason = fallback_reason or "LLM extraction returned no candidates"
                candidates = rule_candidates
                extractor_name = "rule"
        else:
            try:
                candidates = rule_extractor.extract(chunks)
            except Exception as exc:
                fallback_reason = f"rule extraction failed: {exc}"
                candidates = []
            extractor_name = "rule"
        return candidates, extractor_name, fallback_reason


def build_agent_response(
    report: ValidationReport,
    decision: AgentDecision,
    tool_results: list[dict[str, Any]] | None = None,
) -> str:
    if decision.action == "resolve_conflicts":
        lines = ["发现字段存在冲突，请确认：" + "，".join(report.conflicts)]
    elif decision.action == "ask_missing":
        lines = ["当前仍缺少必要信息：" + "，".join(report.missing_required)]
    elif decision.action == "review_warnings":
        lines = ["必须字段已满足，但仍缺少重要信息，导出时会使用默认值：" + "，".join(report.missing_important)]
    else:
        lines = []
        if report.missing_optional:
            lines.append("必须字段已满足，部分非关键字段缺失，导出时会留空。")
        else:
            lines.append("元数据已通过校验，可以导出 qREST metadata.json。")

    for item in tool_results or []:
        tool = item.get("tool")
        if tool == "calculate_frequency":
            lines.append(f"工具计算：Frequency = 1 / DT = {item.get('value')} Hz（来源 {item.get('from')}）")
        elif tool == "derive_counts":
            source = ", ".join(item.get("derived_from") or [])
            lines.append(f"工具推导：{item.get('field_path')} = {item.get('value')}（derived_from {source}）")
        elif item.get("ok") and tool == "read_document":
            output = item.get("output") or {}
            lines.append(f"工具读取：{output.get('path')}（{output.get('chunk_count', 0)} 个文本块）")

    for entry in decision.guidance:
        lines.append(f"参考 Skill {entry}")
    return "\n".join(line for line in lines if line)


def _rule_plan(text: str) -> AgentPlan:
    """规则兜底规划：识别 qREST 数据加载/生成任务 → task；否则 extract。"""
    intent = detect_task_intent(text)
    if intent is not None:
        return AgentPlan(
            action="task",
            skill_name=intent.skill_name,
            tool_arguments=intent_to_arguments(intent),
            skills=[intent.skill_name],
            reason=f"detected task intent: {intent.name}",
            source="rule",
        )
    return AgentPlan(action="extract", reason="rule provider default", source="rule")


def _to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _build_planning_messages(text: str, agent: QrestAgent) -> list[dict[str, str]]:
    context = agent.context_summary()
    return [
        {"role": "system", "content": AGENT_PLANNING_PROMPT},
        {
            "role": "user",
            "content": (
                "Current context:\n"
                + json.dumps(context, ensure_ascii=False, default=str)
                + "\n\nUser message:\n"
                + text
                + "\n\nReturn the JSON plan."
            ),
        },
    ]


def _plan_from_model(parsed: dict[str, Any], tools: ToolRegistry) -> AgentPlan:
    action = str(parsed.get("action", "none"))
    if action not in {"extract", "tool", "ask", "export", "none"}:
        action = "none"

    tool_name = parsed.get("tool")
    arguments = parsed.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    skills = [str(item) for item in parsed.get("skills", []) if isinstance(item, str)]

    skill_name: str | None = None
    if action == "tool":
        known = {spec.name for spec in tools.list_specs()}
        if tool_name not in known:
            action = "extract"
            tool_name = None
            arguments = {}
    elif action == "task":
        skill_name = parsed.get("skill") or parsed.get("skill_name")
        if skill_name not in {"qrest_data_generation", "qrest_data_loading"}:
            action = "extract"
            skill_name = None
            arguments = {}

    return AgentPlan(
        action=action,  # type: ignore[arg-type]
        tool_name=tool_name,
        tool_arguments=arguments,
        skills=skills,
        skill_name=skill_name,
        reason=str(parsed.get("reason", "")),
        source="llm",
    )


def _extract_skill_guidance(text: str, max_chars: int = 120) -> str:
    marker = "## 必须询问"
    start = text.find(marker)
    if start == -1:
        return ""
    section = text[start:]
    end = section.find("\n## ", len(marker))
    if end != -1:
        section = section[:end]
    lines: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith(("* ", "1. ", "2. ", "3. ", "4. ", "5. ", "6. ")):
            lines.append(stripped.lstrip("- *").rstrip("；;").strip())
    return "；".join(line for line in lines if line)[:max_chars]
