# Metadata 规范化与智能推导能力改进 — 进度记录

依据：`docs/qrest-agent Metadata 规范化与智能推导能力改进方案.md`。
状态：两个问题均已完成，全量测试 173 passed（新增 14 项专项测试）。

## 问题一：Metadata 中文字符串 → Canonicalization Layer（§2-§4）

- 新增 `src/qrest_agent/core/canonicalize.py`：
  - `CONTROLLED_VOCABULARY`：StructuralType（钢框架→SteelFrame、钢筋混凝土框架→RCFrame、
    剪力墙→ShearWall、砌体→Masonry）、Shape（矩形→Rectangular、圆形→Circular）、
    Measurand（加速度→Acceleration…）、Corrected（yes/NULL）；
  - `canonicalize_value(field_path, value)`：受控字段确定性中文→英文映射（mapped）；
    自由字段（ProjectName/Provider/EventName/ChannelID）含中文 → failed（不创造名称，§3.2）；
    dict/list 递归处理（Channels[i].Measurand 等）；
  - `metadata_string_errors(metadata)`：确定性 ASCII + 受控值检查（§4）。
- 调用链：LLM 候选 → `canonicalize_value`（agent 层）：
  - mapped → 替换 value 后进 Schema Gate / Working State；
  - failed → 降级 uncertain（保留证据，不进最终 Metadata，UI 可见待确认）；
- Validator `_validate_schema` 与 Exporter Final Gate 都执行 `metadata_string_errors`
  （`json.dumps(ensure_ascii=True)` 不能代替语义规范化，§4）。
- CLI `/confirm` 同样规范化：受控字段中文 → 标准值；自由字段中文 → 拒绝并提示。

## 问题二：复杂字段推导 → Intermediate Facts + Derivation Pass（§5-§15）

- **WorkingState facts namespace**（§6-§7）：`_facts` 与 metadata 同库；
  `set_fact/submit_fact/get_fact/facts/fact_paths/to_facts_dict`；facts 有
  value/status/evidence，**永不导出**，不参与 schema gate 与 validator。
- **Extractor**（§6）：LLM 输出 `{"candidates": [...], "facts": [...]}`；
  facts 路径约定 `Building.*` / `Monitoring.*`（FACT_PREFIXES）；facts 同样
  必须带可验证证据；跨 chunk 逐段提取后在 Working State 聚合（§13）。
- **Derivation Pass**（§8-§10）：`_apply_derivation_tools` 扩展为四段：
  1. StructuralFootprint：Shape=Rectangular + `Building.footprint_length/width` facts
     → Parameters（derived，tool=derive_footprint）→ calculate_bounding_box → BoundingBox；
     无形状描述时绝不假设矩形（Accuracy First）；
  2. Elevation：`above_ground_floors/basement_floors/first_floor_height/
     typical_story_height`（+可选地下层高）facts 齐全 → derive_elevation_profile
     → Elevation（derived，tool 证据 + derived_from facts）→ ElevationNum=len（既有 counts）；
     层高不足 → 保持 missing，不按经验补；
  3. 数组计数（ElevationNum/ChannelNum）；4. Frequency。
- **Channels**（§11）：情况 A 完整通道表（table_reader/逐行提取）可用；情况 C
  只有数量 → ChannelNum 确认、Channels missing；无注册模板 → 不生成。
- **Skill 一致性**（§12）：instrument_info 与 sensor_layout 删除 derive_channel_layout
  残留说明，明确“当前没有注册的通道布置模板 Tool”。

## Prompt 更新（§3/§6/§76）

EXTRACTION_SYSTEM_PROMPT：
- JSON 形状增加 `facts` 数组（Building./Monitoring. 前缀、必带证据、永不导出）；
- 受控字段标准值清单（StructuralType/Shape/Measurand/Corrected）；
- 自由字段规则：只用资料中的 ASCII 标识，中文不创造英文名（uncertain/省略）。

## 测试（§16，14 项）

tests/test_normalization_derivation.py：
- ASCII：canonicalize 受控中文→英文；自由中文→failed；metadata_string_errors；
  agent 层 LLM 输出“钢框架”→ SteelFrame；中文 ProjectName → uncertain 不进 metadata；
  exporter 拦截非 ASCII；/confirm 规范化与拒绝。
- StructuralFootprint：facts→Parameters+BoundingBox（含 evidence.tool 断言）；
  无形状描述不推导。
- Elevation：facts→Elevation[-2.7,0.0,...,47.4]+ElevationNum=16；跨 chunk（两个文件）
  聚合推导；层高缺失保持 missing。
- Channels：只有数量 → ChannelNum 进、Channels missing；facts 永不进 metadata。
