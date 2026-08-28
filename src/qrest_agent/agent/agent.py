from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from qrest_agent.agent.extractor import LLMExtractor, RuleBasedExtractor
from qrest_agent.agent.prompts import AGENT_SYSTEM_PROMPT
from qrest_agent.agent.tool_registry import ToolRegistry
from qrest_agent.core.models import Candidate, ValidationReport
from qrest_agent.core.path import get_path
from qrest_agent.core.schema import DEFAULT_METADATA, QREST_TRACKED_PATHS
from qrest_agent.core.validator import validate_state
from qrest_agent.ingestion.sources import SourceChunk, SourceManager
from qrest_agent.llm.clients import BaseLLMClient
from qrest_agent.skills import SkillRegistry
from qrest_agent.state.working_state import WorkingState

AgentAction = Literal["resolve_conflicts", "ask_missing", "review_warnings", "ready"]


@dataclass(slots=True)
class AgentDecision:
    """主 Agent 对当前状态的下一步决策（Phase 1 契约）。"""

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
    extractor: str = "unknown"
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [item.to_dict() for item in self.candidates],
            "report": self.report.to_dict(),
            "response": self.response,
            "decision": self.decision.to_dict(),
            "extractor": self.extractor,
            "fallback_reason": self.fallback_reason,
        }


class QrestAgent:
    """Phase 1 主 Agent：系统的决策主体（正在替换旧 MetadataAgent 管线）。

    职责边界（方案 §4）：
    - 理解用户当前希望完成什么、提供了什么新信息；
    - 决定需要读取哪些 Skill、调用哪些 Tool；
    - 把新事实以候选形式合并进 Working State（绝不直接写最终 Metadata）；
    - 由确定性 Validator 判断 readiness，缺什么就问什么；
    - 冲突请用户确认，禁止凭经验补全。

    当前 run_turn 的“理解→提取→入 State→校验→决策”骨架已经按新架构落地；
    Phase 6 将把决策步骤升级为真正的 Agent Loop（读 Skill / 调 Tool / 提问）。
    """

    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        tool_registry: ToolRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        working_state: WorkingState | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.tools = tool_registry or ToolRegistry()
        self.skills = skill_registry or SkillRegistry()
        self.working_state = working_state or WorkingState(
            base_metadata=deepcopy(DEFAULT_METADATA),
            tracked_paths=QREST_TRACKED_PATHS,
        )
        if working_state is None:
            self.working_state.seed_defaults(
                {path: get_path(DEFAULT_METADATA, path) for path in ("Header", "Version", "Units")}
            )
        self.sources = SourceManager()
        self.extractor = LLMExtractor(llm_client) if llm_client is not None else RuleBasedExtractor()

    @property
    def system_prompt(self) -> str:
        return AGENT_SYSTEM_PROMPT

    # ---- 理解 ----

    def ingest_text(self, text: str, source_id: str = "user_message") -> list[SourceChunk]:
        return self.sources.add_text(text, source_id=source_id)

    def ingest_file(self, path: str | Path) -> list[SourceChunk]:
        return self.sources.add_file(path)

    # ---- 执行 ----

    def run_turn(self, text: str | None = None, files: list[str | Path] | None = None) -> TurnResult:
        chunks: list[SourceChunk] = []
        if text:
            chunks.extend(self.ingest_text(text))
        for path in files or []:
            chunks.extend(self.ingest_file(path))

        candidates, extractor_name, fallback_reason = self._extract(chunks)
        self.working_state.submit_all(candidates)
        report = validate_state(self.working_state)
        decision = self.decide(report)
        return TurnResult(
            candidates=candidates,
            report=report,
            response=build_agent_response(report, decision),
            decision=decision,
            extractor=extractor_name,
            fallback_reason=fallback_reason,
        )

    def decide(self, report: ValidationReport) -> AgentDecision:
        if report.conflicts:
            return AgentDecision(
                "resolve_conflicts",
                "存在冲突字段，需要用户确认采用哪个值",
                list(report.conflicts),
            )
        if report.missing_required:
            return AgentDecision(
                "ask_missing",
                "必要字段缺失，需要用户补充证据",
                list(report.missing_required),
            )
        if report.missing_important:
            return AgentDecision(
                "review_warnings",
                "重要字段缺失，导出时将使用默认值并明确标注",
                list(report.missing_important),
            )
        return AgentDecision("ready", "工作状态满足校验，可以进入导出或后续算法配置", [])

    def can_export(self) -> bool:
        return validate_state(self.working_state).ready

    def to_metadata(self, require_evidence: bool = True) -> dict[str, Any]:
        return self.working_state.to_metadata(require_evidence=require_evidence)

    def to_audit_dict(self) -> dict[str, Any]:
        return self.working_state.to_audit_dict()

    # ---- 内部 ----

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


def build_agent_response(report: ValidationReport, decision: AgentDecision) -> str:
    if decision.action == "resolve_conflicts":
        return "发现字段存在冲突，请确认：" + "，".join(report.conflicts)
    if decision.action == "ask_missing":
        return "当前仍缺少必要信息：" + "，".join(report.missing_required)
    if decision.action == "review_warnings":
        return "必须字段已满足，但仍缺少重要信息，导出时会使用默认值：" + "，".join(report.missing_important)
    if report.missing_optional:
        return "必须字段已满足，部分非关键字段缺失，导出时会留空。"
    return "元数据已通过校验，可以导出 qREST metadata.json。"
