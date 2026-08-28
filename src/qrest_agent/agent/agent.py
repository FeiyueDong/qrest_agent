from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from qrest_agent.agent.extractor import LLMExtractor, RuleBasedExtractor
from qrest_agent.agent.planner import ActionSpec, AgentPlanner, TurnPlan
from qrest_agent.agent.prompts import AGENT_SYSTEM_PROMPT
from qrest_agent.agent.responder import Responder
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

AgentAction = Literal["resolve_conflicts", "ask_missing", "review_warnings", "ready"]


@dataclass(slots=True)
class AgentDecision:
    """确定性决策摘要（审计用）；正式回复由 Responder 生成。"""

    action: AgentAction
    reason: str
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "reason": self.reason, "details": list(self.details)}


@dataclass(slots=True)
class TurnResult:
    candidates: list[Candidate]
    report: ValidationReport
    response: str
    decision: AgentDecision
    plan: TurnPlan | None = None
    extractor: str = "unknown"
    fallback_reason: str | None = None
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    action_results: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [item.to_dict() for item in self.candidates],
            "report": self.report.to_dict(),
            "response": self.response,
            "decision": self.decision.to_dict(),
            "plan": self.plan.to_dict() if self.plan is not None else None,
            "extractor": self.extractor,
            "fallback_reason": self.fallback_reason,
            "tool_results": list(self.tool_results),
            "action_results": dict(self.action_results),
        }


