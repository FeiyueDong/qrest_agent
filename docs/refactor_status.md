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
- [x] **Phase 3：拆分现有代码**
  - 确定性推导逻辑从 `agent/extractor.py` 拆出到 `tools/metadata_calculator.py`
    （Elevation 序列、通道布置、包围盒、Frequency、Azimuth 归一化、计数推导），
    提取器只保留文本参数提取与规则兜底；
  - 删除提取器内的重复推导实现与无用导入；
  - 固定询问顺序/任务路由的进一步简化推迟到 Phase 6（由 Agent Loop 接管）。
- [x] **Phase 4：Skill 系统（核心部分）**
  - 新增专业知识 Skill：`metadata` / `building_info` / `instrument_info` / `data_info`
    （字段含义、允许的确定性推导、必须询问项、冲突处理、禁止行为）；
  - 待建：`sensor_layout`（测点布置判断）与更多专项 Skill。
- [x] **Phase 5：Tool 系统（核心部分）**
  - 注册确定性工具：`read_document` / `calculate_frequency` / `calculate_bounding_box` /
    `normalize_azimuth` / `derive_elevation_profile` / `derive_channel_layout` /
    `derive_counts` / `validate_metadata`；
  - 待建：`table_reader`（通道表读取）、单位归一化工具与 metadata writer。
- [x] **Phase 6：Agent Loop（核心循环）**
  - `QrestAgent.run_turn` 落地自主循环：理解 → LLM 规划（`plan`，规则兜底）
    → 执行 Tool（`execute_plan`，如 read_document 读取后直接进入提取）
    → 候选入 Working State → 自动确定性推导（derive_counts / calculate_frequency，
    derived + tool 证据落库）→ Validator → 读取相关专业知识 Skill 形成决策指导
    → 应答（含工具计算结果与 Skill 参考）；
  - 对话层同步展示工具结果与 Skill 指导；
  - 待办：`ChatSession` 的任务路由（TaskCoordinator）随 facade 移除时并入主 Agent。
- [x] **Phase 7：验证机制**
  - Schema / required / consistency 校验保留并强化（冲突 issue 记录备选值数量）；
  - 新增 **Evidence validation**：状态合格但无证据的关键字段记为 error，
    进入 `report.evidence_gaps` 并阻断导出；
  - **Conflict validation**：不同来源矛盾时 status=conflict + error issue，
    必须由用户确认后才能导出；
  - 导出报告新增 `field_annotations`：blocked / defaulted / blank / evidenced，
    明确区分“缺失”与“默认值”，三档导出策略标注更清晰；
  - 方案 §14 的 7 项验收测试已落地为 `tests/test_acceptance.py`。

## 收尾状态（facade 移除完成）

- `MetadataState` / `MetadataAgent` / `TaskCoordinator` 已删除；
  全系统只存在 `QrestAgent` + `WorkingState` 一套主体：
  - 自然语言任务由 `QrestAgent.plan()` 决策（LLM 规划，规则兜底识别
    加载/生成意图 → 调 skill handler）；
  - CLI / API / Web / 对话层全部直接使用 QrestAgent；
  - validator / exporter 统一接收 WorkingState。
- 导出策略维持三档（必须阻断 / 重要填默认值并标注 defaulted_fields / 不重要留空），
  并带 `field_annotations`（blocked / defaulted / blank / evidenced）明确标注。
