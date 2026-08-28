# qrest-agent Metadata 规范化与智能推导能力改进方案

## 1. 本轮目标

当前版本已经解决了 `Channels = 18` 这类结构非法数据进入 Metadata 的问题，Schema Contract 应继续保留。

本轮需要进一步解决两个问题：

1. **Metadata 字符串值必须保持英文 ASCII 形式，不能直接写入中文；**
2. **恢复 Agent 根据间接工程信息推导复杂字段的能力，重点包括 `StructuralFootprint`、`Elevation` 和 `Channels`。**

目标是同时实现：

> **结构严格、内容规范、能够推导。**

---

# 2. 问题一：Metadata 中出现中文值

## 2.1 当前问题

目前 Schema 主要检查：

```text
string / number / array / object
```

因此：

```text
StructuralType = "钢框架"
```

虽然不符合 qREST Metadata 的约定，但仍然是合法 `string`，能够通过 Schema Gate。

类似问题还可能出现在：

```text
ProjectName
StructuralType
Shape
Provider
ChannelID
Measurand
DeviceType
EventName
Corrected
```

等字符串字段。

---

## 2.2 基本原则

正式 qREST Metadata：

> **仅允许 ASCII 字符。**

自然语言输入可以是中文，但保存到 Metadata 时必须转换成 qREST 约定的英文/ASCII 表达。

例如：

```text
资料：
钢框架结构

Metadata：
StructuralType = "SteelFrame"
```

而不是：

```text
StructuralType = "钢框架"
```

---

# 3. 增加 Canonicalization Layer

建议在：

```text
Extraction
↓
Canonicalization
↓
Schema Gate
↓
Working State
```

之间增加统一规范化步骤。

其职责是：

```text
自然语言值
→ qREST canonical value
```

---

## 3.1 对受控字段建立标准词汇

例如：

```text
StructuralType
SteelFrame
RCFrame
ShearWall
Masonry
...

Shape
Rectangular
Circular
Polygon

Measurand
Acceleration
Velocity
Displacement
```

允许模型理解：

```text
钢框架
钢筋混凝土框架
剪力墙
加速度
矩形
```

但最终值统一映射为英文标准值。

---

## 3.2 自由字符串不要随意翻译

对于：

```text
ProjectName
Provider
EventName
ChannelID
```

如果资料已经提供英文/ASCII 标识，则直接使用。

如果只有中文名称，不应让模型自行创造一个“看起来合理”的英文名称。

可以：

```text
保持 missing / uncertain
```

或者向用户询问 ASCII 标识。

原则：

> **规范化可以做确定性映射，但不能凭空创建新的项目名称。**

---

# 4. ASCII 应成为确定性约束

Schema/Validator 应增加字符串检查。

正式可导出的 Metadata 中：

```text
所有 string
```

必须满足：

```text
ASCII only
```

如果：

```text
StructuralType = "钢框架"
```

则：

```text
canonicalization 尝试映射
↓
成功 → SteelFrame
失败 → reject / uncertain
```

最终 Exporter 再做一次 ASCII 检查。

不要仅依赖：

```python
json.dumps(..., ensure_ascii=True)
```

因为这只能改变 JSON 编码方式，并没有把中文语义转换成英文。

---

# 5. 问题二：复杂字段推导能力明显下降

目前：

```text
StructuralFootprint
Elevation
Channels
```

在资料没有直接给出最终 Metadata 结构时，Agent 很难生成结果。

例如资料：

```text
地上14层，地下2层；
首层4.5m；
其余地上楼层3.3m。
```

实际上已经足以计算 `Elevation`。

但目前 Extractor 只能输出正式 Metadata 字段，无法保存：

```text
above_ground_floors
basement_floors
first_floor_height
typical_story_height
```

这些“中间事实”。

因此信息虽然被模型读到了，却无法继续传给：

```text
derive_elevation_profile
```

等 Tool。

---

# 6. 增加 Intermediate Facts