class QrestAgent:
    """主 Agent（设计文档 §6/§22）：LLM 决策 → 确定性执行 → LLM 回复。

    回合循环（run_turn）：
      1. ingest input
      2. build context
      3. LLM intent + skill selection（无 LLM 时规则兜底）
      4. load selected Skills（完整 SKILL.md 注入决策上下文）
      5. LLM action planning
      6. execute actions（extract / tool / ask / respond / export）
      7. deterministic derivations
      8. validate Working State
      9. determine trusted turn context
     10. LLM response（Responder，只读）
     11. persist session（recent turns）

    Python 只负责安全边界与确定性执行，不模拟智能行为。
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
        self.working_state = working_state or WorkingState.empty()
        self.working_state.tracked_paths = list(QREST_TRACKED_PATHS)
        self.sources = SourceManager()
        self.extractor = LLMExtractor(llm_client) if llm_client is not None else RuleBasedExtractor()
        self.planner = AgentPlanner(skill_registry=self.skills, tool_registry=self.tools)
        self.responder = Responder(llm_client)
        # 对话记忆（设计文档 §17）：结构化摘要，工程事实以 Working State 为准
        self._conversation: list[dict[str, Any]] = []

    @property
    def system_prompt(self) -> str:
        return AGENT_SYSTEM_PROMPT

    # ---- 理解 ----

    def ingest_text(self, text: str, source_id: str = "user_message") -> list[SourceChunk]:
        return self.sources.add_text(text, source_id=source_id)

    def ingest_file(self, path: str | Path) -> list[SourceChunk]:
        return self.sources.add_file(path)

    # ---- 上下文 ----

    def build_turn_context(self, text: str, chunks: list[SourceChunk]) -> dict[str, Any]:
        report = validate_state(self.working_state)
        known: dict[str, dict[str, Any]] = {}
        for path, state in self.working_state.fields.items():
            if state.value is not None and state.status in EXPORTABLE_STATUSES:
                known[path] = {"value": state.value, "status": state.status, "confidence": state.confidence}
        return {
            "user_message": text,
            "session_id": self.session_id,
            "known_fields": known,
            "missing_required": report.missing_required,
            "missing_important": report.missing_important,
            "conflicts": report.conflicts,
            "recent_turns": list(self._conversation),
            "tool_names": [spec.name for spec in self.tools.list_specs()],
            "tool_schemas": [spec.to_dict() for spec in self.tools.list_specs()],
            "skill_names": self.skills.list_names(),
        }

    def build_trusted_context(
        self,
        text: str,
        candidates: list[Candidate],
        report: ValidationReport,
        action_results: dict[str, Any],
        derivation_results: list[dict[str, Any]],
        plan: TurnPlan,
    ) -> dict[str, Any]:
        new_facts = [
            f"{candidate.field_path} = {candidate.value}（{candidate.status}）"
            for candidate in candidates
            if candidate.value is not None
        ]
        return {
            "user_message": text,
            "intent": plan.intent,
            "plan_reason": plan.reason,
            "new_facts": new_facts,
            "missing_required": report.missing_required,
            "missing_important": report.missing_important,
            "conflicts": report.conflicts,
            "known_fields": {
                path: {"value": state.value, "status": state.status}
                for path, state in self.working_state.fields.items()
                if state.value is not None
            },
            "action_results": action_results,
            "derivation_results": derivation_results,
            "report_ready": report.ready,
        }

    # ---- 回合循环 ----

    def run_turn(self, text: str | None = None, files: list[str | Path] | None = None) -> TurnResult:
        # 1. ingest
        chunks: list[SourceChunk] = []
        if text:
            chunks.extend(self.ingest_text(text))
        for path in files or []:
            chunks.extend(self.ingest_file(path))

        # 2-5. context + plan（intent/skills/actions）
        context = self.build_turn_context(text or "", chunks)
        plan = self.planner.plan(text or "", context, self.llm_client)

        # 6. execute actions
        candidates, action_results, extractor_name, fallback_reason = self._execute_actions(plan, chunks, text or "")

        # 7. deterministic derivations
        derivation_results = self._apply_derivation_tools()

        # 8. validate
        report = validate_state(self.working_state)

        # 9-10. trusted context + LLM response
        trusted = self.build_trusted_context(text or "", candidates, report, action_results, derivation_results, plan)
        response = self.responder.respond(trusted)

        # 11. persist conversation memory（摘要形式：意图 + 新事实 + 回复截断）
        self._conversation.append(
            {
                "user": (text or "")[:200],
                "intent": plan.intent,
                "new_facts": [fact for fact in trusted.get("new_facts", [])][:5],
                "response": response[:200],
            }
        )
        self._conversation = self._conversation[-8:]

        decision = self.decide(report)
        tool_results = list(derivation_results)
        for name, payload in action_results.items():
            if name.startswith("tool:"):
                tool_results.append({"tool": name.removeprefix("tool:"), "output": payload})
        return TurnResult(
            candidates=candidates,
            report=report,
            response=response,
            decision=decision,
            plan=plan,
            extractor=extractor_name,
            fallback_reason=fallback_reason,
            tool_results=tool_results,
            action_results=action_results,
        )

    # ---- actions 执行器 ----

    def _execute_actions(
        self,
        plan: TurnPlan,
        chunks: list[SourceChunk],
        text: str,
    ) -> tuple[list[Candidate], dict[str, Any], str, str | None]:
        pending = list(chunks)
        candidates: list[Candidate] = []
        action_results: dict[str, Any] = {}
        extractor_name = "unknown"
        fallback_reason: str | None = None

        for action in plan.actions:
            if action.type == "extract":
                files = [
                    self._resolve_placeholder(value, action_results)
                    for value in action.arguments.get("files") or []
                ]
                for file_path in files:
                    if isinstance(file_path, str) and file_path:
                        try:
                            pending.extend(self.ingest_file(file_path))
                        except Exception as exc:
                            action_results.setdefault("extract_errors", []).append(str(exc))
                if not pending:
                    continue
                turn_candidates, extractor_name, fallback_reason = self._extract(pending)
                candidates.extend(turn_candidates)
                # 所有提取结果先进入 Working State（设计文档 §3.5：唯一事实中心）
                self.working_state.submit_all(turn_candidates)
                pending = []
            elif action.type == "tool":
                tool_name = action.tool
                if tool_name is None:
                    continue
                arguments = self._resolve_placeholders(action.arguments, action_results)
                try:
                    result = self.tools.execute(tool_name, arguments)
                    payload = result.to_dict() if hasattr(result, "to_dict") else result
                except Exception as exc:
                    payload = {"ok": False, "error": str(exc)}
                action_results[f"tool:{tool_name}"] = payload
                if tool_name == "read_document" and isinstance(payload, dict) and payload.get("chunks"):
                    for item in payload["chunks"]:
                        if isinstance(item, dict):
                            chunk = SourceChunk.from_dict(item)
                            if chunk.text.strip():
                                pending.append(chunk)
            elif action.type == "export":
                export = self.prepare_metadata_export()
                payload = export.to_dict(include_metadata=True)
                session_dir = self.session_id or "default"
                self.tools.artifacts.write_json(
                    session_dir, "metadata_export_report.json", export.to_dict(include_metadata=False)
                )
                if export.ok and export.metadata is not None:
                    path = self.tools.artifacts.write_json(session_dir, "metadata.json", export.metadata)
                    payload["metadata_json"] = str(path)
                action_results["export"] = payload
            elif action.type in {"ask", "respond"}:
                break
        return candidates, action_results, extractor_name, fallback_reason

    def _resolve_placeholders(self, value: Any, action_results: dict[str, Any]) -> Any:
        if isinstance(value, str):
            return self._resolve_placeholder(value, action_results)
        if isinstance(value, dict):
            return {key: self._resolve_placeholders(item, action_results) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve_placeholders(item, action_results) for item in value]
        return value

    def _resolve_placeholder(self, value: str, action_results: dict[str, Any]) -> Any:
        """$export.key / $tool:<name>.key / $tool:<name>.outputs.key 占位符解析。"""
        if not value.startswith("$"):
            return value
        parts = value[1:].split(".", 1)
        if len(parts) != 2:
            return value
        namespace, key = parts
        source = action_results.get(namespace)
        if source is None or not isinstance(source, dict):
            return value
        if key in source:
            return source[key]
        if "outputs" in source and isinstance(source["outputs"], dict) and key in source["outputs"]:
            return source["outputs"][key]
        return value

    def decide(self, report: ValidationReport) -> AgentDecision:
        if report.conflicts:
            return AgentDecision("resolve_conflicts", "存在冲突字段，需要用户确认", list(report.conflicts))
        if report.missing_required:
            return AgentDecision("ask_missing", "必要字段缺失，需要用户补充证据", list(report.missing_required))
        if report.missing_important:
            return AgentDecision("review_warnings", "重要字段缺失，导出时将使用默认值", list(report.missing_important))
        return AgentDecision("ready", "工作状态满足校验", [])

    # ---- 导出 ----

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
        """回合内确定性推导（设计文档 §12.3/§11.3）：derived + tool 证据落库。"""
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
                    evidence=[Evidence(
                        source_id="tool:derive_counts",
                        source_type="tool",
                        tool="derive_counts",
                        derived_from=["BuildingInfo.Elevation"],
                        text="ElevationNum = len(Elevation)",
                    )],
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
                    evidence=[Evidence(
                        source_id="tool:derive_counts",
                        source_type="tool",
                        tool="derive_counts",
                        derived_from=["InstrumentInfo.Channels"],
                        text="ChannelNum = len(Channels)",
                    )],
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

    def _extract(self, chunks: list[SourceChunk]) -> tuple[list[Candidate], str, str | None]:
        """正式路径 LLM-only；LLM 失败/无结果时规则兜底（设计文档 §9）。"""
        if isinstance(self.extractor, LLMExtractor):
            fallback_reason: str | None = None
            try:
                llm_candidates = self.extractor.extract(chunks)
            except Exception as exc:
                fallback_reason = f"LLM extraction failed: {exc}"
                llm_candidates = []
            if llm_candidates:
                return llm_candidates, "llm", None
            fallback_reason = fallback_reason or "LLM extraction returned no candidates"
            try:
                return RuleBasedExtractor().extract(chunks), "rule", fallback_reason
            except Exception as exc:
                return [], "rule", f"{fallback_reason}; rule fallback failed: {exc}"
        try:
            return RuleBasedExtractor().extract(chunks), "rule", None
        except Exception as exc:
            return [], "rule", f"rule extraction failed: {exc}"


def _to_json(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)
