# qREST Agent Todo

This checklist tracks the current development plan. The priority is to make Stage 1 reliable before expanding Stage 2.

## Goal

Build an AI-assisted qREST configuration agent that can:

- collect qREST metadata from conversation and uploaded files;
- extract only supported fields as candidate values with evidence;
- merge candidates into audited project state;
- report missing or conflicting key information instead of inventing values;
- export standard qREST `metadata.json`;
- call deterministic qREST data tools to generate or parse `.qrest` files;
- keep an interface for later algorithm-parameter configuration.

## Current Baseline

- [x] Python project scaffold under `src/qrest_agent`.
- [x] Core candidate/evidence/state models.
- [x] Deterministic qREST metadata validator.
- [x] Text and JSON source ingestion.
- [x] Rule-based extraction fallback.
- [x] Ollama, Ollama CLI, and OpenAI-compatible client interfaces.
- [x] Bundled qREST docs, examples, and Linux data tools under `resources/qrest_data`.
- [x] `data_generator` and `data_loader` wrapped as deterministic agent tools.
- [x] CLI smoke commands and unit tests.

## Phase 1: Metadata Core Hardening

- [x] Define a formal qREST metadata schema file in this repo.
- [x] Separate required, optional, and extension fields.
- [x] Preserve extension fields such as `DeviceType` during import/export.
- [ ] Add field-level unit metadata and conversion policy.
- [ ] Add validation severity levels for hard errors, warnings, and review-only items.
- [ ] Improve conflict records with source comparison summaries.
- [ ] Add explicit user confirmation records for values accepted through dialogue.
- [x] Add export of both final `metadata.json` and audit trail JSON.

Acceptance:

- Existing bundled examples validate without external paths.
- Missing required fields are reported by exact field path.
- Conflicting values never silently overwrite confirmed values.
- Exported metadata remains qREST-compatible.

## Phase 2: Source Ingestion

- [x] Add PDF text ingestion.
- [x] Add DOCX text ingestion.
- [x] Add XLSX table ingestion.
- [x] Add CSV ingestion with channel-table recognition.
- [x] Keep a standard `SourceChunk` representation for page, paragraph, sheet, range, and row locations.
- [x] Add source search over ingested chunks.
- [x] Add tests using small synthetic PDF/DOCX/XLSX fixtures.

Acceptance:

- Uploaded engineering materials can be converted into searchable chunks.
- Every extracted non-null value can point back to a source chunk.
- Unsupported files fail with a clear message.

## Phase 3: LLM Extraction Reliability

- [x] Improve extraction prompts for qREST field paths.
- [x] Add model capability notes for local small models.
- [x] Add benchmark cases for extraction accuracy, hallucination rate, and JSON validity.
- [x] Add provider config file for local and online APIs.
- [x] Add retries and structured error reporting for Ollama HTTP failures.
- [x] Compare `deepseek-r1:1.5b` against rule-based extraction on simple examples.
- [x] Test other local models after deployment.

Acceptance:

- Invalid model output is filtered before state merge.
- If the model cannot produce valid candidates, deterministic fallback still works.
- Hallucinated values without evidence are rejected.

## Phase 4: Dialogue Workflow

- [x] Add session state storage for multi-turn interaction.
- [x] Add commands to inspect current metadata state.
- [x] Generate human-readable questions for missing fields.
- [x] Generate human-readable questions for conflicts.
- [x] Support user confirmation and correction of candidate values.
- [x] Add a conversation transcript to the audit trail.

Acceptance:

- A user can complete a metadata file through multiple turns.
- The agent asks for missing information instead of filling unknown values.
- Confirmed user values are protected from lower-confidence extracted values.

## Phase 5: qREST Tool Skills

- [ ] Add preflight validation before `generate_qrest`.
- [ ] Report data/metadata mismatches such as `NPTS` versus actual text rows.
- [ ] Add output artifact management under a project/session directory.
- [ ] Add a readable summary for `load_qrest` results.
- [ ] Add optional comparison between generated and source metadata.
- [ ] Add a tool-dispatch path from dialogue intent to `ToolRegistry.execute`.

Acceptance:

- The agent can parse a `.qrest` file into readable metadata and text data.
- The agent can generate a `.qrest` file from validated metadata and text data.
- Tool warnings are surfaced to the user, not hidden.

## Phase 6: API Surface

- [ ] Decide whether the first interface is CLI-only, FastAPI, or both.
- [ ] Add FastAPI app skeleton if web/API development starts.
- [ ] Add upload endpoints.
- [ ] Add chat/session endpoints.
- [ ] Add project artifact endpoints.
- [ ] Add API tests for validation and extraction flows.

Acceptance:

- The core agent can be used without changing core logic.
- API routes call the same deterministic validator and tool registry as the CLI.

## Phase 7: Stage 2 Interface

- [ ] Define `analysis` section schema.
- [ ] Define method configuration input/output boundary.
- [ ] Add placeholder tool specs for algorithm configuration.
- [ ] Add validation for method config once algorithms are selected.
- [ ] Keep Stage 2 disabled until Stage 1 metadata is validated.

Acceptance:

- Stage 1 output can be consumed by a future method-configuration agent.
- Incomplete metadata blocks algorithm configuration.

## Immediate Next Tasks

1. Exercise the CLI dialogue manually with `qwen3:4b-instruct`.
2. Add file attachment support inside the interactive chat loop.
3. Add persistent session reload if multi-day dialogue sessions become necessary.
4. Add preflight checks around qREST data tool calls.
5. Add tool-dispatch from dialogue intent to qREST data tools.
