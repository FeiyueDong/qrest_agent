# Success: Generated Artifact

User request:

```text
用 metadata.json 和 data.txt 生成 output.qrest。
```

Expected behavior:

- run `preflight_generate_qrest`;
- run `generate_qrest` if preflight has no hard errors;
- report the `.qrest` artifact path;
- include preflight warnings when present;
- say the input is fully consistent only when there are no warnings.

