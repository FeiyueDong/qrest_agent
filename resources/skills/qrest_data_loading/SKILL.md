# qREST Data Loading Skill

Use this skill when the user wants to inspect, parse, load, convert, or import an existing `.qrest` file.

## Applies When

- The user asks to parse or load a `.qrest` file.
- The user asks to extract metadata JSON and readable TXT data from `.qrest`.
- The user asks to import the parsed metadata into the current qREST Agent session.
- The user asks to compare the loaded metadata with a reference metadata JSON.

## Required Inputs

- Input `.qrest` path.
- Optional reference metadata JSON path for comparison.
- Session-managed output paths for:
  - `loaded_metadata.json`
  - `loaded_data.txt`
  - `load_qrest_result.json`
  - `qrest_data_loading_task_log.json`

## Forbidden Behavior

- Do not guess the input `.qrest` path.
- Do not claim imported metadata is ready unless deterministic validation says so.
- Do not hide metadata comparison warnings.
- Do not overwrite confirmed user state except through the existing candidate merge rules.

## Workflow

1. Identify the input `.qrest` path.
2. Identify optional reference metadata JSON for comparison.
3. Run `load_qrest`.
4. If loading succeeds, import `loaded_metadata.json` into the current session through the existing ingestion/extraction path.
5. Summarize loaded artifacts, metadata readiness, warnings, and comparison differences.
6. Write a task log.

## Tool Policy

- First choice: `load_qrest`.
- Use `generate_qrest` only for generation requests, not loading requests.
- Treat the deterministic loader result as authoritative.

