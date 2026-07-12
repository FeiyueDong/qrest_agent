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

## Bundled qREST Resources

The project carries a local qREST reference bundle under `resources/qrest_data/`:

- `docs/`: qREST storage and transfer protocol documents;
- `examples/kunming2/` and `examples/wuhan/`: sample `metadata.json`, `data.txt`, and `.qrest` files;
- `tools/linux/bin/`: bundled `data_generator` and `data_loader` binaries copied from qREST_Data.

This keeps tests and agent workflows independent from `/home/yue/CodeFiles/qrest_data`.

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

## Design Boundary

The LLM layer only produces `Candidate` records. The deterministic core owns:

- schema paths;
- candidate merge rules;
- missing-field checks;
- conflict detection;
- qREST metadata export.

This is deliberate: when key information is missing, the agent should report the missing fields and ask the user for more evidence instead of inventing engineering values.
