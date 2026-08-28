# Agentic Data Generation Transition Plan

This document plans the first step of moving qREST Agent from a mostly hard-coded workflow toward an AI-led assistant with qREST-specific skills and deterministic tools.

Status: implemented as part of the broader skill-first task architecture. See [skill_first_architecture.md](skill_first_architecture.md) for the current module map and extension guide.

## Purpose

The target product shape is:

- a main dialogue AI agent owns interaction, task understanding, progress summaries, and next-step decisions;
- qREST skills describe professional workflows, constraints, prompts, and tool-use policy;
- deterministic tools execute data generation, parsing, validation, export, and artifact management;
- final engineering readiness remains governed by validation and evidence, not by model confidence alone.

The first transition phase focuses on data generation. In this document, data generation means producing a usable qREST data artifact from validated metadata and time-series data, including preflight checks, execution, artifact tracking, and user-facing explanation.

## Original Baseline

The current implementation already contains the reliable core pieces:

- `MetadataAgent` owns metadata state, extraction, validation, and export.
- `ChatSession` owns command-style dialogue and natural-language corrections.
- `ToolRegistry` exposes `generate_qrest` and `load_qrest`.
- `QrestDataTools.generate_qrest()` runs deterministic preflight checks before calling the bundled `data_generator`.
- `ApiService.run_tool()` can execute tools and update session artifacts.
- The browser and CLI expose `/generate-qrest` as an explicit command.

The main limitation was that the flow was command-driven and implementation-driven. The AI could extract fields or parse simple actions, but it did not yet act as the primary coordinator of a qREST data-generation task.

## Implemented State

The data-generation transition has been implemented and expanded into a general task-handler architecture:

- `resources/skills/qrest_data_generation/` defines the data-generation skill.
- `resources/skills/qrest_data_loading/` defines the data-loading skill.
- `qrest_agent.skills.SkillRegistry` discovers and loads repo-native skills.
- `qrest_agent.agent.tasks.TaskCoordinator` detects task-level intent.
- `qrest_agent.agent.task_handlers.TaskHandlerRegistry` selects concrete handlers.
- `QrestDataGenerationHandler` owns generation preflight/export/generation behavior.
- `QrestDataLoadingHandler` owns `.qrest` loading/import behavior.
- `ToolRegistry` exposes `preflight_generate_qrest`, `generate_qrest`, and `load_qrest`.
- `ChatSession.to_dict()` exposes `skills`, `skill_handlers`, and `task_logs` to CLI/API/Web.
- `/help`, `/tools`, README, architecture docs, and Web UI now present the system as skill-first.

## Target Behavior

The user should be able to speak in task-level language, for example:

- "用当前项目状态和这个 data.txt 生成 qREST 数据。"
- "检查这份 metadata 和数据文件能不能生成 qREST。"
- "严格模式生成，如果有任何不一致就停止。"
- "先帮我看看还缺什么，能生成时再生成。"

The main agent should:

1. identify that the user wants a data-generation workflow;
2. inspect current session state, available files, and artifacts;
3. call the data-generation skill to decide required inputs and safety checks;
4. call deterministic preflight and generation tools when inputs are sufficient;
5. explain blocking errors, warnings, generated artifacts, and next actions;
6. never invent missing metadata, file paths, channel counts, sampling intervals, or engineering assumptions.

## Architecture Direction

The first transition should add an agentic layer without removing the deterministic core.

Recommended shape:

```text
User
  |
  v
MainDialogueAgent
  |
  +-- SkillLibrary
  |     +-- qrest_data_generation
  |
  +-- ToolRegistry
  |     +-- preflight_generate_qrest
  |     +-- generate_qrest
  |     +-- load_qrest
  |
  +-- SessionState
        +-- metadata records
        +-- source chunks
        +-- artifacts
        +-- task log
```

The main agent should not contain qREST data-generation details directly. It should consult a skill definition that explains the workflow and then call tools with validated arguments.

## New Concepts

### Main Dialogue Agent

Create a higher-level dialogue coordinator above or beside `ChatSession`. It should handle task-level intent and route to skills.

Initial responsibilities:

- classify user turns into metadata acquisition, data generation, data loading, state inspection, or ordinary conversation;
- maintain a compact task summary for the current session;
- decide whether the request needs a skill;
- call skill planning logic and deterministic tools;
- produce a user-facing answer that includes evidence, warnings, and artifact paths.

This can initially be a small Python coordinator rather than a fully general autonomous loop.

### Skill Definition

Add a repo-native skill format for qREST workflows. A skill should be readable by the main agent and testable by Python.

Suggested first skill:

```text
resources/skills/qrest_data_generation/
  SKILL.md
  prompt.md
  tool_policy.json
  examples/
```

The skill should define:

- when the skill applies;
- required inputs: metadata JSON or validated session metadata, data TXT, output target, strict mode;
- forbidden behavior: do not guess missing engineering values, do not generate if mandatory validation fails, do not hide preflight warnings;
- workflow steps;
- tool argument mapping;
- response format guidance;
- examples of blocked, warning, and successful generations.

The skill can begin as documentation plus structured policy. Later it can grow into executable skill handlers if needed.

### Deterministic Tool Boundary

Keep `QrestDataTools` as the execution boundary, but expose preflight as a first-class tool.

Current `generate_qrest()` internally runs preflight. For an agentic workflow, the model needs to ask "can I generate?" before it asks "please generate." Add an explicit registry entry:

