# Testing

The project uses `pytest`.

Run all tests from the repository root:

```bash
.venv/bin/python -m pytest
```

The pytest configuration in `pyproject.toml` sets `pythonpath = ["src"]`, so `PYTHONPATH=src` is not required for normal test runs.

## Human-Readable Outputs

Tests write representative outputs to `test_outputs/`. This directory is ignored by git and is intended for manual inspection after a test run.

Important files include:

- `test_outputs/validation/kunming2_ready_report.json`
- `test_outputs/validation/missing_dt_report.json`
- `test_outputs/validation/channel_mismatch_report.json`
- `test_outputs/agent/ready_metadata.json`
- `test_outputs/agent/ready_audit.json`
- `test_outputs/agent/not_ready_audit.json`
- `test_outputs/state/conflict_audit.json`
- `test_outputs/state/extension_preserved_metadata.json`
- `test_outputs/tools/load_qrest_result.json`
- `test_outputs/tools/loaded_metadata.json`
- `test_outputs/tools/loaded_data_head.txt`
- `test_outputs/tools/generate_qrest_result.json`
- `test_outputs/tools/generated.qrest`

These files are not fixtures. They are generated artifacts that show what the current system produced during the latest test run.

## Test Style

- Use pytest function tests and fixtures.
- Use `tmp_path` for transient files used only for assertions.
- Use the `artifact_dir` fixture for files that should remain available under `test_outputs/`.
- Keep generated artifacts small when possible. For large data files, store summaries or head samples unless the binary artifact itself is the behavior under test.
