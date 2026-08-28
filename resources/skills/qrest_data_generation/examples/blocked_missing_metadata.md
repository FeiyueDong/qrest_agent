# Blocked: Missing Metadata

User request:

```text
用当前项目状态和 data.txt 生成 qREST 数据。
```

Expected behavior:

- export current session metadata through the deterministic export policy;
- stop if mandatory fields are missing;
- report exact blocked fields;
- ask the user for the missing engineering information.

Do not fill missing fields from guesses.

