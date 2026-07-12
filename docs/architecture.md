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

## Bundled qREST Tool Skills

`resources/qrest_data/` contains the local qREST reference bundle used by this project:

- protocol docs copied from qREST_Data;
- complete sample datasets;
- Linux `data_generator` and `data_loader` binaries.

`qrest_agent.tools.QrestDataTools` exposes these as deterministic agent skills:

- `generate_qrest(metadata_json, data_txt, output_qrest)`;
- `load_qrest(input_qrest, output_metadata_json, output_data_txt)`.

These tools are intentionally kept separate from LLM extraction. The model may request a conversion, but the conversion itself is performed by the bundled command-line tools and returns a structured `ToolResult`.

## Source Ingestion

`SourceManager` converts uploaded materials into `SourceChunk` records with stable source IDs and locations:

- PDF: uses the local `pdftotext` command and records page/chunk locations.
- DOCX: reads `word/document.xml` directly and records paragraph locations.
- CSV: records row-oriented text chunks.
- XLSX: reads worksheet XML and shared strings directly and records sheet/chunk locations.

The ingestion layer extracts text only. Candidate generation remains a separate extractor step so that deterministic validation and evidence tracking stay independent from file parsing.

## Dialogue Shell

The first dialogue interface is a command-line shell exposed by `qrest_agent.cli chat`.

It supports two modes:

- interactive input from a terminal;
- scripted `--message` turns for tests and reproducible smoke runs.

The shell keeps one in-memory `ChatSession` per process. Each turn can extract candidates, update metadata state, print missing/conflict prompts, and accept explicit user confirmation through `/confirm Field.Path value`.

This is not yet a full natural-language correction system. For important corrections, the user should use explicit `/confirm` commands so that the deterministic state layer receives a confirmed candidate with clear evidence.
