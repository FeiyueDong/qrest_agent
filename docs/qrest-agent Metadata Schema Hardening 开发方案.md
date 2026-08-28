# qrest-agent Metadata Schema Hardening 开发方案

## 1. 本轮工作的背景

近期测试中发现一个严重问题：

```text
InstrumentInfo.Channels = 18
```

其中 `Channels` 本应是：

```text
array<object>
```

却被读取成了一个单纯整数。

而正确的数字字段实际上应该是：

```text
InstrumentInfo.ChannelNum = 18
```

这类问题属于严重的数据结构错误。

它比普通的数值误差、字段遗漏更加严重，因为它意味着：

> Agent 不仅可能理解错信息，还可能完全破坏 qREST Metadata 约定的数据结构。

如果系统连字段的基本类型和结构都不能保证，那么：

```text
Evidence
Confidence
Skill
Agent Planning
自然语言交互
```

这些高级能力都失去了可靠的数据基础。

因此，本轮开发应把：

> **Metadata 准确性与数据结构合法性**

放到最高优先级。

---

# 2. 本轮工作的核心目标

本轮不以“提高 LLM 提取效果”为第一目标，而应建立一个更加严格的原则：

> **LLM 可以理解错误，但系统不能允许结构错误的数据进入正式状态。**

目标结构：

```text
LLM / Tool / Import
        ↓
    Candidate
        ↓
   Schema Gate
        ↓
   Working State
        ↓
    Validator
        ↓
   Metadata Export
```

其中：

```text
Schema Gate
Validator
Exporter
```

均必须是确定性代码。

LLM 只负责：

```text
理解语义
发现候选信息
选择字段
生成 Candidate
```

不能负责保证最终数据结构正确。

---

# 3. 当前问题的本质

目前项目中实际上已经存在 Metadata Schema。

例如：

```text
InstrumentInfo.ChannelNum
```

定义为：

```text
integer
```

而：

```text
InstrumentInfo.Channels
```

定义为：

```text
array
```

完整 qREST Schema 甚至进一步规定：

```text
Channels
└─ array
   └─ object
      ├─ ChannelNo: integer
      ├─ ChannelID: string
      ├─ Measurand: string
      ├─ Scale: number
      ├─ Azimuth: number
      └─ LocationXYZ: array[number, number, number]
```

问题不在于系统“不知道正确结构”。

问题在于：

> **这些 Schema 目前没有成为 Candidate → WorkingState → Export 全链路中的强制约束。**

---

# 4. 当前错误形成路径

当前可能出现：

```text
文档：
“系统共布置18个传感器”
        ↓
LLM 理解
        ↓
错误输出：
InstrumentInfo.Channels = 18
        ↓
Candidate
        ↓
没有强类型检查
        ↓
Working State
        ↓
继续接受
        ↓
Validator
        ↓
Channels 不是 list → 直接跳过
        ↓
错误值继续保留
```

真正需要解决的不是：

> “怎样保证 LLM 永远不把 Channels 和 ChannelNum 搞混？”

这是无法完全保证的。

真正应该保证的是：

> **即使 LLM 搞混了，错误也必须在进入 Working State 之前被拦截。**

---

# 5. 本轮设计原则

## 5.1 Accuracy First

本轮所有设计决策优先考虑：

```text
正确
>
智能
>
方便
```

宁可：

```text
拒绝一个不确定 Candidate
要求用户补充
重新抽取
```

也不要：

```text
自动接受一个结构不合法的值
```

---

## 5.2 Fail Closed

当字段值无法证明满足 Schema 时：

```text
默认拒绝
```

而不是：

```text
默认接受
```

例如：

```text
Channels = 18
```

必须：

```text
INVALID
```

不能因为：

```text
有 Evidence
Confidence 很高
LLM 很确定
```

就允许进入 Working State。

---

## 5.3 Schema 优先于 LLM

当：

```text
LLM output
```

与：

```text
Metadata Schema
```

冲突时：

```text
Schema 永远优先
```

例如：

```text
LLM:
Channels = 18
```

Schema：

```text
Channels must be array
```

