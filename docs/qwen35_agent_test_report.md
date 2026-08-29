# qwen3.5:9b Agent 测试记录（CPU 环境诊断）

日期：2026-08-29。用户确认 qwen3.5:9b 在终端可用；本次尝试用其完成 agent 全链路测试。

## 结论

- **单步调用可用**：intent 选择 100s、action 规划 67s、LLM 提取 51s 均成功且结果正确
  （`钢框架→SteelFrame` extracted、`昆明大楼` → uncertain）；
- **连续调用不可用**：同一进程内 4 次连续请求时，qwen3.5:9b 约 75% 返回空 JSON
  （实测 call1 FAIL / call2 OK / call3 FAIL / call4 FAIL）；
- agent 回合 = 4 次连续 LLM 调用，全成功概率 ≈ 25%^4 ≈ 0.4%，因此完整场景无法稳定完成；
- respond（自然语言回复）在 CPU 上生成超长 → ollama 返回空（280s+）。

## 根因与修复（已提交到代码）

| 问题 | 修复 |
| --- | --- |
| CPU 默认线程过少导致大模型推理卡死（9B 模型 90s+ 无响应） | OllamaClient 默认 `num_thread=cpu_count()`（实测 8 线程后 3.6s 响应） |
| qwen3.5 是 thinking 模型，思维链在 CPU 上极慢 | 默认 `think=false`（实测 4.9s 响应） |
| ollama 默认 context 4096 < agent prompt（system+schema+skill+source） | 默认 `num_ctx=8192` |
| 自然语言回复生成过长导致超时 | 默认 `num_predict=600` |
| 连续请求偶发返回空/坏 JSON（~75%） | `complete_json` 增加 JSON 解析级重试（默认 retries=1，E2E 用 2） |

这些修复同时让 qwen3:4b-instruct 的调用更稳更快（176 测试全通过）。

## 实测数据（qwen3.5:9b）

| 步骤 | prompt 大小 | 耗时 | 结果 |
| --- | --- | --- | --- |
| 简单 JSON 请求 | ~20 tokens | 3.6-4.9s | OK |
| intent 选择 | 1254 chars | 100.1s | OK（collect_metadata + building_info/metadata） |
| action 规划 | 9159 chars | 66.9s | OK（extract） |
| LLM 提取 | ~8-10K chars | 47.8-50.6s | OK（SteelFrame extracted；昆明大楼 uncertain） |
| responder | 255 chars（精简） | >280s | 失败（空 JSON） |
| 连续 4 次简单调用 | - | ~7s/次 | 1/4 成功 |

## 环境限制

- 本机 CPU-only（nvidia-smi 无法连接驱动）；9B Q4 模型 CPU 推理 ~2-5 tok/s；
- ollama 服务在宿主环境（bwrap 沙箱内 ps 不可见），连续请求偶发空返回疑似 ollama 端
  在 CPU 推理下的资源/超时问题；
- qwen3:4b-instruct（2.5GB）在本环境稳定（12/12 场景重复一致）。

## GPU 环境复测命令

```bash
env PYTHONPATH=src .venv/bin/python scripts/manual_e2e/real_llm_scenarios.py qwen3.5:9b all
env PYTHONPATH=src .venv/bin/python scripts/manual_e2e/stability_test.py qwen3.5:9b 3
```
