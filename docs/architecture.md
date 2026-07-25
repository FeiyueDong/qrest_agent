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

For local model runs, extraction is hybrid rather than model-only. `LLMExtractor` reads the text first, then `RuleBasedExtractor` still runs as a deterministic companion. This lets the model handle flexible wording while the rule layer performs qREST-specific engineering derivations such as:

- deriving `BuildingInfo.Elevation` from floor counts and story heights;
- mapping monitored floor labels such as `B1F`, `首层`, `3层`, `6层`, `9层`, `13层` to absolute Z elevations;
- deriving `InstrumentInfo.Channels` from monitoring floors, per-floor sensor count, footprint dimensions, and left/right/middle sensor layout descriptions.

If the LLM fails or returns no valid candidates, the turn falls back to rule-only extraction and records `fallback_reason`.

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

`generate_qrest` performs deterministic preflight checks before running the binary:

- qREST metadata validation;
- `data.txt` row count;
- first-row channel count;
- malformed row and non-numeric row checks;
- comparison against `DataInfo.NPTS` and `InstrumentInfo.ChannelNum`.

Mismatches are returned as warnings unless strict mode is enabled. This keeps existing imperfect engineering examples usable while still surfacing problems to the user.

`load_qrest` returns a readable summary of the parsed metadata and data profile. It can also compare loaded metadata against a reference metadata JSON.

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

The shell also exposes deterministic tool commands:

- `/provider` and `/debug` show the active provider, model, and extractor;
- `/file path` ingests a local file into the metadata workflow;
- `/tools` lists available deterministic tools;
- `/load-qrest input.qrest [source_metadata.json]` parses a binary qREST file into session artifacts;
- `/generate-qrest metadata.json data.txt [output.qrest]` generates a qREST file and surfaces preflight warnings.

CLI defaults are loaded from `resources/llm/provider_config.json`. If no `--provider` is supplied, the current default is `ollama-cli` with `qwen3:4b-instruct`. Tests and deterministic smoke runs should pass `--provider rule` explicitly.

When an LLM extractor fails or produces no valid candidates, `MetadataAgent.run_turn()` falls back to the rule-based extractor and records `fallback_reason` in the turn result. The dialogue response surfaces this fallback so the user can tell whether a model was actually useful for that turn.

Natural-language correction now uses a structured action interpreter. When a message looks like a state-changing instruction, `ActionInterpreter` asks the configured model to return an action such as:

- `resolve_conflicts` with `choice=current|alternative`;
- `confirm_field` with validated qREST field paths and values;
- `none` when the message should continue through normal extraction.

The model only parses intent. Python still validates field paths, checks conflicts, coerces value types, creates `confirmed` candidates, and merges them through `MetadataState`. If no model is configured or the model output is unusable, a small deterministic fallback handles simple bulk conflict phrases.

## Browser UI

`qrest_agent.cli web` serves a dependency-light browser UI backed by Python's standard-library `http.server`.

The web UI is intentionally a thin client over `ApiService`:

- `POST /api/sessions` creates an in-memory `ChatSession`;
- `POST /api/chat` sends natural-language input or dialogue commands;
- `POST /api/upload` accepts base64-encoded files and forwards them to the same ingestion pipeline used by `/file`;
- `GET /api/session` refreshes runtime, validation, records, and artifacts;
- `GET /api/artifact` previews text artifacts.

The server defaults to `127.0.0.1` for local Linux validation. Binding `--host 0.0.0.0` exposes the same UI to other devices on the LAN through `http://<linux-ip>:<port>/`, subject to firewall and network policy.

Like the CLI, the web command loads provider defaults from `resources/llm/provider_config.json`. The page displays the runtime provider/model from the session so local-model usage is visible.

## API Surface

The project now exposes an `ApiService` in `qrest_agent.api.service`.

The service provides the stable boundary used by future web clients:

- create and inspect sessions;
- send chat messages;
- upload text or binary files into a session;
- execute deterministic tools through the same `ToolRegistry` used by the CLI;
- list and read session artifacts.

`qrest_agent.api.app.create_app()` is an optional FastAPI wrapper around this service. FastAPI is not a required runtime dependency for the core package; install the optional `api` extras before serving the HTTP app.