最终结果必须是：

```text
Candidate rejected
```

而不是尝试迁就模型输出。

---

# 6. 建立统一 Metadata Schema Contract

本轮最重要的架构调整，是建立统一的：

```text
Metadata Schema Contract
```

它应成为以下模块的共同依据：

```text
Extraction
Candidate Validation
Working State
Validator
Exporter
Web UI
Tests
```

不能再由每层自行理解字段结构。

---

# 7. Schema 的权威来源

当前项目存在：

```text
core/schema.py
```

以及：

```text
resources/qrest_data/schema/metadata_schema.json
```

后者包含更加完整的嵌套结构约束。

建议本轮明确：

> **完整 JSON Schema 是 Metadata 数据结构的最终权威来源。**

例如：

```text
resources/qrest_data/schema/metadata_schema.json
```

负责：

```text
type
array items
object properties
required nested fields
基本数据形状
```

而：

```text
FieldSpec
```

继续负责 Agent 层附加信息：

```text
description
importance
unit_role
allow_derived
agent policy
```

避免重复定义类型规则。

---

# 8. 避免多份独立 Schema

不建议继续维护：

```text
schema.py 中一份类型
JSON Schema 一份类型
Validator 手写一份类型
Prompt 再描述一份类型
```

否则以后很容易不一致。

目标应为：

```text
metadata_schema.json
        ↓
Schema utilities
        ├─ Candidate validation
        ├─ Validator
        ├─ Extraction schema context
        └─ Export validation
```

---

# 9. 第一层防线：Extraction Schema Context

LLM 在 Extraction 时不能只看到：

```text
InstrumentInfo.ChannelNum
InstrumentInfo.Channels
```

这样的字段名字。

必须同时看到字段结构。

例如：

```json
{
  "field_path": "InstrumentInfo.ChannelNum",
  "type": "integer",
  "description": "number of monitoring channels"
}
```

以及：

```json
{
  "field_path": "InstrumentInfo.Channels",
  "type": "array",
  "description": "full monitoring channel configuration",
  "items": {
    "type": "object",
    "required": [
      "ChannelNo",
      "ChannelID",
      "Measurand",
      "Scale",
      "Azimuth",
      "LocationXYZ"
    ]
  }
}
```

---

# 10. Prompt 中增加明确的字段区分

特别对于容易混淆的字段，应加入明确说明。

例如：

```text
InstrumentInfo.ChannelNum:
- integer
- 表示通道总数量

InstrumentInfo.Channels:
- array of channel objects
- 表示完整通道配置
- 绝对不能用一个整数代替
```

再增加例子：

```text
Source:
“系统共布置18个传感器”

Valid:
InstrumentInfo.ChannelNum = 18

Invalid:
InstrumentInfo.Channels = 18
```

类似规则还可以用于：

```text
ElevationNum vs Elevation
ChannelNum vs Channels
```

---

# 11. 不应完全依赖 Prompt

即使 Prompt 写得再明确，也不能认为问题已经解决。

Prompt 只是：

```text
第一层软约束
```

真正的安全边界必须在代码中。

---

# 12. 第二层防线：Candidate Schema Gate

所有 Candidate 在进入 Working State 前必须执行：

```text
validate_candidate_shape()
```

例如：

```python
validate_candidate_shape(
    field_path,
    value
)
```

返回：

```text
valid
```

或：

```text
invalid
expected_type
actual_type
reason
```

---

# 13. 基础类型规则

统一检查：

```text
string
→ str

integer
→ int
→ bool 不算 integer

number
→ int / float
→ bool 不算 number

array
→ list

object
→ dict
```

---

# 14. 示例：Channels=18

输入：

```python
field_path = "InstrumentInfo.Channels"
value = 18
```

结果：

```text
valid = false

reason:
expected array, got integer
```

此 Candidate：

```text
不得进入 Working State
```

---

# 15. 示例：ChannelNum=[...]

输入：

```python
field_path = "InstrumentInfo.ChannelNum"
value = [...]
```

结果同样：

```text
reject
```

---

# 16. 示例：Elevation=16

