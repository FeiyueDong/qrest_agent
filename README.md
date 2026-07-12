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
.venv/bin/python -m qrest_agent.cli validate /home/yue/CodeFiles/qrest_data/resource/metadata.json
.venv/bin/python -m qrest_agent.cli extract-text "项目名为 Demo，大楼高度 62.5m，采样间隔 0.02s。"
```

## Design Boundary

The LLM layer only produces `Candidate` records. The deterministic core owns:

- schema paths;
- candidate merge rules;
- missing-field checks;
- conflict detection;
- qREST metadata export.

This is deliberate: when key information is missing, the agent should report the missing fields and ask the user for more evidence instead of inventing engineering values.

