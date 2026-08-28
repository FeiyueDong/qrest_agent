# qREST Agent

qREST Agent is a first-pass framework for building a skill-first AI assistant for qREST projects.

The current focus is an agentic first stage:

- route natural-language qREST tasks through repo-native skills and skill handlers;
- collect building, instrumentation, and data metadata from user messages and uploaded materials;
- store extracted values as candidates with evidence;
- merge candidates into a project state without letting the model directly overwrite final metadata;
- validate required qREST fields deterministically;
- export standard qREST `metadata.json`;
- load and generate `.qrest` artifacts through deterministic qREST tools;
- keep an `analysis` extension point for later algorithm-parameter configuration.

The core package intentionally has no third-party runtime dependency yet, so it can run in the current `.venv` before local and online model providers are finalized.

## Quick Start

```bash
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli resources
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli validate resources/qrest_data/examples/kunming2/metadata.json
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli extract-text "项目名为 Demo，大楼高度 62.5m，采样间隔 0.02s。"
```

## Tests

```bash
.venv/bin/python -m pytest
```

Tests write human-readable artifacts to `test_outputs/` for manual review. See [docs/testing.md](docs/testing.md).

## LLM Extraction Benchmark

The extraction benchmark compares deterministic extraction with local or online model providers:

```bash
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli benchmark-extraction \
  --provider rule \
  --output test_outputs/llm/rule_benchmark.json

env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli benchmark-extraction \
  --provider ollama-cli \
  --model qwen3:4b-instruct \
  --output test_outputs/llm/qwen3_4b-instruct_benchmark.json
```

Current local-model notes are tracked in [docs/llm_models.md](docs/llm_models.md).

## Command-Line Dialogue

By default, `chat`, `extract-text`, and `benchmark-extraction` read `resources/llm/provider_config.json`. The current default is `ollama-cli` with `qwen3:4b-instruct`.

For local-model testing with Ollama:

```bash
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli chat
```

For a deterministic rule-based smoke test:

```bash
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli chat \
  --provider rule \
  --transcript test_outputs/dialogue/manual_chat_transcript.json
```

Prefer natural-language tasks inside the chat:

- `解析 resources/qrest_data/examples/kunming2/kunming2.qrest 并导入当前项目`
- `检查 metadata.json 和 data.txt 能不能生成 qREST`
- `用当前项目状态和 data.txt 直接生成 qREST`

Useful inspection and low-level commands:

- `/state`
- `/provider`
- `/debug`
- `/missing`
- `/conflicts`
- `/file path/to/source.pdf`
- `/tools`
- `/load-qrest input.qrest [source_metadata.json]`
- `/generate-qrest metadata.json data.txt [output.qrest]`
- `/confirm Field.Path value`
- `/quit`

`/tools` lists repo-native skills, registered skill handlers, deterministic tools, and low-level shortcut commands.

For user instructions that should modify state, the dialogue layer asks the configured model to parse a structured action, then Python validates and executes it. Examples:

- `冲突部分全部更新为候选值`
- `所有冲突保留当前值`
- `采样点数按 30000 处理`

The chat startup line prints the active provider/model/extractor. If an LLM call fails or returns no valid candidates, the dialogue response reports that it fell back to rule extraction.

The extractor is hybrid during LLM runs: the local/online model extracts flexible natural-language facts, and deterministic rules still run afterward to derive qREST-specific structures such as `BuildingInfo.Elevation` and `InstrumentInfo.Channels`.

## Browser UI

The lightweight browser UI uses Python's standard library and does not require FastAPI:

```bash
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli web \
  --host 127.0.0.1 \
  --port 8000
```

Open `http://127.0.0.1:8000/` on the Linux machine.

For LAN testing, bind to all interfaces and visit the Linux machine's LAN IP from another device:

```bash
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli web \
  --host 0.0.0.0 \
  --port 8000
```

Then open `http://<linux-ip>:8000/` from a device on the same network. The local firewall must allow inbound traffic on that port.

The page supports chat turns, document upload, current validation status, extracted field inspection, and artifact preview. It uses the same provider/model defaults as the CLI unless `--provider`, `--model`, or `--base-url` is overridden.

The page can also export `metadata.json` into the current session artifacts. Export follows the weighted metadata policy marked in `resources/qrest_data/examples/metadata.json`:

- `必须`: blocks export when missing;
- `重要`: exports with a warning and fills the annotated default value;
- `不重要`: exports with an info note and leaves the value blank.

