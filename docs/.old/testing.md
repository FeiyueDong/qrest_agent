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
- `test_outputs/validation/metadata_policy_summary.json`
- `test_outputs/validation/weighted_missing_report.json`
- `test_outputs/validation/weighted_export_result.json`
- `test_outputs/validation/weighted_export_blocked.json`
- `test_outputs/agent/ready_metadata.json`
- `test_outputs/agent/ready_audit.json`
- `test_outputs/agent/not_ready_audit.json`
- `test_outputs/state/conflict_audit.json`
- `test_outputs/state/extension_preserved_metadata.json`
- `test_outputs/tools/load_qrest_result.json`
- `test_outputs/tools/loaded_metadata.json`
- `test_outputs/tools/loaded_data_head.txt`
- `test_outputs/tools/generate_qrest_result.json`
- `test_outputs/tools/generate_qrest_preflight_report.json`
- `test_outputs/tools/generate_qrest_strict_result.json`
- `test_outputs/tools/generated.qrest`
- `test_outputs/tools/registry_session_artifacts_result.json`
- `test_outputs/api/service_chat_upload_artifacts.json`
- `test_outputs/api/service_binary_docx_upload.json`
- `test_outputs/api/service_tool_result.json`
- `test_outputs/api/service_weighted_export_result.json`
- `test_outputs/api/service_blocked_export_result.json`
- `test_outputs/web/index.html`
- `test_outputs/web/server_smoke_flow.json`
- `test_outputs/ingestion/docx_chunks.json`
- `test_outputs/ingestion/pdf_chunks.json`
- `test_outputs/ingestion/docx_text.txt`
- `test_outputs/ingestion/pdf_text.txt`
- `test_outputs/ingestion/document_agent_extraction_results.json`
- `test_outputs/dialogue/basic_session_transcript.json`
- `test_outputs/dialogue/basic_state.txt`
- `test_outputs/dialogue/confirm_command_result.json`
- `test_outputs/dialogue/natural_language_conflict_resolution.json`
- `test_outputs/dialogue/llm_action_conflict_resolution.json`
- `test_outputs/dialogue/llm_action_field_confirmation.json`
- `test_outputs/dialogue/cli_chat_transcript.json`
- `test_outputs/dialogue/cli_chat_output.txt`
- `test_outputs/dialogue/qwen3_chat_transcript.json`
- `test_outputs/dialogue/file_command_result.json`
- `test_outputs/dialogue/tool_command_transcript.json`
- `test_outputs/dialogue/phase56_cli_tool_transcript.json`
- `test_outputs/dialogue/default_provider_smoke.json`
- `test_outputs/llm/benchmark_case_summary.json`
- `test_outputs/llm/rule_benchmark.json`
- `test_outputs/llm/deepseek-r1_1.5b_benchmark.json`
- `test_outputs/llm/qwen3.5_2b_benchmark.json`
- `test_outputs/llm/qwen3_4b-instruct_benchmark.json`

PDF ingestion currently depends on the system `pdftotext` command. The tests use `resources/input_doc/Kunming_building_metadata_test_case.pdf` and `resources/input_doc/Kunming_building_metadata_test_case.docx`.

These files are not fixtures. They are generated artifacts that show what the current system produced during the latest test run.

## LLM Benchmark Outputs

The local-model benchmark stores one JSON report per model. Each report contains aggregate metrics and per-case candidate details:

- `accuracy`: expected fields that were extracted with the expected value;
- `hallucination_rate`: forbidden fields that were extracted despite missing evidence;
- `json_valid_rate`: benchmark cases where the model output could be parsed as a JSON object.

The benchmark intentionally does not merge candidates into project state. It only checks whether an extractor can produce safe candidate records.

## Test Style

- Use pytest function tests and fixtures.
- Use `tmp_path` for transient files used only for assertions.
- Use the `artifact_dir` fixture for files that should remain available under `test_outputs/`.
- Keep generated artifacts small when possible. For large data files, store summaries or head samples unless the binary artifact itself is the behavior under test.
