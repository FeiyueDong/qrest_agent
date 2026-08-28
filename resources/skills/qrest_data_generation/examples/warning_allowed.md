# Warning: Generation Allowed

User request:

```text
检查 metadata.json 和 data.txt 能不能生成 qREST。
```

Expected behavior:

- run `preflight_generate_qrest`;
- report `ready=true` when there are no hard errors;
- list warnings such as `DataInfo.NPTS` not matching the actual row count;
- say generation is allowed but the inputs are not fully consistent.