## Bundled qREST Resources

The project carries a local qREST reference bundle under `resources/qrest_data/`:

- `docs/`: qREST storage and transfer protocol documents;
- `examples/kunming2/` and `examples/wuhan/`: sample `metadata.json`, `data.txt`, and `.qrest` files;
- `tools/linux/bin/`: bundled `data_generator` and `data_loader` binaries copied from qREST_Data.

This keeps tests and agent workflows independent from `/home/yue/CodeFiles/qrest_data`.

Input documents for ingestion tests live under `resources/input_doc/`. PDF parsing currently uses the system `pdftotext` command; DOCX/XLSX/CSV parsing uses the Python standard library.

## qREST Skills And Tools

The preferred dialogue path is skill-first. Natural-language requests are routed by `TaskCoordinator` to registered skill handlers:

- `qrest_data_loading`: parse an existing `.qrest` file, write readable artifacts, and import loaded metadata into the session.
- `qrest_data_generation`: preflight or generate a `.qrest` file from metadata and time-series data.

The skill handlers call deterministic tools through `ToolRegistry`. The command-line tools remain available as low-level shortcuts:

```bash
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli generate-qrest \
  resources/qrest_data/examples/kunming2/metadata.json \
  resources/qrest_data/examples/kunming2/data.txt \
  /tmp/kunming2.qrest

env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli load-qrest \
  resources/qrest_data/examples/kunming2/kunming2.qrest \
  /tmp/metadata.json \
  /tmp/data.txt
```

Inside Python, use `QrestDataTools.generate_qrest()` and `QrestDataTools.load_qrest()` as deterministic tools.

`generate-qrest` runs a deterministic preflight before calling the bundled binary. It validates metadata and reports data mismatches such as `DataInfo.NPTS` not matching the number of rows in `data.txt`. Warnings are shown in the `ToolResult`; use `--strict` to make warnings block generation.

The dialogue shell still accepts low-level commands:

```bash
/load-qrest resources/qrest_data/examples/kunming2/kunming2.qrest
/generate-qrest resources/qrest_data/examples/kunming2/metadata.json resources/qrest_data/examples/kunming2/data.txt
```

These commands are kept for precise debugging and scripted smoke runs. User-facing workflows should prefer natural-language tasks handled by skills.

When a dialogue session supplies a `session_id`, tool outputs are managed under that session's artifact directory.

## API Surface

The first API layer is service-first and dependency-light:

- `qrest_agent.api.ApiService` manages sessions, chat turns, text uploads, tool calls, and artifacts.
- `qrest_agent.api.app.create_app()` provides an optional FastAPI wrapper. Install `qrest-agent[api]` before serving it.

The API service and CLI both call the same deterministic validator, state merger, skill handlers, and `ToolRegistry`.

## Design Boundary

The LLM layer only produces `Candidate` records. The deterministic core owns:

- schema paths;
- candidate merge rules;
- missing-field checks;
- conflict detection;
- qREST metadata export.

This is deliberate: when key information is missing, the agent should report the missing fields and ask the user for more evidence instead of inventing engineering values.

## Architecture Refactor Status (Phase 1-2)

Per [docs/qrest-agent 架构重构方案.md](docs/qrest-agent%20架构重构方案.md), the project is migrating from a fixed-pipeline design to an agent-led architecture:

- `qrest_agent.state.WorkingState` (new): canonical working state. Every fact is stored as `value + status + evidence (+ derived_from)` with statuses `missing / extracted / uncertain / derived / inferred / confirmed / conflict`. `inferred` and `uncertain` never enter final metadata by default, and export requires evidence.
- `qrest_agent.agent.agent.QrestAgent` (new): the Phase 1 main agent. It owns the Working State, decides the next action (`ask_missing / resolve_conflicts / review_warnings / ready`), and runs the "understand → extract → update state → validate → decide" loop. Its system prompt (`AGENT_SYSTEM_PROMPT`) defines the agent's decision authority and anti-hallucination rules.
- `MetadataAgent` / `MetadataState` are now transitional facades over `QrestAgent` / `WorkingState`; they keep the old API working while Phase 3 splits the remaining modules.
- Evidence requirement: `WorkingState.to_metadata()` (and the facade) only export values whose status is exportable AND that carry evidence.

Phase tracking lives in [docs/refactor_status.md](docs/refactor_status.md).