建议允许 Extraction 同时产生两类信息：

```text
Metadata Candidates
+
Intermediate Facts
```

例如：

```json
{
  "facts": {
    "Building.above_ground_floors": 14,
    "Building.basement_floors": 2,
    "Building.first_floor_height": 4.5,
    "Building.typical_story_height": 3.3
  }
}
```

每个 Fact 同样需要：

```text
value
status
evidence
```

但：

> **Intermediate Facts 永远不能直接导出为 Metadata。**

---

# 7. Working State 增加 Facts Namespace

不建议建立第二套独立状态系统。

继续使用一个 Working State：

```text
WorkingState
├─ metadata
│  ├─ BuildingInfo...
│  ├─ InstrumentInfo...
│  └─ DataInfo...
│
└─ facts
   ├─ Building.above_ground_floors
   ├─ Building.typical_story_height
   ├─ Building.footprint_length
   ├─ Monitoring.monitored_floors
   ├─ Monitoring.per_floor_sensor_count
   └─ ...
```

Metadata 是最终结果。

Facts 是 Agent 推理过程中的可信中间信息。

---

# 8. 增加 Derivation Pass

当前流程：

```text
extract
→ Working State
→ 简单 derivation
→ validate
```

建议调整为：

```text
extract metadata + facts
↓
merge Working State
↓
Derivation Pass
↓
Tools
↓
Derived Metadata Candidates
↓
Canonicalization
↓
Schema Gate
↓
Validator
```

Derivation Pass 根据：

```text
当前缺失字段
+
已有可信 Facts
+
Skill
+
可用 Tool
```

判断哪些字段可以确定性生成。

---

# 9. StructuralFootprint 推导

例如资料：

```text
建筑平面呈矩形，尺寸约42m × 25.2m。
```

首先提取：

```text
Shape = Rectangular

facts:
footprint_length = 42
footprint_width = 25.2
```

然后生成：

```json
Parameters = {
  "Length": 42,
  "Width": 25.2
}
```

再调用：

```text
calculate_bounding_box
```

得到：

```json
BoundingBox = {
  "MaxX": 21,
  "MinX": -21,
  "MaxY": 12.6,
  "MinY": -12.6
}
```

这是确定性推导，应自动完成。

---

# 10. Elevation 推导

当 Facts 已包含：

```text
above_ground_floors
basement_floors
first_floor_height
typical_story_height
必要的地下层高
```

即可调用：

```text
derive_elevation_profile
```

生成完整：

```text
BuildingInfo.Elevation
```

随后：

```text
ElevationNum = len(Elevation)
```

继续由确定性 Tool 推导。

如果层高信息不足：

```text
Elevation 保持 missing
```

不能按经验补充。

---

# 11. Channels 推导

Channels 应分三种情况处理。

### 情况 A：资料存在完整通道表

优先：

```text
table_reader
→ Channels
→ ChannelNum
```

这是最可靠路径。

### 情况 B：资料提供了完整位置、方向等布置信息

先提取：

```text
monitored_floors
sensor coordinates
azimuth
scale
device type
...
```

然后确定性组合成 Channels。

### 情况 C：只有模糊描述

例如：

```text
每层三个传感器，左右和中间布置
```

如果没有足够信息确定：

```text
LocationXYZ
Azimuth
Scale
```

则不能直接生成完整 Channels。

只有 qREST 明确定义了某个标准布置模板时，才能：

```text
layout_template_id
→ deterministic layout tool
```

否则继续询问用户。

---

# 12. 修正当前 Skill / Tool 不一致

目前 `instrument_info` Skill 仍提到：

```text
derive_channel_layout
```

但正式 ToolRegistry 已没有对应 Tool。

本轮应统一：

- 如果该能力不再使用：删除 Skill 中的说明；
- 如果存在正式 qREST 标准布置模板：重新设计并注册明确的模板 Tool；
- 禁止恢复旧版中未经明确约定的坐标假设。

