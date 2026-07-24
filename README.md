# qREST Agent

qREST Agent is a first-pass framework for building an AI-assisted metadata acquisition tool for qREST projects.

The current focus is the first stage:

- collect building, instrumentation, and data metadata from user messages and uploaded materials;
- store extracted values as candidates with evidence;
- merge candidates into a project state without letting the model directly overwrite final metadata;
- validate required qREST fields deterministically;
- export standard qREST `metadata.json`;
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

Useful commands inside the chat:

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

## Bundled qREST Resources

The project carries a local qREST reference bundle under `resources/qrest_data/`:

- `docs/`: qREST storage and transfer protocol documents;
- `examples/kunming2/` and `examples/wuhan/`: sample `metadata.json`, `data.txt`, and `.qrest` files;
- `tools/linux/bin/`: bundled `data_generator` and `data_loader` binaries copied from qREST_Data.

This keeps tests and agent workflows independent from `/home/yue/CodeFiles/qrest_data`.

Input documents for ingestion tests live under `resources/input_doc/`. PDF parsing currently uses the system `pdftotext` command; DOCX/XLSX/CSV parsing uses the Python standard library.

## qREST Data Tools

The command-line tools are exposed as agent-callable wrappers and CLI commands:

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

The dialogue shell can also call these tools:

```bash
/load-qrest resources/qrest_data/examples/kunming2/kunming2.qrest
/generate-qrest resources/qrest_data/examples/kunming2/metadata.json resources/qrest_data/examples/kunming2/data.txt
```

When a dialogue session supplies a `session_id`, tool outputs are managed under that session's artifact directory.

## API Surface

The first API layer is service-first and dependency-light:

- `qrest_agent.api.ApiService` manages sessions, chat turns, text uploads, tool calls, and artifacts.
- `qrest_agent.api.app.create_app()` provides an optional FastAPI wrapper. Install `qrest-agent[api]` before serving it.

The API service and CLI both call the same deterministic validator, state merger, and `ToolRegistry`.

## Design Boundary

The LLM layer only produces `Candidate` records. The deterministic core owns:

- schema paths;
- candidate merge rules;
- missing-field checks;
- conflict detection;
- qREST metadata export.

This is deliberate: when key information is missing, the agent should report the missing fields and ask the user for more evidence instead of inventing engineering values.
