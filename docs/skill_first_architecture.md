# Skill-First qREST Agent Architecture

This document describes the current skill-first architecture used by qREST Agent and how to extend it with new qREST workflows.

## Current Shape

qREST Agent now treats natural-language qREST tasks as the primary user path. Low-level commands such as `/load-qrest` and `/generate-qrest` remain available for debugging and scripted smoke runs, but user-facing workflows should be implemented as repo-native skills plus skill handlers.

Runtime flow:

```text
User message
  |
  v
ChatSession
  |
  v
TaskCoordinator
  |
  v
TaskHandlerRegistry
  |
  v
Skill handler
  |
  +-- SkillRegistry reads resources/skills/<skill-name>/SKILL.md
  +-- ToolRegistry executes deterministic tools
  +-- MetadataAgent updates audited state when needed
  +-- ArtifactManager writes reports and task logs
```

## Main Modules

- `qrest_agent.agent.dialogue.ChatSession`
  - owns dialogue turns, command routing, state-correction actions, and user-facing responses;
  - calls `TaskCoordinator` before falling back to metadata extraction;
  - exposes `skills`, `skill_handlers`, and `task_logs` in `to_dict()` for API and Web UI.

- `qrest_agent.agent.tasks.TaskCoordinator`
  - detects task-level intent;
  - selects a handler from `TaskHandlerRegistry`;
  - does not contain workflow-specific execution logic.

- `qrest_agent.agent.task_models`
  - defines `TaskIntent` and `TaskExecutionResult`.

- `qrest_agent.agent.task_handlers`
  - defines `TaskHandler`, `TaskHandlerRegistry`, and concrete workflow handlers;
  - currently includes `QrestDataGenerationHandler` and `QrestDataLoadingHandler`.

- `qrest_agent.skills.SkillRegistry`
  - discovers repo-native skills under `resources/skills`;
  - loads `SKILL.md` and optional `tool_policy.json`.

- `qrest_agent.agent.tool_registry.ToolRegistry`
  - exposes deterministic tools such as `preflight_generate_qrest`, `generate_qrest`, and `load_qrest`;
  - writes standard tool artifacts for session-scoped calls.

## Current Skills

### `qrest_data_generation`

Location:

```text
resources/skills/qrest_data_generation/
```

Natural-language examples:

- `检查 metadata.json 和 data.txt 能不能生成 qREST`
- `用当前项目状态和 data.txt 直接生成 qREST`
- `严格检查 metadata.json 和 data.txt 能不能生成 qREST`

Handler:

```text
QrestDataGenerationHandler
```

Deterministic tools:

- `preflight_generate_qrest`
- `generate_qrest`

Artifacts:

- `metadata.json` when exported from current session state;
- `metadata_export_report.json`;
- `generate_qrest_preflight_report.json`;
- `generate_qrest_result.json`;
- `generated.qrest`;
- `qrest_data_generation_task_log.json`.

### `qrest_data_loading`

Location:

```text
resources/skills/qrest_data_loading/
```

Natural-language examples:

- `解析 demo.qrest 并导入当前项目`
- `加载 input.qrest 并对比 metadata.json`

Handler:

```text
QrestDataLoadingHandler
```

Deterministic tool:

- `load_qrest`

Artifacts:

- `loaded_metadata.json`;
- `loaded_data.txt`;
- `load_qrest_result.json`;
- `qrest_data_loading_task_log.json`.

## Readiness Boundary

The AI or local model must not decide engineering readiness by itself.

Hard boundaries:

- final metadata readiness is decided by deterministic validation and export policy;
- qREST generation readiness is decided by `preflight_generate_qrest`;
- qREST file loading is decided by `load_qrest`;
- missing engineering values are reported and requested, not invented;
- warnings are surfaced even when a tool command succeeds.

## Web And CLI Surface

CLI:

- `/help` starts with natural-language task examples;
- `/tools` lists repo-native skills, registered skill handlers, deterministic tools, and low-level shortcut commands.

Web:

- the composer placeholder uses natural-language task examples;
- the side panel shows available skills, handler counts, and recent task log artifacts;
- `GET /api/session` returns `skills`, `skill_handlers`, and `task_logs`.

## Adding A New Skill Handler

Use this checklist when adding a new qREST workflow such as algorithm configuration.

1. Add a skill directory:

```text
resources/skills/<skill_name>/
  SKILL.md
  tool_policy.json
```

2. Define the user-facing workflow in `SKILL.md`:

- when it applies;
- required and optional inputs;
- forbidden behavior;
- deterministic tools to call;
- output artifacts;
- response expectations.

3. Extend `TaskIntent` only if the workflow needs new structured fields.

4. Add an intent parser in `qrest_agent.agent.tasks`.

5. Implement a concrete handler in `qrest_agent.agent.task_handlers`.

6. Register the handler in `create_default_handler_registry()`.

7. Add tests:

- intent detection;
- default handler registration;
- successful natural-language task execution;
- blocked input path;
- artifact and task-log creation;
- dialogue/API/Web smoke coverage if user-facing behavior changes.

8. Run validation:

```bash
.venv/bin/python -m pytest
git diff --check
```

## Next Candidate Workflows

- `qrest_metadata_acquisition`: make metadata collection itself a skill-first workflow instead of only fallback extraction.
- `qrest_algorithm_configuration`: fill the reserved `analysis` section after metadata validation.
- `qrest_data_diagnosis`: inspect metadata/data mismatches without generating or loading artifacts.