错误：

```text
BuildingInfo.Elevation = 16
```

必须：

```text
reject
```

正确应该是：

```text
BuildingInfo.ElevationNum = 16
```

但系统不要静默自动修改字段。

---

# 17. 复杂字段必须做深层结构校验

对于：

```text
array
object
```

仅检查最外层类型是不够的。

例如：

```text
Channels = [1, 2, 3]
```

虽然是 list，但仍然非法。

必须继续检查：

```text
item type = object
```

---

# 18. Channels 深层检查

至少要求：

```text
Channels
→ list

每个 Channel
→ dict
```

并检查必要键：

```text
ChannelNo
ChannelID
Measurand
Scale
Azimuth
LocationXYZ
```

基本类型：

```text
ChannelNo      integer
ChannelID      string
Measurand      string
Scale          number
Azimuth        number
LocationXYZ    array length 3
```

---

# 19. Candidate Gate 不负责完整工程一致性

需要区分：

### Candidate Schema Gate

负责：

```text
数据类型
基本形状
嵌套结构
```

### Validator

负责：

```text
工程一致性
跨字段关系
范围
完整性
```

例如：

```text
Channels = [...]
```

结构合法后可以进入 Working State。

但是：

```text
ChannelNum != len(Channels)
```

由 Validator 报错。

---

# 20. Invalid Candidate 的处理

错误 Candidate 不应：

```text
直接丢弃且无记录
```

建议保留诊断结果。

例如：

```json
{
  "field_path": "InstrumentInfo.Channels",
  "value": 18,
  "rejected": true,
  "reason": "expected array, got integer",
  "source": "LLM"
}
```

用于：

```text
调试
UI
日志
自动重试
```

但不能进入 Working State。

---

# 21. 第三层防线：Working State 强制 Schema

即使 Candidate Gate 出现 bug：

```text
WorkingState
```

也不能接受非法值。

因此：

```python
WorkingState.submit()
WorkingState.set()
WorkingState.update()
WorkingState.confirm()
WorkingState.derive()
```

只要写入 tracked Metadata Field，就应该进行基本 Schema 检查。

---

# 22. Working State 的原则

Working State 应满足：

> **只保存结构上合法的事实或合法形状的待确认值。**

不能出现：

```text
FieldState(
    field_path="InstrumentInfo.Channels",
    value=18
)
```

这种状态。

---

# 23. Working State 写入失败

建议行为：

```text
raise / reject
```

并返回结构化错误：

```text
SchemaViolation
```

例如：

```json
{
  "field_path": "InstrumentInfo.Channels",
  "expected": "array",
  "actual": "integer"
}
```

---

# 24. confirmed 也不能绕过 Schema

即使用户明确说：

```text
“Channels 就是18”
```

也不能因为：

```text
status = confirmed
```

就跳过结构检查。

因为：

```text
confirmed
```

只表示：

> 用户确认这个事实来源。

并不意味着：

> 数据结构自动合法。

因此：

```text
confirmed ≠ schema bypass
```

---

# 25. derived 同样不能绕过 Schema

Tool 或确定性推导也必须满足目标字段结构。

例如 Tool 返回：

```text
Channels = 18
```

同样必须被拒绝。

不能假设：

```text
Tool = 永远正确
```

---

# 26. 第四层防线：Validator 完整结构校验

当前 Validator 必须加强。

特别禁止：

```python
if not isinstance(channels, list):
    return
```

这种逻辑。

正确行为：

```python
if not isinstance(channels, list):
    issues.append(
        ValidationIssue(
            "error",
            "InstrumentInfo.Channels",
            "Channels must be an array"
        )
    )
    return
```

---

# 27. 但不要只修 Channels

本轮应统一处理所有 Metadata 字段。

先执行：

```text
Generic Schema Validation
```

再执行：

```text
Domain Validation
```

---

# 28. Generic Schema Validation

负责：

```text
required
type
array shape
object structure
nested required keys
```

可以直接基于：

```text
metadata_schema.json
```

---

# 29. Domain Validation

继续负责 qREST 工程约束，例如：

