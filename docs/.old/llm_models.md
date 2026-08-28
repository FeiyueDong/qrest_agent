# Local Model Notes

This page records the current extraction benchmark results for small local models. The benchmark is intentionally strict: the model must return valid JSON candidates, use exact qREST field paths, avoid unsupported values, and keep missing information out of the final state.

## Benchmark Command

Rule-based baseline:

```bash
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli benchmark-extraction \
  --provider rule \
  --output test_outputs/llm/rule_benchmark.json
```

Ollama CLI model:

```bash
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli benchmark-extraction \
  --provider ollama-cli \
  --model qwen3:4b-instruct \
  --output test_outputs/llm/qwen3_4b-instruct_benchmark.json
```

## Results

| Model | Accuracy | Hallucination Rate | JSON Valid Rate | Notes |
|---|---:|---:|---:|---|
| rule | 1.00 | 0.00 | 1.00 | Deterministic baseline and fallback. |
| deepseek-r1:1.5b | 0.00 | 0.00 | 1.00 | Returned valid JSON but no useful candidates. Not suitable as the primary extractor. |
| qwen3.5:2b | 0.00 | 0.00 | 0.00 | Produced long thinking text and no parseable JSON in the current CLI prompt path. |
| qwen3:4b-instruct | 0.67 | 0.00 | 1.00 | Best tested local LLM so far. Simple metadata extraction works; longer engineering prose still needs normalization and deterministic fallback. |

The detailed artifacts are saved under `test_outputs/llm/` for manual review.

The command-line dialogue path has also been smoke-tested with `qwen3:4b-instruct`:

```bash
env PYTHONPATH=src .venv/bin/python -m qrest_agent.cli chat \
  --provider ollama-cli \
  --model qwen3:4b-instruct \
  --message "项目名称为 DemoBuilding。事件名称为 2025_TEST_EVENT。采样时间间隔：0.02 s。数据点数：30000。" \
  --message "/state" \
  --transcript test_outputs/dialogue/qwen3_chat_transcript.json
```

This smoke test extracted `BuildingInfo.ProjectName`, `DataInfo.EventName`, and `DataInfo.DT`, then reported the remaining missing required fields.

## Current Recommendation

Use the rule-based extractor as the reliability fallback and use `qwen3:4b-instruct` as the first local LLM candidate for continued testing.

The CLI now reads `resources/llm/provider_config.json` for default model settings. With the current configuration, omitting `--provider` in `chat`, `extract-text`, or `benchmark-extraction` uses `ollama-cli` with `qwen3:4b-instruct`. Use `--provider rule` for deterministic offline tests.

Do not use `deepseek-r1:1.5b` or `qwen3.5:2b` as the default strict extractor at this stage. They may still be useful later for explanation or relaxed dialogue, but they are not reliable enough for direct candidate generation.

The state merge path must continue to reject invalid field paths, unsupported non-null values, and model output that fails JSON parsing.
