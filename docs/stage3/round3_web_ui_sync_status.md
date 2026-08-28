# Round 3 收口与 Web UI 同步改造 — 进度记录

依据：`docs/qrest-agent 核心收口与 Web UI 同步改造方案.md`（§1-§67）。
状态：Phase 1-5 已完成，全量测试 140 passed；Phase 6（真实 LLM E2E）需在部署环境执行。

## Phase 1：Agent 语义链（P0）

- **Skill → Extraction**（§5-§10）：新增 `ExtractionContext(intent, selected_skills, skill_instructions, user_message)`，
  `LLMExtractor.extract(chunks, context=...)` 把本轮 intent + 选中 Skill 完整指令注入提取 prompt
  （`build_extraction_user_prompt(text, context)`），只注入 `plan.skills` 中的 Skill（§10）。
- **correction → confirmed**（§8）：`_apply_correction_promotion` —— intent=correction 且来源为
  用户消息（chat）且候选通过证据校验（仍是 extracted 且有非空值）→ 提升为 confirmed。
- **Trusted Context 严格分类**（§11-§15）：`build_trusted_context` 输出
  `accepted_facts`（仅 Working State 合并后的 confirmed/extracted/derived）、`uncertain`、`inferred`、
  `conflicts`、`missing_required/important`、`requested_inputs`、`tool_results`（含失败，§29）、
  `recent_conversation`、`report_ready`。不再把 uncertain/inferred 混入 known_fields。
- **ask Action 结构化**（§20-§24）：ask 执行时记录 `action_results["ask"] = {reason, request, expected}`
  并终止后续动作；`requested_inputs` 进入 Trusted Context；规则兜底的 qREST 生成缺 data.txt 也生成
  结构化 ask（reason=missing_data_txt, expected=path_or_attachment）。
- **Responder 事实规则**（§14/§25-§26）：prompt 明确 accepted/uncertain/inferred/conflict/missing 的
  表达边界；recent_conversation 只用于理解指代，对话历史不是工程事实来源；模板 fallback 优先使用
  requested_inputs 并提示 uncertain/inferred。

## Phase 2：输入与记忆上下文（P1）

- **input_sources**（§16-§18）：`InputSourceSummary(source_id, source_type, name, chunk_count, preview)`，
  `build_turn_context` 按 source_id 聚合 chunk（preview ≤400 字符）；`_compact_state` 让 Skill Selection
  与 Action Planning 两个阶段都能看到本轮上传的资料。
- **Responder 历史**（§25/§27）：`recent_conversation` 进入 Trusted Context；memory 条目改为
  user / intent / accepted_facts / assistant_summary（保留 new_facts 兼容）。

## Phase 3：API（P1/P2）

- **统一 Turn**（§45-§48/§63）：`POST /api/turn` = message + attachments；`POST /api/upload` 只保存
  文件并登记 pending attachment（attachment_id），不再立即触发 Agent；`/api/chat` 保留为兼容别名。
- **Turn 输出**（§41/§54）：DialogueResult 增加 `plan / turn {intent, skills, actions, tools} / extractor /
  fallback_reason`；Session 输出 `attachments`（pending/used）与 `last_turn`。
- **删除旧概念**（§42-§44）：`skill_handlers`、`task_logs` 已从 dialogue.py 与 Web 层全部移除。

## Phase 4-5：Web UI 数据模型更新 + 静态文件拆分

- `src/qrest_agent/web/static/`：index.html / app.js / style.css（方案 §49-§53 保持 Vanilla JS）。
- Project State：已确认（confirmed/extracted/derived）/ 待确认（uncertain/inferred）/ 缺失 / 冲突 四分类。
- Fields：状态标签、Evidence（来源/位置/引文）、derived（Derived from + Tool）、inferred（不会进入正式
  metadata）提示。
- This Turn：intent / skills / actions / tools（§39，不展示思维链）。
- Artifacts 替代 Task Logs（§43-§44）；Attachments 先选择后随消息发送（§45-§46）；Export 按钮保留
  Ready/Not Ready 标识，点击查看阻断原因（§56）。

## 测试

- 全量：140 passed（原 133 + 新增/更新 7）。
- 新增 `tests/test_round3_semantics.py`：§61 Test A（Skill 注入 Extraction）、Test B（correction context）、
  Test C（Trusted Context 过滤）、Test D（file-only planning 见 input_sources）、Test E（ask→requested_inputs）、
  Test F（Responder 收到 recent_conversation）。
- `tests/test_web_server.py` 重写：静态资源路由、新状态分类（§62）、upload→pending→turn→used 组合（§63）。
- `tests/test_api_service.py` 更新：upload 不再自动触发；二进制 docx 上传 + turn 组合。

## Phase 6：真实 LLM E2E（待部署环境执行）

按 §60 场景 1-8 逐项验证；本环境无 ollama。预期关注点：Skill 选择质量、correction 确认链路、
evidence 幻觉、uncertain 表达、缺 data.txt 自然询问、qREST 完整生成。