```text
ChannelNum == len(Channels)

ElevationNum == len(Elevation)

ChannelNo 从1连续增加

Azimuth = -1
或
0 <= Azimuth <= 360

LocationXYZ 长度必须为3

NPTS > 0

DT > 0

BoundingBox Max > Min
```

---

# 30. Validator 结果原则

只要存在任何：

```text
Schema error
```

则：

```text
ready = false
```

无论：

```text
所有 required 字段是否都有 value
```

都不能 ready。

---

# 31. 非法结构不能视作“已知”

例如：

```text
Channels = 18
```

当前如果只是：

```text
value != null
```

就可能被视为已知。

本轮应保证：

```text
invalid field
```

不能进入：

```text
accepted_facts
known
ready
```

---

# 32. 第五层防线：Export Final Gate

在真正输出：

```text
metadata.json
```

之前，应再次运行：

```text
full schema validation
```

最终流程：

```text
Working State
↓
to_metadata()
↓
JSON Schema validation
↓
Domain validation
↓
Export
```

---

# 33. Exporter 必须拒绝非法结构

即使由于程序 bug：

```text
Working State
```

内部意外出现非法结构，

Exporter 仍然必须阻止：

```text
metadata.json
```

生成。

---

# 34. 最终保证

必须实现：

> **最终生成的 metadata.json 永远满足 qREST Metadata Schema。**

这是最低要求。

---

# 35. 不建议静默自动纠错字段

例如：

```text
Channels = 18
```

很明显可能应该是：

```text
ChannelNum = 18
```

但系统不要：

```text
自动把 Channels 改成 ChannelNum
```

因为这种行为属于新的推测。

---

# 36. 推荐采用“拒绝 + 反馈 + 重试”

流程：

```text
LLM Candidate
Channels = 18
        ↓
Schema Gate
        ↓
Rejected
        ↓
Error:
Expected array, got integer
        ↓
LLM retry
```

---

# 37. LLM Schema Retry

可以增加一次可控重试。

例如：

```text
Your previous candidate was rejected:

field:
InstrumentInfo.Channels

expected:
array of channel objects

actual:
integer

Evidence:
“系统共布置18个传感器”

Re-examine the evidence and return corrected candidates.
```

模型很可能重新输出：

```text
ChannelNum = 18
```

---

# 38. Retry 仍必须经过 Schema Gate

不能：

```text
第一次检查
→ 第二次默认相信
```

任何 retry 输出仍然：

```text
Candidate
→ Schema Gate
```

---

# 39. Retry 次数限制

建议：

```text
max 1~2 retries
```

避免：

```text
无限循环
```

如果仍然失败：

```text
拒绝字段
向用户说明
```

---

# 40. Schema Error 与 Evidence Error 分离

建议明确区分两类问题：

## Schema Error

例如：

```text
Channels = 18
```

属于：

```text
数据结构错误
```

---

## Evidence Error

例如：

```text
Channels = [...]
```

结构正确，

但来源资料并未支持。

属于：

```text
事实来源错误
```

---

# 41. 两者都必须通过

一个 Candidate 要进入 Working State，应满足：

```text
Schema Valid
AND
Evidence Valid
```

即：

```text
Candidate
├─ Shape Gate
└─ Evidence Gate
```

---

# 42. Confidence 不应影响 Schema

无论：

```text
confidence = 0.99
```

还是：

```text
confidence = 0.2
```

如果：

```text
Channels = 18
```

都必须拒绝。

Schema 是硬规则。

---

# 43. Skill 不应替代 Schema

`instrument_info/SKILL.md` 可以解释：

```text
ChannelNum 的含义
Channels 的含义
两者关系
```

但不能依赖 Skill 来保证数据结构。

Skill 是：

```text
专业认知层
```

Schema 是：

```text
数据契约层
```

两者职责不同。

---

# 44. 建议更新 instrument_info Skill

增加明确说明：

```text
ChannelNum 与 Channels 必须严格区分。

“共有18个通道”
只能支持：
ChannelNum = 18

不能支持：
Channels = 18

Channels 必须是完整 channel object 数组。
如果资料只有总数量而没有逐通道配置，则：
ChannelNum 可以确认；
Channels 保持 missing。
```

