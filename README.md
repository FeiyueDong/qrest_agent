# qREST Agent

面向 qREST（建筑结构轻量化地震监测）工程元数据收集的 **Agent 驱动** AI 助手：
用户用自然语言描述工程信息、上传资料（Word/PDF/Excel/JSON/…），Agent 负责理解与决策，
Python 侧以确定性代码保证数据结构、证据与一致性。

核心原则：

- **LLM 负责理解、选择和表达**；Skill 提供专业知识；Tool 做确定性计算；
- **Working State 是唯一事实中心**：每条事实保存为
  `value + status（missing/extracted/uncertain/derived/inferred/confirmed/conflict）+ evidence`，
  uncertain/inferred 永不进入最终 Metadata；
- **Schema Gate / Validator / Exporter 保证数据契约**：结构非法值（如 `Channels=18`）在进入
  状态前即被拒绝；最终导出的 metadata.json 中所有字符串必须为规范 ASCII 值
  （受控字段自动完成中文→英文映射，如 `钢框架→SteelFrame`）；
- **Intermediate Facts + Derivation Pass**：Agent 可保存有证据的中间事实
  （如 `Building.above_ground_floors`），由确定性 Tool 自动推导
  `StructuralFootprint`、`Elevation`、`ElevationNum` 等复杂字段。

架构与各轮演进文档见 [docs/](docs/)（历史方案归档在 `docs/stage1-4/`）。

---

## 1. 环境准备

```bash
# Python 虚拟环境（仓库内已提供 .venv）
.venv/bin/python --version

# 本地模型（可选，用于 LLM 模式）：需要 ollama 服务运行
ollama list          # 查看已安装模型
ollama serve         # 如服务未启动（系统服务已托管则无需）
```

本机可用模型示例（以 `ollama list` 输出为准）：

| 模型 | 说明 |
| --- | --- |
| qwen3:4b-instruct | 默认模型；CPU 环境稳定（推荐） |
| qwen3.5:9b / qwen3:14b / qwen3.8:latest | 质量更高，建议 GPU 环境 |
| deepseek-r1:8b / deepseek-r1:14b | 推理模型，注意思考链开销 |

> 无模型 / 断网时也可运行：使用 `--provider rule` 的确定性规则模式（仅兜底）。

---

## 2. 最常用命令

```bash
# 启动命令行对话（LLM 模式，默认 ollama + qwen3:4b-instruct）
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli chat

# 规则模式（无需模型，适合快速冒烟）
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli chat --provider rule

# 启动 Web UI（默认 127.0.0.1:8000）
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli web

# 指定端口 / 局域网访问启动 Web UI
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli web --host 0.0.0.0 --port 8080
# 然后从其他设备打开 http://<本机IP>:8080/

# 运行测试
.venv/bin/python -m pytest
```

---

## 3. 切换模型 / Provider

需要 LLM 的命令（`chat`、`web`、`extract-text`、`benchmark-extraction`）共用同一套切换方式。
Provider 可选：`rule` | `ollama`（HTTP API，推荐）| `ollama-cli`（子进程调用）| `openai-compatible`。

### 3.1 命令行参数（优先级最高）

```bash
# 切换到其它本地模型（HTTP API，速度最快）
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli chat \
  --provider ollama --model qwen3.5:9b

# 使用 ollama run 子进程方式（与终端 ollama run 行为一致）
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli chat \
  --provider ollama-cli --model qwen3:4b-instruct

# OpenAI 兼容服务（vLLM / LM Studio / 远程 API 等）
env PYTHONPATH=src QREST_AGENT_API_KEY=sk-xxx .venv/bin/python -m qrest_agent.cli chat \
  --provider openai-compatible --model your-model --base-url http://your-server:8000/v1

# Web UI 同样支持模型切换
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli web --port 8080 \
  --provider ollama --model qwen3:14b
```

### 3.2 环境变量（全局默认）

