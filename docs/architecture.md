# qREST Agent Architecture

## Stage 1: Metadata Acquisition

The first stage builds a standard qREST project context from user messages and uploaded sources.

Flow:

1. `SourceManager` ingests chat text or files and creates searchable chunks.
2. `RuleBasedExtractor` or `LLMExtractor` creates `Candidate` values.
3. `MetadataState.submit_many()` merges candidates into audited field records.
4. `validate_state()` checks qREST required fields and cross-field consistency.
5. The agent asks for missing or conflicting information until validation passes.
6. `export_metadata()` writes qREST-compatible metadata.

The model is intentionally not allowed to edit final metadata directly.

## Stage 2: Algorithm Configuration

The exported object already reserves:

```json
{
  "analysis": {
    "method": null,
    "parameters": {},
    "status": "reserved"
  }
}
```

Later, a method-configuration agent can read the validated metadata and fill this section with algorithm-specific parameters.

## Provider Strategy

The current client layer supports:

- rule-based offline extraction for tests and bootstrapping;
- Ollama local models through `/api/chat`;
- OpenAI-compatible online or private APIs through `/chat/completions`.

Provider-specific SDKs can be added behind the same `complete_json()` boundary.