这条规则非常重要。

---

# 45. 同样更新 building/data Skill

容易发生类似混淆的字段，例如：

```text
ElevationNum
Elevation
```

应明确：

```text
“建筑有16个标高层”
不能直接支持完整 Elevation 数组。
```

只有明确层高或标高数据时：

```text
Elevation = [...]
```

才能确认或确定性生成。

---

# 46. Schema 错误应在 UI 可见

Web UI 可以增加：

```text
Rejected / Invalid
```

诊断信息。

但不应把非法 Candidate 放进 Project State。

例如：

```text
本轮发现 1 个结构错误候选：

InstrumentInfo.Channels
expected: array
actual: integer

已拒绝写入项目状态。
```

---

# 47. Project State 只显示合法结构

右侧字段树：

```text
confirmed
extracted
derived
uncertain
inferred
missing
conflict
```

应保证这些状态中的 value 本身已经满足 Schema。

不要再出现：

```text
Channels [confirmed] = 18
```

---

# 48. 增加 Schema Diagnostics

建议 TurnResult 增加：

```text
rejected_candidates
schema_errors
```

例如：

```json
{
  "rejected_candidates": [
    {
      "field_path": "InstrumentInfo.Channels",
      "value": 18,
      "reason": "expected array, got integer"
    }
  ]
}
```

方便：

```text
测试
日志
UI
LLM retry
```

---

# 49. 测试策略需要升级

这次问题能够出现，说明当前测试虽然数量很多，但测试重心仍然偏：

```text
Agent 行为
Skill
Evidence
UI
```

缺少：

> Metadata Data Contract Tests

本轮必须增加专门测试。

---

# 50. Schema Contract 基础测试

针对所有 FieldSpec 自动测试：

```text
string field ← integer
integer field ← array
number field ← object
array field ← integer
object field ← string
```

必须全部失败。

---

# 51. 专门回归测试：Channels

必须加入：

```python
Candidate(
    field_path="InstrumentInfo.Channels",
    value=18
)
```

断言：

```text
Schema Gate rejects
WorkingState unchanged
Validator not ready
Exporter blocked
```

---

# 52. ChannelNum 回归测试

输入：

```text
InstrumentInfo.ChannelNum = 18
```

必须：

```text
合法 integer
```

但如果：

```text
Channels missing
```

则：

```text
Metadata 尚不完整
```

---

# 53. Channels item 类型测试

例如：

```text
Channels = [1, 2, 3]
```

必须失败。

---

# 54. Channels nested field 测试

例如：

```json
[
  {
    "ChannelNo": 1,
    "ChannelID": "A1"
  }
]
```

如果 mandatory keys 缺失：

```text
应被 Validator 报告
```

Candidate Gate 是否直接拒绝，可根据设计选择。

建议：

```text
基本 item type
→ Candidate Gate

完整 mandatory nested field
→ Validator
```

---

# 55. LocationXYZ 测试

非法：

```text
[1, 2]
```

或：

```text
["x", "y", "z"]
```

必须不能通过最终校验。

---

# 56. Elevation 回归测试

非法：

```text
Elevation = 16
```

必须：

```text
reject
```

---

# 57. Parameters 回归测试

非法：

```text
StructuralFootprint.Parameters = 46.9
```

必须：

```text
reject
```

---

# 58. BoundingBox 回归测试

非法：

```text
BoundingBox = "46x30"
```

必须拒绝。

---

# 59. DT / NPTS 回归测试

例如：

```text
DT = [0.02]
NPTS = "many"
```

必须被 Schema Gate 或 Validator 拒绝。

---

# 60. Import 测试

不仅测试 LLM。

用户上传：

```text
metadata.json
```

如果其中：

```text
Channels = 18
```

也必须：

```text
Import rejected / field invalid
```

不能因为来源是已有 JSON 就默认可信。

---

# 61. Tool 输出测试

Tool 返回的 Metadata 结构也要经过 Schema。