| 变量 | 作用 |
| --- | --- |
| `QREST_AGENT_PROVIDER` | 默认 provider（rule / ollama / ollama-cli / openai-compatible） |
| `QREST_AGENT_MODEL` | 默认模型名 |
| `QREST_AGENT_BASE_URL` | ollama HTTP / OpenAI 兼容服务的 base_url |
| `QREST_AGENT_API_KEY` | OpenAI 兼容服务的 API Key |

```bash
export QREST_AGENT_PROVIDER=ollama
export QREST_AGENT_MODEL=qwen3:14b
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli chat
```

### 3.3 配置文件（最低优先级）

`resources/llm/provider_config.json` 中的 `default_provider` / `default_model`
决定命令的默认值；`providers` 段描述各 provider 参数（如 `ollama` 的 `base_url`）。修改后全局生效。

---

## 4. 命令行参数速查

每个子命令都可执行 `python -m qrest_agent.cli <command> --help` 查看完整参数。

| 子命令 | 作用 | 关键参数 |
| --- | --- | --- |
| `chat` | 命令行对话 | `--provider/--model/--base-url/--api-key`、`--session-id`、`--artifact-root`、`--message`（可多次，脚本化）、`--transcript` |
| `web` | 浏览器 UI（标准库实现，无 FastAPI 依赖） | `--host`（默认 127.0.0.1，LAN 用 0.0.0.0）、`--port`（默认 8000）、模型参数同上、`--artifact-root` |
| `extract-text "文本"` | 单条文本跑完整 Agent 回合（JSON 输出） | 模型参数同上 |
| `extract-file <path>` | 对文件跑完整 Agent 回合 | — |
| `ingest-file <path>` | 只显示文件解析出的 source chunks | — |
| `export-from-file <path> <meta_out> <audit_out>` | 提取并在就绪时导出 metadata + audit | — |
| `validate <metadata.json>` | 确定性校验 metadata 文件 | — |
| `benchmark-extraction` | 提取基准 | `--provider/--model`、`--output` |
| `generate-qrest <meta.json> <data.txt> <out.qrest>` | 生成 .qrest | `--strict` |
| `preflight-generate-qrest <meta.json> <data.txt>` | 生成前检查 | — |
| `load-qrest <in.qrest> <meta_out.json> <data_out.txt>` | 解析 .qrest | `--compare-metadata-json` |
| `resources` | 列出捆绑资源/示例/工具 | `--json` |

---

## 5. 对话用法

```bash
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli chat
```

自然语言任务示例：

- `结构为钢框架，矩形平面，尺寸约42m × 25.2m。`（提取 + 自动推导 Parameters/BoundingBox）
- `地上14层，地下2层，首层4.5m，标准层3.3m。`（中间事实 → 自动推导 Elevation）
- `解析 resources/qrest_data/examples/kunming2/kunming2.qrest 并导入当前项目`
- `检查 resources/qrest_data/examples/kunming2/metadata.json 和 data.txt 能不能生成 qREST`
- `用当前项目状态和 data.txt 直接生成 qREST`
- `前面的长度不对，改为46.9m。`（修正历史值）

调试 / 底层命令（保留为 debug 入口，正式流程建议用自然语言）：

- `/help`、`/provider`（当前模型/模式）、`/state`（字段与校验状态）
- `/missing`、`/conflicts`、`/confirm Field.Path value`（如 `/confirm DataInfo.DT 0.02`）
- `/file path`、`/tools`（skills 与 tools 列表）
- `/load-qrest …`、`/generate-qrest …`、`/quit`

脚本化运行（自动消息 + 导出 transcript）：

```bash
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli chat \
  --provider rule \
  --message "项目名称为 Demo，采样间隔为 0.02s。" \
  --message "/confirm DataInfo.NPTS 30000" \
  --message "/state" \
  --transcript test_outputs/dialogue/cli_chat_transcript.json
```

