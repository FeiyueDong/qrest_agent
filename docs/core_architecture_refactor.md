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

## 后续可选

- ToolSpec 增加真正的参数 Schema（§21，当前仍为文字描述）；
- 对话历史升级为 summary + recent turns（§17，当前仅保存最近 8 轮）；
- System Prompt 进一步精简（§20）。
