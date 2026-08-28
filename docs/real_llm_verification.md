# 真实 LLM 验证记录（ollama 本地模型）

环境：本机 ollama（HTTP API http://localhost:11434）。可用模型：
`qwen3.8:latest` / `deepseek-r1:14b` / `qwen3:14b` / `deepseek-r1:8b` / `qwen3.5:9b` /
`qwen3:4b-instruct`（provider_config 默认模型）。

E2E 脚本：`scripts/manual_e2e/real_llm_scenarios.py`
（用法：`env PYTHONPATH=src .venv/bin/python scripts/manual_e2e/real_llm_scenarios.py qwen3:4b-instruct [场景...]`）。

## 验证结果（qwen3:4b-instruct）

| 场景 | 结果 | 说明 |
| --- | --- | --- |
| ascii：结构为钢框架 + 中文项目名 | 通过 | StructuralType=钢框架 → **SteelFrame**（canonicalize 生效）；ProjectName=昆明大楼 → **uncertain**（不创造英文名） |
| footprint：矩形 42m × 25.2m | 通过 | Shape=Rectangular；Parameters=LLM 直接提取；**BoundingBox 由 calculate_bounding_box 自动 derived** |
| elevation：14 层/地下 2 层/层高 | 通过 | LLM 输出 **5 条 facts** → Derivation Pass 调 derive_elevation_profile → **Elevation（16 项 derived）+ ElevationNum=16**，回复准确 |
| channels：系统共布置18个传感器 | 通过（修复后） | 修复前：Skill 措辞“ChannelNum 必须等于 Channels 长度”致模型拒绝确认总数；修复后：**ChannelNum=18 extracted**、Channels 保持 missing；同时 **Schema Gate 拦截了模型尝试写入的 Channels="UNKNOWN"**（rejected_candidates 记录 expected array, got string） |
| correction：前面的长度改为46.9m | 通过（修复后） | 修复前：LLM 返回空候选；修复后（提取上下文注入当前已知值 + prompt correction 规则）：**Parameters={Length:46.9, Width:25.2} confirmed**（Width 保留），**BoundingBox 自动重算 23.45/-23.45**（修复 derived→derived 覆盖语义，不再产生 conflict） |
| hallucination：仅“昆明的办公建筑” | 通过 | 不生成 StructuralType/Elevation；回复正确询问缺失项 |
| qrest_ask：用当前项目状态生成 qREST | 通过 | intent=qrest_task；actions=export + 结构化 ask（missing_data_txt，request/expected 正确） |

## 过程中发现并修复的问题

1. **instrument_info Skill 措辞**：`ChannelNum 必须等于 Channels 数组长度` 让模型在只有总数时拒绝
   确认 ChannelNum。按方案 §87-§88 改为：只有总数 → ChannelNum 可直接确认、Channels missing。
2. **correction 提取为空**：模型面对局部修正（“改为46.9m”）不知道要输出完整对象。
   修复：ExtractionContext 增加 `current_values`（correction 轮注入当前已知字段值），
   prompt 明确 correction 输出完整字段（保留未提及子字段）+ status=confirmed。
3. **BoundingBox 修正后变 conflict**：Parameters 修正后重算 BoundingBox 时，_merge 把
   derived→derived 的值替换当冲突。修复：WorkingState 合并规则——旧值 derived 且新值
   derived → 确定性重算直接覆盖（旧 derived 值作废，不构成用户数据冲突）；confirmed 仍受保护。

## 结论

- 中文规范化、facts→Elevation 推导、footprint BoundingBox 推导、Schema Gate 拦截、
  correction 确认链路在真实本地模型上全部工作；
- 单轮 4 次 LLM 调用约 10-45s（qwen3:4b-instruct），可接受；
- 建议后续：qwen3.8 / qwen3.5:9b 更大模型复测（facts 输出与 ask 行为可能更稳定）。