例如 Mock Tool：

```text
Channels = 18
```

必须阻止进入 Working State。

---

# 62. User confirmation 测试

用户明确确认：

```text
Channels = 18
```

也必须失败。

证明：

```text
confirmed
```

不会绕过 Schema。

---

# 63. Export 测试

人为构造错误 Working State：

```text
Channels = 18
```

然后：

```text
export_metadata()
```

必须失败。

这是最终安全网测试。

---

# 64. Schema Error 消息应明确

不要只说：

```text
invalid value
```

应返回：

```text
Field:
InstrumentInfo.Channels

Expected:
array<object>

Actual:
integer

Value:
18
```

便于：

```text
用户理解
开发调试
模型 retry
```

---

# 65. 数据结构错误与事实错误分离

建议错误分类：

```text
schema_error
evidence_error
consistency_error
missing_error
conflict_error
```

例如：

```text
Channels = 18
→ schema_error

ChannelNum = 18
Channels length = 17
→ consistency_error
```

---

# 66. Validator 分层

推荐：

```text
validate_metadata()
    ├─ validate_schema()
    ├─ validate_required()
    ├─ validate_evidence()
    └─ validate_domain_consistency()
```

便于维护和测试。

---

# 67. Schema Gate API

可以增加：

```python
validate_field_value(
    field_path: str,
    value: Any,
) -> FieldValidationResult
```

返回：

```python
@dataclass
class FieldValidationResult:
    valid: bool
    field_path: str
    expected: str | None
    actual: str | None
    errors: list[str]
```

---

# 68. Candidate Validation API

建议：

```python
validate_candidate(
    candidate,
    source_chunk,
) -> CandidateValidationResult
```

依次执行：

```text
field allowed
↓
schema
↓
evidence
↓
status
```

---

# 69. WorkingState 不重复实现全部 Schema

WorkingState 只需要调用：

```text
Schema utility
```

不要自己再写一套：

```python
if Channels ...
if Elevation ...
```

否则会重复。

---

# 70. Exporter 同样调用统一 Schema utility

目标：

```text
所有层共用一套 Schema validator
```

不是多套独立规则。

---

# 71. JSON Schema Library

如果项目允许，可以直接使用成熟 JSON Schema 校验库。

例如 Python：

```text
jsonschema
```

如果不希望增加依赖，也可以先实现轻量 Field Schema Gate。

但完整 Export 阶段建议优先考虑直接使用已有：

```text
metadata_schema.json
```

---

# 72. 如果不增加依赖

也可以第一阶段先实现：

```text
FieldSpec type gate
+
现有 Validator 深层检查
```

但目标仍应是：

```text
统一 Schema
```

而不是长期维持两套规则。

---

# 73. 建议实施阶段

## Phase 1：立即修复 P0 漏洞

修改 Validator：

```text
Channels 非 list
→ error
```

同时检查类似：

```text
Elevation
Version
Units
Parameters
BoundingBox
```

是否存在：

```text
类型不对却 return
```

的问题。

---

# 74. Phase 2：实现 Candidate Schema Gate

所有 LLM Candidate 在进入：

```text
Working State
```

前：

```text
validate_field_value()
```

不合法：

```text
reject
```

---

# 75. Phase 3：WorkingState 防线

所有：

```text
set
update
submit
confirm
derive
```

对 tracked metadata fields：

```text
执行基础 Schema 检查
```

---

# 76. Phase 4：Extraction Schema Context

把：

```text
field type
shape
nested structure
```

提供给 LLM。

同时补：

```text
ChannelNum vs Channels
ElevationNum vs Elevation
```

明确例子。

---

# 77. Phase 5：Full Validator

调整为：

```text
Schema Validation
+
Domain Validation
+
Evidence Validation
```

---

# 78. Phase 6：Export Final Gate

输出 metadata 前：

```text
再次完整验证
```

---

# 79. Phase 7：Schema Retry

增加一次：

```text
LLM structural correction retry
```

但不是第一阶段必需。

先把：

```text
错误必须被挡住
```

做好，再提升自动纠错体验。

---

