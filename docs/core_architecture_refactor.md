# 核心架构重构进度（qrest-agent 核心架构重构设计.md）

跟踪 [qrest-agent 核心架构重构设计.md](./qrest-agent%20核心架构重构设计.md) 的落地状态。

- [x] **Phase A：清理核心**
  - 删除 ActionInterpreter / TaskHandlerRegistry / QrestDataGenerationHandler /
    QrestDataLoadingHandler / task_models 中间层；主 Agent + WorkingState +
    SkillRegistry + ToolRegistry + Validator + LLMClient 成为唯一核心。
- [x] **Phase B：Skill 真正接入 Agent**
  - SKILL.md 支持 frontmatter（name/description）；SkillRegistry.summaries() 供
    LLM 动态选择；规划两步走：先按摘要选 intent+skills，程序加载完整 SKILL.md
    注入规划上下文（§7/§26 Test 1、Test 2 验证 Skill 内容影响行为）。
- [x] **Phase C：统一 Planning**
  - `agent/planner.py`：TurnPlan（intent/skills/actions/need_user_input/reason）；
    actions 仅 extract/tool/ask/respond/export；正则任务识别仅作 rule fallback。
- [x] **Phase D：重写 Extraction**
  - 正式路径 LLM-only（证据校验后合并）；RuleBasedExtractor 仅 fallback/offline；
    删除 `_extract_kunming_document_patterns` 与假设型通道/标高文本推导。
- [x] **Phase E：强化 Evidence**
  - 删除自动补 evidence；value 非空且 extracted/confirmed 无证据 → 拒绝；
    evidence.text 归一化后无法在来源 chunk 中找到 → 降 uncertain；
    Evidence 增加 tool/derived_from（derived evidence 明确标识）。
- [x] **Phase F：LLM Response**
  - `agent/responder.py`：只读 Responder（LLM 自然回复）；无 LLM/失败时模板
    fallback（含 tool/export 结果摘要）。
- [x] **Phase G：删除旧 workflow（核心）**
  - qREST 加载/生成任务 = qrest_data Skill + export/preflight/generate/load Tool
    actions，不再有专门 workflow class；固定回复模板降级为 fallback。
- [x] **§26 验收测试**：`tests/test_agent_architecture.py` 覆盖 11 项（Skill 动态
  选择 / Skill 改变行为 / 无正则提取 / 无证据拒绝 / 伪造证据降级 / 缺信息不生成 /
  真 derived / 假设不 derived / 自然回复 / 用户修正 / qREST 生成）。

## 后续补充（§17/§20/§21）

- [x] **§21 Tool 参数 Schema**：ToolSpec.arguments 为机器可读 Schema
  （type/required/minimum/description）；ToolRegistry.execute 先校验参数
  （缺失/类型/范围），错误结构化返回；path 类型接受 PathLike；LLM 规划
  上下文携带 tool_schemas。
- [x] **§17 对话历史**：QrestAgent 维护结构化对话记忆（user/intent/new_facts/
  response 摘要，最近 8 轮），注入每轮规划上下文；工程事实始终以 Working State 为准。
- [x] **§20 System Prompt**：无字段知识（已在 Skill），仅保留角色/能力/边界/状态语义。
- 真实 LLM 端到端演练：本开发环境无 ollama，使用 ScriptedClient 完成了
  §28 交互模式的 mock 验证（资料 → 选择 building_info+instrument_info →
  证据化提取 → 缺 NorthAngle 自然询问）；真实模型演练请在部署环境执行
  `qrest_agent.cli chat`（默认 ollama-cli + qwen3:4b-instruct）。
