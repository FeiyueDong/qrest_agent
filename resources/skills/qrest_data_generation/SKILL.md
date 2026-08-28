# qREST Data Generation Skill

Use this skill when the user wants to generate, preflight, or diagnose a qREST data artifact from metadata and time-series data.

## Applies When

- The user asks to generate a `.qrest` file.
- The user asks whether metadata and `data.txt` can be used to generate qREST data.
- The user asks to use the current session metadata together with a data file.
- The user asks to run strict generation or to stop on any inconsistency.

## Required Inputs

- Metadata source:
  - an explicit metadata JSON path, or
  - the current session metadata exported through the deterministic metadata export policy.
- Data source:
  - an explicit time-major text data path.
- Output target:
  - an explicit `.qrest` output path, or
  - a session-managed artifact path.
- Strict mode:
  - default `false`;
  - use `true` when the user asks to stop on warnings or inconsistencies.

## Forbidden Behavior

- Do not invent missing engineering metadata.
- Do not guess file paths.
- Do not infer channel counts, sample counts, sampling intervals, or sensor layouts without evidence.
- Do not generate when mandatory metadata validation fails.
- Do not hide preflight warnings just because the binary generation command succeeds.
- Do not say the input is fully consistent unless preflight has no warnings.

## Workflow

1. Identify whether the user wants preflight only or actual generation.
2. Resolve metadata:
   - use an explicit metadata path when supplied;
   - otherwise export current session metadata through the weighted export policy;
   - stop if export is blocked.
3. Resolve data TXT path:
   - use an explicit path when supplied;
   - ask the user for the path when absent.
4. Run `preflight_generate_qrest`.
5. If preflight has errors, report blocking issues and stop.
6. If the user requested preflight only, summarize warnings and stop.
7. Run `generate_qrest` with strict mode if requested.
8. Summarize generated artifacts, warnings, errors, and whether generation was fully consistent.

## Tool Policy

- First choice for readiness checks: `preflight_generate_qrest`.
- First choice for binary generation: `generate_qrest`.
- Use `load_qrest` only when the user provides an existing `.qrest` file to inspect or convert.
- Treat deterministic tool output as authoritative over model wording.

## Response Guidance

Successful generation with warnings:

- say that the `.qrest` artifact was generated;
- list important warnings;
- clearly say that the source metadata/data are not fully consistent.

Blocked generation:

- say that generation was blocked;
- list the exact metadata field or data issue;
- ask only for missing evidence that is required to proceed.

Preflight-only result:

- say whether generation is currently allowed;
- distinguish hard errors from warnings;
- do not create a `.qrest` artifact unless explicitly requested.

