# Metadata Schema Hardening — 进度记录

依据：`docs/qrest-agent Metadata Schema Hardening 开发方案.md`。
状态：五层防线已实现（Phase 1-6 + 8 完成；Phase 7 LLM Schema Retry 按方案 §79 留待后续），
全量测试 159 passed（含新增 Schema Contract 专项 19 项）。

## 问题根因

`InstrumentInfo.Channels = 18` 可进入 Working State：无 Candidate 类型门、
WorkingState 写入不检查、Validator 对 `channels 非 list` 直接 `return` 跳过、
Exporter 无最终闸门。Schema 存在（FieldSpec + metadata_schema.json）但未成为全链路强制约束。

## 统一 Schema Contract

- 权威来源：`resources/qrest_data/schema/metadata_schema.json`（§7）。
- 新增 `src/qrest_agent/core/schema_gate.py`（§67/§68）：
  - `FieldValidationResult`（valid/field_path/expected/actual/errors）
  - `SchemaViolation` 异常（§23）
  - `validate_shape`（形状门：最外层类型 + 数组元素基本类型，§13/§17-§18）
  - `validate_full`（完整结构：nested required/prefixItems/minItems，§26/§54 供测试与诊断）
  - `schema_context_text`（§9-§10/§76：字段类型/结构 + Num vs Array 区分说明）
- 分层原则（§54/§19）：类型与形状 → Schema 层；nested mandatory key / 工程一致性 →
  Validator Domain 层（按字段政策报告，避免与导出默认值策略冲突）。

## 五层防线

1. **Extraction Schema Context**（§9-§10）：EXTRACTION_SYSTEM_PROMPT 注入完整
   Field schema（类型/嵌套结构）+ ChannelNum vs Channels、ElevationNum vs Elevation
   明确区分与反例（软约束）。
2. **Candidate / WorkingState Shape Gate**（§12-§25）：`WorkingState.set/update/
   submit/confirm/derive` 全部在写入前调用 `validate_shape`，非法值 raise
   `SchemaViolation`；confirmed（§24/§62）与 derived（§25/§61）均不能绕过。
3. **Agent 层**（§48）：`_execute_actions` 逐候选 shape 校验 + 捕获 SchemaViolation，
   拒绝项进入 `TurnResult.rejected_candidates`（field_path/value/reason/expected/actual）。
4. **Validator Generic Schema 层**（§26-§31/§66）：`_validate_schema` 对所有
   required 字段做形状校验（error）；修复 `_validate_instrument` 中
   `channels 非 list → return` 的静默跳过；`validate_metadata` 改为安全导入
   （非法值跳过导入并作为 schema_error 报告，来源 JSON 不再默认可信，§60）。
5. **Export Final Gate**（§32-§34/§63）：`prepare_metadata_export` 在写最终
   metadata 前再次对全部 required 字段做形状校验，非法 → blocked。

## 错误分类（§65）

- `Channels=18` → schema_error（expected array, got integer）
- `ChannelNum=18` 但 Channels 长度 17 → consistency_error（Domain 层）
- Evidence 缺失/伪造 → evidence_error（已有机制）

## 其它

- Skills：`instrument_info`（§44）与 `building_info`（§45）补充“结构严格区分”
  硬约束（Num vs Array、数量不能代替数组、禁止反向生成空 Channels）。
- UI（§46）：对话消息中显示 “Schema 拒绝 N 项（未写入项目状态）” 诊断，
  不进入 Project State / accepted_facts。
- CLI `/confirm`：结构非法值返回“结构校验拒绝”而非写入。

## 测试（§50-§63 全部覆盖，19 项）

tests/test_schema_hardening.py：
- §50 全 FieldSpec 类型反向测试（string←integer 等全部拒绝）
- §51 Channels=18 永久回归：Candidate rejected / state unchanged / validator not ready / export blocked
- §52 ChannelNum=18 合法且不自动生成 Channels
- §53 Channels=[1,2,3] 拒绝；§54 缺 mandatory key 由 Validator 报告
- §55 LocationXYZ 长度/类型；§56 Elevation=16；§57 Parameters=46.9；
  §58 BoundingBox="46x30"；§59 DT=[0.02]/NPTS="many"
- §60 import metadata.json 非法结构 → schema error；§61 derive/update 拒绝；
  §62 confirm 拒绝（含 CLI /confirm）；§63 Export Final Gate
- agent 全链路：LLM 输出 Channels=18（confidence 0.99）→ rejected_candidates +
  状态不变；LLM 输出 ChannelNum=18 → 正常接受

## 待后续（非本轮必需）

- Phase 7：LLM Schema Retry（§36-§39/§79）——被拒候选可回喂模型做一次结构化纠正，
  重试输出仍须过 Schema Gate，最多 1-2 次。
