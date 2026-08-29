# 小模型稳定性测试报告（真实 LLM 多轮验证）

日期：2026-08-29。环境：CPU-only（nvidia-smi 无法连接驱动），本地 ollama 服务。
可用模型：qwen3.8:latest / deepseek-r1:14b / qwen3:14b / deepseek-r1:8b / qwen3.5:9b / qwen3:4b-instruct。

## 结论（TL;DR）

1. **qwen3:4b-instruct（2.5GB，默认模型）在 4 个核心场景 × 3 次重复 = 12/12 结果完全一致**：
   中文规范化、footprint 推导、elevation facts→推导、correction 确认链路全部稳定；
2. 9B+ 模型在本机 **CPU 推理不可行**：qwen3.5:9b 单次简单调用 90s 无响应
   （模型已加载但推理卡死）；建议在 GPU 环境运行 `scripts/manual_e2e/real_llm_scenarios.py <model> all` 复测；
3. 小模型偶发波动已被系统正确拦截：channels 场景曾出现 LLM 把 `Channels="UNKNOWN"` 写入数组字段，
   **Schema Gate 拒绝并记录 rejected_candidates**（expected array, got string）。

## qwen3:4b-instruct 稳定性（3 次 × 4 场景，temperature=0, format=json）

| 场景 | run1 | run2 | run3 |
| --- | --- | --- | --- |
| ascii（钢框架+昆明大楼） | StructuralType=**SteelFrame** extracted；ProjectName=**uncertain** | 同 run1 | 同 run1 |
| footprint（矩形 42×25.2m） | Shape=Rectangular；Parameters=extracted；**BoundingBox=derived**（tool 计算 21/-21/12.6/-12.6） | 同 run1 | 同 run1 |
| elevation（14 层/地下2/层高） | **5 条 facts** + Elevation **derived**（16 项）+ ElevationNum=16 | 同 run1 | 同 run1 |
| correction（改为46.9m） | Parameters={46.9,25.2} **confirmed**（Width 保留）；**BoundingBox 重算 23.45/-23.45** derived | 同 run1 | 同 run1 |

数据：`test_outputs/llm_e2e/qwen3_4b-instruct_stability.json`（12 条 run 记录）。

## 7 场景全流程（qwen3:4b-instruct，首次全量）

| 场景 | 结果 |
| --- | --- |
| ascii_structural_type | ✅ 中文受控值→SteelFrame；中文自由字段→uncertain |
| footprint_derivation | ✅ Parameters extracted + BoundingBox derived（修复后不再出现 inferred 占位） |
| elevation_derivation | ✅ 5 facts → Elevation[16 项] derived + ElevationNum=16 |
| channel_num_only | ✅ ChannelNum=18 extracted；Channels missing（Skill 措辞修复后稳定） |
| correction_confirmed | ✅ Parameters confirmed 46.9 + BoundingBox 自动重算 |
| no_invented_structural_type | ✅ 不生成 StructuralType（LLM 空结果→规则兜底，回复正确询问） |
| qrest_generation_missing_data | ✅ intent=qrest_task；export + 结构化 ask（missing_data_txt） |

## 模型行为波动点（已由系统防线兜住）

- channels 场景早前一次运行：LLM 输出 `InstrumentInfo.Channels="UNKNOWN"`（字符串替代数组）
  → **Schema Gate 拒绝**（rejected_candidates: expected array, got string）；
  后续重复运行未再出现，但防线保证即使出现也不会进入 Working State。
- footprint 场景早前一次运行：LLM 输出 inferred BoundingBox（猜测 21/-21）
  → 修复后确定性 Tool 覆盖 inferred 占位（derived），不再阻塞推导。

## 其他模型（CPU 环境不可行记录）

| 模型 | 大小 | 尝试结果 |
| --- | --- | --- |
| qwen3.5:9b | 6.6GB | 单次简单调用 90s 无响应（HTTP 000）；4 场景任务 14 分钟无进展后终止 |
| qwen3:14b | 9.3GB | 未运行（同量级，预计更慢） |
| deepseek-r1:8b/14b | 5.2/9.0GB | 推理模型，CPU 下预计每调用数分钟，终止 |
| qwen3.8:latest | 17GB | 未运行（最大，CPU 不可行） |

## 交付脚本

- `scripts/manual_e2e/real_llm_scenarios.py`：单模型多场景 E2E（结果写入 test_outputs/llm_e2e/）
- `scripts/manual_e2e/stability_test.py`：同一模型同场景重复 N 次测稳定性
- `scripts/manual_e2e/compare_models.py`：跨模型结果对比表

GPU 环境建议：`real_llm_scenarios.py qwen3.5:9b all`、`stability_test.py qwen3.5:9b 3`。