# 80. Phase 8：回归测试

新增：

```text
Schema Contract
```

专项测试。

尤其保留：

```text
Channels = 18
```

作为永久 regression test。

---

# 81. 本轮暂时不做

不要因为这次 bug 又重新引入：

```text
大量项目专用正则
Kunming 专用 Channels 推导
复杂模板猜测
固定 channel layout workflow
```

这些不是本问题的正确解决方式。

---

# 82. 为什么不恢复旧实现

旧版本中 Channels 之所以通常正常，是因为存在：

```text
RuleBasedExtractor
```

直接生成完整 Channels。

这虽然避免了：

```text
Channels = 18
```

但也会引入：

```text
根据有限信息推测具体坐标
```

等问题。

所以旧逻辑可以作为：

```text
历史参考
```

但不应作为正式解决方案恢复。

---

# 83. 正确的新原则

旧架构的安全感来自：

```text
规则替模型做事
```

新架构的安全感应该来自：

```text
模型做语义理解
+
Schema 保证结构
+
Evidence 保证来源
+
Validator 保证一致性
```

---

# 84. 最终期望流程

例如资料：

```text
“监测系统总共18个通道。”
```

Agent：

```text
LLM
↓
ChannelNum = 18
↓
Schema valid
↓
Evidence valid
↓
Working State
```

同时：

```text
Channels
```

仍然：

```text
missing
```

因为资料没有完整通道定义。

---

# 85. 如果 LLM 错误输出

例如：

```text
Channels = 18
```

则：

```text
Schema Gate
↓
Reject
↓
Diagnostic
↓
optional retry
```

最终 Working State 仍然：

```text
Channels = missing
```

而不是：

```text
Channels = 18
```

---

# 86. 如果资料提供完整 Channels

例如表格中明确给出：

```text
18行通道
```

经过 Table Tool：

```text
Channels = [
  {...},
  {...},
  ...
]
```

然后：

```text
Schema valid
↓
ChannelNum = len(Channels)
↓
derived = 18
```

这是最可靠的路径。

---

# 87. ChannelNum 与 Channels 的建议关系

优先原则：

```text
如果已有 Channels：
ChannelNum = len(Channels)
```

应由 Tool 确定性推导。

如果只有：

```text
“共有18个通道”
```

则：

```text
ChannelNum = 18
Channels = missing
```

不要反向：

```text
ChannelNum = 18
→ 自动生成18个空 Channels
```

---

# 88. Accuracy 优先于 completeness

这是本轮最重要的产品原则：

> **宁可信息不完整，也不要生成错误结构或伪造完整信息。**

因此：

```text
ChannelNum known
Channels unknown
```

是完全可以接受的中间状态。

比：

```text
Channels = 18
```

或者：

```text
自动生成18个假的 Channels
```

更正确。

---

# 89. 完成标准

本轮开发完成后必须保证：

### 条件 1

```text
Channels = 18
```

无法进入 Working State。

### 条件 2

Validator 必须明确报：

```text
Channels expected array
```

### 条件 3

Exporter 必须阻止任何非法 Metadata。

### 条件 4

所有 array/object 字段都具备基础结构检查。

### 条件 5

LLM Extraction 能看到字段类型与结构。

### 条件 6

`ChannelNum` 与 `Channels` 不再仅靠模型语义区分。

### 条件 7

Schema、Evidence、Consistency 三类错误明确区分。

### 条件 8

新增永久 regression test：

```text
InstrumentInfo.Channels = 18
```

---

# 90. 最终架构原则

今后 qrest-agent 中所有 Metadata 处理都应遵循：

> **LLM 负责理解信息，不负责定义数据结构。**

> **Schema 负责保证字段的数据形状。**

> **Evidence 负责保证事实有来源。**

> **Validator 负责保证跨字段的一致性。**

> **Working State 只能保存结构合法的状态。**

> **Exporter 必须保证最终输出永远符合 qREST Metadata Schema。**

以及本轮最重要的一句话：

> **Agent 可以不知道某个字段，但绝不能把一个结构上不可能的值当作正确答案。**