---

## 6. Web UI

浏览器界面（左侧 Agent Activity 栏 + 中间对话 + 右侧 Project State）：
对话与附件、已确认/待确认/缺失/冲突计数、字段详情与 Evidence、This Turn /
Recent Turns / Inputs / Skills / Artifacts。

交互模型是 **Turn = 消息 + 附件**：

1. 点「添加附件」选择文件 → 只上传登记为待发送（不立即触发 Agent）；
2. 输入任务（如 `请根据这些资料整理当前项目的信息`）并发送 → 附件随消息一起处理；
3. 右侧查看字段状态与自动推导结果；点击 Artifacts 文件可预览内容；
   「导出 metadata.json」显示就绪状态与阻断原因。

```bash
# 默认：127.0.0.1:8000
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli web

# 指定端口 + 指定模型
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli web --port 8080 \
  --provider ollama --model qwen3.5:9b

# 局域网访问（从其它设备打开 http://<本机IP>:8000/）
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli web --host 0.0.0.0 --port 8000
```

底层 REST 端点：`/api/sessions`、`/api/upload`（只保存附件）、`/api/turn`（消息+附件）、
`/api/session`、`/api/artifacts`、`/api/export-metadata`。
可选 FastAPI 封装：`qrest_agent.api.app.create_app()`（需安装 `qrest-agent[api]`）。

---

## 7. 真实 LLM 验证脚本

`scripts/manual_e2e/` 提供真实模型场景与稳定性工具（结果写入 `test_outputs/llm_e2e/`）：

```bash
# 全部场景（中文规范化/复杂字段推导/修正/幻觉/qREST 任务…）
env PYTHONPATH=src .venv/bin/python scripts/manual_e2e/real_llm_scenarios.py qwen3:4b-instruct all

# 指定场景
env PYTHONPATH=src .venv/bin/python scripts/manual_e2e/real_llm_scenarios.py qwen3:4b-instruct elevation correction

# 稳定性：同模型同场景重复 N 次
env PYTHONPATH=src .venv/bin/python scripts/manual_e2e/stability_test.py qwen3:4b-instruct 3

# 跨模型对比表
env PYTHONPATH=src .venv/bin/python scripts/manual_e2e/compare_models.py
```

实测结论：CPU 环境 qwen3:4b-instruct 在核心场景 3 次重复结果一致；更大模型（9B+）
需要 GPU（见 `docs/qwen35_agent_test_report.md`、`docs/llm_model_stability_report.md`）。

---

## 8. 测试

```bash
.venv/bin/python -m pytest
```

测试把代表性输出写入 `test_outputs/` 供人工审阅。

---

## 9. 目录速览

```text
src/qrest_agent/
  agent/         QrestAgent 回合循环 / Planner / Extractor / Responder / 对话壳
  core/          Schema Contract、Canonicalization、Validator、Exporter（确定性层）
  state/         Working State（metadata 字段 + Intermediate Facts）
  skills/        Skill 注册与加载
  ingestion/     文档解析（pdf/docx/xlsx/csv/json…）
  tools/         确定性计算与 qREST 数据工具
  llm/           provider 客户端（ollama / ollama-cli / openai-compatible）与基准
  api/ web/      ApiService、可选 FastAPI、标准库 Web UI
resources/
  skills/        领域知识 SKILL.md（metadata / building_info / instrument_info / …）
  qrest_data/    捆绑的 qREST 文档 / 示例 / schema / 工具
  llm/           provider_config.json、benchmark_cases.json
docs/            设计文档与各轮进度（历史归档在 stage1-4/）
scripts/manual_e2e/  真实模型 E2E 与稳定性脚本
```

更多：`docs/real_llm_verification.md`（真实模型验证记录）、`docs/normalization_derivation_status.md`
（最近一轮改造进度）、`docs/llm_model_stability_report.md`（小模型稳定性）。