Skill 描述必须与真实 Tool 能力一致。

---

# 13. 增加跨 Chunk Fact Aggregation

当前逐 chunk Extraction 对复杂文档不够。

例如：

```text
段落1：地上14层、地下2层
段落5：首层4.5m
段落8：标准层3.3m
```

单独看任何一个 chunk 都无法计算 Elevation。

因此应采用：

```text
Chunk 1 → Facts
Chunk 2 → Facts
Chunk 3 → Facts
        ↓
Source-level Fact Aggregation
        ↓
Derivation Pass
```

不要求模型一次读取整个文档，但要允许多个 chunk 的可信 Facts 在 Working State 中组合。

---

# 14. 不恢复旧版项目专用正则

早期版本能够生成这些复杂字段，是因为存在：

```text
cross-chunk regex
elevation parser
channel layout generator
```

这些能力可以作为行为参考，但不建议直接恢复。

本轮目标应该是：

```text
LLM 提取语义事实
+
Working State 聚合
+
Skill 判断是否可推导
+
Tool 确定性计算
```

而不是重新把语义判断写死在 Python 正则中。

---

# 15. 建议修改后的核心流程

最终建议：

```text
Natural Language / Files
        ↓
Semantic Extraction
     ↙        ↘
Metadata     Intermediate
Candidates      Facts
     │           │
     └─────┬─────┘
           ↓
     Working State
           ↓
     Derivation Pass
           ↓
   Deterministic Tools
           ↓
   Derived Candidates
           ↓
    Canonicalization
           ↓
      Schema Gate
           ↓
       Validator
           ↓
        Metadata
```

---

# 16. 测试重点

至少增加以下回归测试。

### ASCII

输入：

```text
结构为钢框架。
```

应得到：

```text
StructuralType = "SteelFrame"
```

最终 Metadata 不允许出现中文字符串。

### StructuralFootprint

输入：

```text
矩形平面，尺寸42m × 25.2m。
```

应自动得到：

```text
Shape
Parameters
BoundingBox
```

### Elevation

输入：

```text
地上14层、地下2层，首层4.5m，标准层3.3m，并提供地下层高。
```

应自动生成：

```text
Elevation
ElevationNum
```

### Cross-chunk

将上述层数和层高拆到不同段落，结果仍应一致。

### Channels

完整通道表：

```text
→ 自动生成 Channels
```

只有：

```text
共有18个传感器
```

则：

```text
ChannelNum = 18
Channels = missing
```

不得伪造 Channels。

---

# 17. 本轮完成标准

完成后应保证：

1. 最终 Metadata 所有字符串均为合法 ASCII；
2. 常见受控字段自动转换为 qREST 标准英文值；
3. 不对 ProjectName 等自由字段随意翻译或创造名称；
4. Agent 可以保存并组合有证据的 Intermediate Facts；
5. StructuralFootprint 可以根据尺寸信息自动生成；
6. Elevation 可以根据层数和层高自动生成；
7. Channels 在信息充分时可以自动构造，信息不足时保持 missing；
8. 跨段落信息可以共同参与推导；
9. Schema Gate 继续保持严格，不因增强智能推导而放宽；
10. 不恢复大量项目专用 Regex 和隐藏工程假设。

---

# 18. 最终原则

本轮希望进一步形成：

> **LLM 负责理解资料中“有什么信息”。**

> **Intermediate Facts 保存那些暂时不能直接写入 Metadata、但后续有用的可信事实。**

> **Skill 负责判断“这些事实可以推导什么”。**

> **Tool 负责真正计算。**

> **Canonicalization 保证 Metadata 使用统一英文 ASCII 表达。**

> **Schema Gate 与 Validator 继续保证结果绝不会因为“更智能”而降低准确性。**

最终目标不是在“准确”与“智能”之间二选一，而是：

> **先保证数据契约绝对可靠，再让 Agent 利用已有可信事实尽可能主动完成能够确定的推导。**