- `preflight_generate_qrest(metadata_json, data_txt)`

The generation tool should keep its internal preflight as a final guard.

### Session Artifacts

Data-generation tasks need clear artifact ownership.

Minimum artifact outputs:

- `generated.qrest`
- `generate_qrest_preflight_report.json`
- `generate_qrest_result.json`
- optional `metadata.json` used for generation if exported from session state

The main agent should describe these artifacts by name and path, and the API/browser should list them.

### Task Log

Add a lightweight task log to the session audit trail.

Each task event should record:

- user request;
- selected skill;
- selected tool;
- tool arguments after path resolution;
- preflight result;
- generated artifact paths;
- final status: blocked, warning, success, or failed.

This log is important because an AI-led workflow needs traceability.

## Implementation Plan Status

### Step 1: Document and Register the Skill

- [x] Add `resources/skills/qrest_data_generation/SKILL.md`.
- [x] Add a short structured policy file for required inputs and forbidden actions.
- [x] Add one blocked example, one warning example, and one success example.
- [x] Add a skill registry module that can list available local qREST skills.

Acceptance:

- the skill can be discovered by name;
- the skill text clearly states that missing engineering information must be reported, not invented;
- tests can load the skill from the repo without external services.

### Step 2: Promote Preflight to a Tool

- [x] Add a `preflight_generate_qrest` tool spec to `ToolRegistry`.
- [x] Return a structured report matching `PreflightReport.to_dict()`.
- [x] Write the preflight report into session artifacts when called with `session_id`.
- [x] Keep `generate_qrest()` preflight behavior as a guard.

Acceptance:

- API and CLI can call preflight directly;
- preflight reports metadata validation errors, row count mismatch, channel mismatch, malformed rows, and non-numeric rows;
- generation still blocks on hard preflight errors.

### Step 3: Add Data-Generation Intent Handling

- [x] Add a task-level intent for natural-language data-generation requests.
- [x] Route data-generation requests to the new skill instead of requiring `/generate-qrest`.
- [x] Resolve inputs from explicit paths, current session artifacts, or current validated metadata.
- [x] Ask for missing file paths or blocked metadata fields when inputs are insufficient.

Acceptance:

- "检查这两个文件能不能生成 qREST" runs preflight;
- "用当前 metadata 和 data.txt 生成 qREST" runs generation when inputs are sufficient;
- unresolved metadata or absent data files produce a question, not a guessed path or guessed value.

### Step 4: Export Session Metadata for Generation

- [x] When the user asks to use current project state, prepare metadata export through the existing weighted export layer.
- [x] If export is blocked, report the blocking fields and stop.
- [x] If export succeeds, write a session-scoped `metadata.json` artifact and pass that path to preflight/generation.

Acceptance:

- generation from current state uses the same deterministic export policy as manual export;
- missing mandatory fields block generation;
- important missing fields use existing default-warning behavior only through the export layer.

### Step 5: Add Agentic Response Summaries

- [x] Convert tool results into concise user-facing summaries.
- [x] Include status, important warnings, blocking errors, and artifact paths.
- [x] Separate "process succeeded" from "input is fully consistent".

Acceptance:

- a successful binary execution with preflight warnings is reported as generated with warnings;
- a blocked preflight clearly names the blocking field or data issue;
- generated artifacts are visible through CLI/API/browser state.

### Step 6: Regression Tests

Add targeted tests for:

- [x] skill registry loading;
- [x] direct preflight tool execution;
- [x] natural-language preflight intent;
- [x] natural-language generation intent;
- [x] blocked export from incomplete session metadata;
- [x] warning case where generation is allowed but mismatch is surfaced;
- [x] artifact creation and task-log recording.

Acceptance:

- full unit suite passes;
- test artifacts show the final generated `.qrest`, preflight report, and task log for review.

## Local Model Strategy

Small local models should not be trusted as the sole executor of this workflow. For the first transition phase, use them for:

- intent recognition;
- tool argument extraction from simple user requests;
- response phrasing;
- asking follow-up questions.

Keep deterministic Python responsible for:

- path existence checks;
- metadata export readiness;
- preflight validation;
- qREST binary execution;
- artifact creation;
- final status classification.

If a model returns invalid tool arguments, unknown paths, unsupported field paths, or guessed engineering values, the coordinator should reject the output and ask a clarifying question.

## Out of Scope for This Phase

- Fully autonomous multi-step planning across all qREST workflows.
- Algorithm configuration for IM, EDP, OMA, or RR.
- Replacing the metadata extraction pipeline.
- Letting the model directly edit final metadata.
- Browser redesign beyond showing new artifacts and summaries.

## Migration Notes

This phase should be implemented additively:

- keep existing `/generate-qrest` and `/load-qrest` commands working;
- keep current API tool execution contracts stable where possible;
- add the new agentic route beside existing command routes;
- reuse `QrestDataTools` rather than rewriting qREST conversion logic;
- preserve deterministic validation as the readiness boundary.

## Follow-Up Work

1. Promote metadata acquisition into its own skill handler so it is no longer only a fallback extraction path.
2. Add `qrest_algorithm_configuration` as the first Stage 2 skill target.
3. Consider a `qrest_data_diagnosis` skill for mismatch investigation without generation/loading side effects.
4. Add richer Web task-log inspection if users need to inspect previous tool arguments and reports.
