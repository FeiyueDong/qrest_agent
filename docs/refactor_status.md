# qREST Agent 重构进度

跟踪 [qrest-agent 架构重构方案.md](./qrest-agent%20架构重构方案.md) 的落地状态。

- [x] **Phase 1：重新定义 Agent**
  - 新增 `qrest_agent.agent.agent.QrestAgent`：系统唯一的决策主体，拥有
    Working State、Skill Registry、Tool Registry；
  - 新增主系统提示 `AGENT_SYSTEM_PROMPT`（决策权威 + 反幻觉硬规则）；
  - `run_turn` 按“理解 → 提取 → 入 Working State → Validator → 决策”运行，
    决策结果 `AgentDecision`（ask_missing / resolve_conflicts / review_warnings / ready）。
- [x] **Phase 2：建立 Working State**
  - 新增 `qrest_agent.state.evidence.Evidence`（source_id/location/text/source_type）；
  - 新增 `qrest_agent.state.working_state`：
    `FieldState`（value/status/evidence/alternatives/derived_from/revision/updated_by）、
    `WorkingState`（set/update/submit/confirm/derive/mark_missing/resolve_conflict/missing/evidence_gaps/to_metadata）；
  - 状态语义：confirmed / extracted / derived 可进入最终数据（需证据）；
    uncertain / inferred 默认禁止；missing 必须询问；
  - 所有提取结果先进入 Working State；最终 Metadata 只由 `to_metadata()` 生成。
- [ ] **Phase 3：拆分现有代码**（extractor 专业正则 → Skill/Tool；删除固定流程）
- [ ] **Phase 4：Skill 系统**（metadata/building_info/instrument_info/data_info/sensor_layout）
- [ ] **Phase 5：Tool 系统**（document reader / table reader / calculator / validator / writer）
- [ ] **Phase 6：Agent Loop**（读 Skill / 调 Tool / 提问的自主循环）
- [ ] **Phase 7：验证机制**（evidence validation / conflict validation 全面接入导出策略）

## 过渡说明

- `core.models.MetadataState` / `agent.metadata_agent.MetadataAgent` 目前是
  Phase 1-2 的过渡门面，委托给 `WorkingState` / `QrestAgent`；
  随着 Phase 3 拆分将逐步删除。
- 导出策略维持三档（必须阻断 / 重要填默认值并标注 defaulted_fields / 不重要留空），
  但缺失与默认值在报告中的标注将随 Phase 7 进一步明确。
