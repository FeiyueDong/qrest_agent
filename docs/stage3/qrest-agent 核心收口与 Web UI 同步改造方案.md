# qrest-agent 核心收口与 Web UI 同步改造方案

## 1. 本轮工作的定位

目前 qrest-agent 已经基本完成从：

```text
固定 workflow + LLM 提取器
```

向：

```text
QrestAgent
+ Skills
+ Tools
+ Working State
+ Evidence
+ Validator
+ LLM Responder
```

的架构转变。

现阶段不建议再次整体推翻核心架构。

本轮工作的重点应由“架构重构”转为：

> **修正 Agent 各阶段之间的语义断点，使 Planning、Skill、Extraction、Working State、Validator 和 Response 真正形成一致链路，同时同步更新已经落后于核心架构的 Web UI。**

本轮可以继续进行较明显的代码调整，但原则上应围绕当前正确架构进行收口，而不是重新设计一套新的 Agent Runtime。

---

# 2. 当前架构中值得保留的部分

以下部分已经基本符合目标，建议继续保留并在其上完善：

```text
QrestAgent
AgentPlanner
TurnPlan
SkillRegistry
ToolRegistry
WorkingState
FieldState
Evidence
Validator
MetadataExporter
LLMExtractor
Responder
LLM Provider
Document ingestion
ArtifactManager
qREST Data Tools
```

当前主链路：

```text
ingest
→ intent + skill selection
→ load Skill
→ action planning
→ execute actions
→ extraction / tools
→ Working State
→ deterministic derivation
→ Validator
→ Trusted Context
→ Responder
```

总体方向正确。

本轮不需要再引入：

```text
TaskCoordinator
ActionInterpreter
TaskHandler
多个业务 Agent
第二套 Metadata State
复杂 workflow engine
```

---

# 3. 本轮核心目标

需要解决以下 6 个主要问题：

1. **Skill 目前只直接影响 Planning，没有完整进入 Extraction；**
2. **Trusted Context 对 uncertain / inferred 等状态的表达不够严格；**
3. **纯文件上传时 Planner 不知道本轮具体收到什么资料；**
4. **ask Action 没有真正携带“需要向用户询问什么”的信息；**
5. **Responder 对多轮对话上下文利用不足；**
6. **Web UI 仍然基于旧的 handler/task 模型，已经与当前 Agent 架构脱节。**

完成后希望形成：

```text
User + Attachments
        ↓
Intent / Skill Selection
        ↓
Load Skill
        ↓
Action Planning
        ↓
Skill-aware Extraction / Tool Execution
        ↓
Working State
        ↓
Validator
        ↓
Structured Trusted Context
        ↓
Natural Response
        ↓
Web UI 展示事实、来源和本轮 Agent 行为
```

---

# 4. 优先级划分

建议分成三个层次：

## P0：事实可信性

必须优先解决：

```text
Skill → Extraction
Trusted Context 状态过滤
ask Action 语义
```

这些直接关系到 Agent 是否会产生错误表达。

---

## P1：Agent 上下文完整性

包括：

```text
文件信息进入 Planner
conversation memory 进入 Responder
统一 Turn 输入
```

解决 Agent 在真实对话中的理解能力。

---

## P2：Web UI 同步

包括：

```text
新 Working State 状态展示
Evidence
Turn Plan
Skills
Tools
Attachments
Artifacts
```

---

# 5. Skill 必须进入 Extraction

## 5.1 当前问题

目前完整 `SKILL.md` 已经进入 Planner，因此 Skill 可以影响：

```text
是否 extract
是否 ask
是否调用 Tool
```

但真正执行 Extraction 时，LLMExtractor 主要看到：

```text
Extraction System Prompt
+
Source Chunk
```

并不知道：

```text
本轮 intent
selected skills
Skill instructions
```

因此存在：

```text
Planner 很专业
↓
Extractor 又变成通用 Metadata 抽取器
```

的问题。

---

# 6. 修改 Extraction 接口

建议从：

```python
extractor.extract(chunks)
```

调整为：

```python
extractor.extract(
    chunks,
    context=ExtractionContext(...)
)
```

建议：

```python
@dataclass
class ExtractionContext:
    intent: str
    selected_skills: list[str]
    skill_instructions: list[str]
    user_message: str
```

或者：

```python
extract(
    chunks,
    intent=plan.intent,
    skills=loaded_skills,
)
```

具体形式不限，但 Extraction 必须能够知道本轮专业上下文。

---

# 7. Extraction Prompt 的目标

新的 Extraction Prompt 应组合：

```text
稳定 Extraction System Prompt
+
本轮 intent
+
相关 Skill instructions
+
当前 source chunk
```

例如：

```text
Intent:
correction

Relevant skills:
building_info

Skill instructions:
...
```

然后：

```text
Source:
前面的建筑长度写错了，应为 46.9 m。
```

---

# 8. correction 必须可靠产生 confirmed

当前 Planning 已能判断：

```text
intent = correction
```

但 Extractor 不知道这个 intent。

修改后明确规定：

```text
如果：
source_type = user_message
AND
intent = correction
AND
用户明确给出替代值

则：
status = confirmed
```

例如：

```text
用户：
前面说的长度不对，应该是 46.9m。
```

生成：

```json
{
  "field_path": "BuildingInfo.StructuralFootprint.Parameters",
  "value": {
    "Length": 46.9
  },
  "status": "confirmed"
}
```

而不是普通 `extracted`。

---

# 9. Skill 对 Extraction 的实际价值

例如 `building_info` Skill 中规定：

```text
StructuralType 只有资料明确说明时才能 extracted
不能因为建筑用途推测
```

那么 Extractor 应真正受到该规则约束。

类似：

```text
instrument_info
sensor_layout
data_info
```

都应该参与真正的候选生成。

---

# 10. 不需要所有 Skill 都送入 Extractor

只注入：

```text
plan.skills
```

中和 Extraction 相关的 Skill。

避免每轮把所有 Skill 塞给模型。

例如：

```text
用户询问 qREST 文件生成
```

可能选择：

```text
qrest_data
```

若本轮没有 metadata extraction，则无需调用 Extractor。

---

# 11. Trusted Context 必须重新定义

这是本轮最重要的数据语义调整之一。

当前不应简单把：

```text
candidate.value != null
```

理解成“新事实”。

应该严格区分：

```text
accepted_facts
uncertain_candidates
inferred_candidates
conflicts
missing_required
missing_important
```

---

# 12. accepted_facts

只允许：

```text
confirmed
extracted
derived
```

并且最好使用：

> Working State merge 后的最终状态

而不是直接使用原始 Candidate。

原因是 Candidate 可能在 merge 后：

```text
变成 conflict
被旧 confirmed 值拒绝
被替换
被降级
```

---

# 13. 推荐 Trusted Context

例如：

```json
{
  "intent": "collect_metadata",

  "accepted_facts": [
    {
      "field": "BuildingInfo.StructuralType",
      "value": "RCFrame",
      "status": "extracted"
    }
  ],

  "uncertain": [
    {
      "field": "BuildingInfo.GeoLocation.NorthAngle",
      "value": 15,
      "reason": "source ambiguous"
    }
  ],

  "inferred": [],

  "conflicts": [],

  "missing_required": [
    "BuildingInfo.GeoLocation.NorthAngle"
  ],

  "requested_inputs": [],

  "tool_results": [],

  "report_ready": false
}
```

---

# 14. Responder 的事实规则

Responder Prompt 应明确：

```text
accepted_facts：
可以作为事实陈述

uncertain：
只能描述为“可能/资料中存在候选，需要确认”

inferred：
只能描述为“推测，不进入正式 Metadata”

conflict：
必须说明存在冲突

missing：
只能询问，不能补充
```

核心原则：

> **语言层的确定程度必须与 Working State 的确定程度一致。**

---

# 15. “Trusted Context” 名称要真正可信

当前设计中如果：

```text
uncertain
inferred
```

也直接进入“known fields”，则 Trusted Context 名称本身会失去意义。

因此建议后续只把真正可接受状态放到：

```text
trusted_fields
accepted_facts
```

其余状态必须单独分类。

---

# 16. 文件输入必须进入 Planner Context

## 16.1 当前问题

用户只上传：

```text
project.docx
```

而不输入文字时：

```text
run_turn(files=[...])
```

虽然程序已经读取文件内容，但 Planner Context 没有明确告诉 LLM：

```text
本轮收到 project.docx
文件类型 docx
共多少 chunk
大概是什么内容
```

因此 Skill Selection 可能处于“看不见上传资料”的状态。

---

# 17. 增加 Input Sources

建议建立：

```python
@dataclass
class InputSourceSummary:
    source_id: str
    source_type: str
    name: str
    chunk_count: int
    preview: str
```

Planner Context 加入：

```json
{
  "input_sources": [
    {
      "name": "building_report.docx",
      "type": "docx",
      "chunk_count": 18,
      "preview": "昆明某隔震建筑..."
    }
  ]
}
```

---

# 18. preview 不需要太长

第一阶段 Skill Selection 不需要全文。

可以：

```text
每个 source 200~500 字符
最多 N 个 sources
```

目的只是让 Agent 知道：

> 用户这一轮到底给了什么。

之后真正 Extraction 再读取完整 chunk。

---

# 19. 文件本身也应该成为 Agent 输入的一部分

最终统一思想：

```text
Turn Input
=
User Message
+
Attachments
```

而不是：

```text
chat 是一种 Turn
upload 又是另一种 Turn
```

---

# 20. ask Action 必须结构化

## 20.1 当前问题

现在：

```text
ask
```

执行时基本只是停止后续 actions。

但没有记录：

```text
为什么 ask
需要什么
用户应该怎样提供
```

这会导致 Responder 只能根据 Validator 推测。

但 Validator 只负责 Metadata，不知道业务操作缺少：

```text
data.txt
qrest path
output destination
```

等任务级输入。

---

# 21. 推荐 ask Action

例如：

```json
{
  "type": "ask",
  "arguments": {
    "reason": "missing_required_input",
    "request": "请提供用于生成 qREST 的时程数据文件 data.txt",
    "expected": "path_or_attachment"
  }
}
```

---

# 22. ask 应进入 action_results

例如：

```json
{
  "ask": {
    "reason": "missing_data_txt",
    "request": "请提供 data.txt",
    "expected": "file"
  }
}
```

Trusted Context 中加入：

```text
requested_inputs
```

Responder 就可以直接使用。

---

# 23. 区分 Metadata 缺失和 Task 缺失

必须明确：

```text
metadata_missing
```

和：

```text
task_input_missing
```

不是一回事。

例如：

```text
Metadata 已 ready
用户要求生成 qREST
但没有 data.txt
```

应表现为：

```text
metadata_ready = true
task_ready = false
```

不能简单说：

> 已可以继续。

---

# 24. ActionPlan 建议允许连续多 Action

例如：

```text
export
→ preflight_generate_qrest
→ generate_qrest
```

这是合理的。

但是：

```text
ask
```

之后应终止本轮后续执行。

同时需要完整保存 ask 信息。

---

# 25. Conversation Memory 应进入 Responder

现在 conversation memory 已经用于 Planner：

```text
user
intent
new_facts
response
```

这个设计可以继续。

但 Responder 也应获得：

```text
recent_conversation
```

用于处理：

```text
“为什么？”
“刚才那项是什么意思？”
“那就按前面的值。”
```

这种指代。

---

# 26. 对话历史不能成为工程事实来源

必须始终保持：

```text
Conversation Memory
=
帮助理解语义

Working State
=
工程事实
```

Responder Prompt 建议明确：

> 对话历史只用于理解用户指代和上下文，不得使用其中与 Working State 冲突的信息作为工程事实。

---

# 27. Memory 建议结构

例如：

```json
{
  "recent_conversation": [
    {
      "user": "建筑长度为 48m",
      "intent": "collect_metadata",
      "accepted_facts": [
        "Length=48"
      ],
      "assistant_summary": "已记录建筑长度"
    }
  ]
}
```

之后用户：

```text
“刚才的长度改为46.9m”
```

Planner 可以更容易判断目标字段。

---

# 28. Tool Schema 可以继续保留

当前 ToolSpec 已支持：

```text
type
required
minimum
description
```

这是正确方向。

后续可以逐步补：

```text
enum
maximum
items
properties
```

但本轮不需要做复杂 JSON Schema 框架。

保持轻量即可。

---

# 29. Tool 执行错误应作为 Agent 上下文

例如：

```text
generate_qrest
```

失败：

```text
data file does not exist
```

不能只是：

```text
ToolResult error
```

还应进入：

```text
Trusted Context
→ Responder
```

让 Agent 自然解释下一步。

---

# 30. RuleBasedExtractor 继续降级

当前 RuleBasedExtractor 已经只作为：

```text
无 LLM
LLM 失败
LLM 无结果
```

fallback。

这个策略基本合理。

但后续继续避免向其中添加：

```text
特定工程
特定论文
特定项目
复杂自然语言
```

的正则。

只保留非常通用的：

```text
JSON
明确 Field: Value
结构化文本
```

即可。

---

# 31. Web UI 必须同步改造

本轮建议正式更新 Web UI。

原因不是视觉样式，而是：

> **当前 UI 的数据模型已经落后于 Agent Runtime。**

旧 UI 仍使用：

```text
skill_handlers
task_logs
known
missing
conflict
```

但新架构已经不存在真正的：

```text
TaskHandler
```

并且 Working State 的状态已经更加细化。

---

# 32. Web UI 改造原则

UI 应展示用户真正关心的三类信息：

```text
1. Conversation
2. Project State
3. Agent Activity
```

而不是暴露内部旧 workflow 概念。

---

# 33. 推荐总体布局

继续保留简单两栏式：

```text
┌──────────────────────────────────┬─────────────────────┐
│                                  │ Project State       │
│                                  │                     │
│                                  │ 已确认              │
│                                  │ 待确认              │
│        Conversation              │ 缺失                │
│                                  │ 冲突                │
│                                  │                     │
│                                  │ Fields              │
│                                  ├─────────────────────┤
│                                  │ This Turn           │
│                                  │ Skills              │
│                                  │ Actions             │
│                                  │ Tools               │
├──────────────────────────────────┴─────────────────────┤
│ Attachments                                             │
│ 输入信息或要求……                                [发送] │
└────────────────────────────────────────────────────────┘
```

不需要复杂 Dashboard。

---

# 34. Project State 状态重新设计

不再采用：

```text
已知
缺失
冲突
```

建议改成：

```text
已确认
待确认
缺失
冲突
```

---

# 35. 状态映射

## 已确认

```text
confirmed
extracted
derived
```

可以使用不同小标签区分来源。

---

## 待确认

```text
uncertain
inferred
```

---

## 缺失

```text
missing
```

以及 Validator 报告中要求但尚未创建 record 的字段。

---

## 冲突

```text
conflict
```

---

# 36. Field 展示 Evidence

字段详情建议变为：

```text
StructuralType
RCFrame
[extracted]

来源：
building_report.docx

位置：
page 3 / paragraph 5

Evidence：
“the structural system consists of reinforced-concrete moment frames”

confidence:
0.92
```

---

# 37. Derived 字段展示方式

例如：

```text
ElevationNum
16
[derived]

Derived from:
BuildingInfo.Elevation

Tool:
derive_counts
```

这样用户可以明确知道：

> 这是程序算出来的，不是 LLM 从资料中读出来的。

---

# 38. inferred 必须明显区别

例如：

```text
NorthAngle
15°
[inferred / 待确认]
```

UI 不应把 inferred 看成“已知”。

如果项目默认不允许 inferred 进入 Metadata，可以增加：

```text
不会进入正式 metadata
```

的提示。

---

# 39. 显示本轮 Agent Activity

建议增加：

```text
This Turn
```

区域。

内容例如：

```text
Intent
collect_metadata

Skills
building_info
instrument_info

Actions
✓ extract
✓ derive_counts
✓ validate

Tools
derive_counts

Result
需要补充 NorthAngle
```

---

# 40. 不显示 Chain-of-Thought

这里只展示：

```text
结构化 Plan
Tool
Skill
Validation Result
```

不要展示模型内部推理过程。

目标是：

```text
可解释
可调试
```

而不是：

```text
暴露模型思维链
```

---

# 41. Web API 需要暴露 Turn 信息

目前 DialogueResult 应适当扩展。

建议加入：

```text
plan
selected_skills
actions
tool_results
extractor
fallback_reason
```

例如：

```json
{
  "response": "...",
  "report": {...},

  "turn": {
    "intent": "collect_metadata",
    "skills": [
      "building_info"
    ],
    "actions": [
      {
        "type": "extract"
      }
    ],
    "tools": []
  }
}
```

---

# 42. 删除 skill_handlers

`skill_handlers` 已经不再是真实架构概念。

应直接删除：

```text
skill_handlers
handlers.length
```

以及为兼容旧 UI 人工生成该字段的代码。

Web UI 直接使用：

```text
skills
```

即可。

---

# 43. 删除旧 Task Logs 区域

如果所谓 Task Log 已经只是旧 Handler 时代的产物，不建议继续作为 UI 一级概念。

可以换成：

```text
Artifacts
```

例如：

```text
metadata.json
metadata_export_report.json
generated.qrest
loaded_metadata.json
loaded_data.txt
```

---

# 44. Artifacts 比 Task Logs 更符合当前系统

Agent 实际产生的是：

```text
Tools
→ Artifacts
```

而不是：

```text
Task Handler
→ Task Log
```

因此 UI 应展示真实产物。

---

# 45. 文件上传改为 Attachment 模型

## 当前模式

```text
选文件
→ 点击导入
→ 文件立即单独触发一个 Agent Turn
```

建议调整。

---

# 46. 推荐模式

用户先选择文件：

```text
[building_report.docx ×]
[channel_layout.xlsx ×]
```

然后输入：

```text
“请根据这些资料整理当前项目的 metadata。”
```

最后一起发送。

形成：

```text
Turn
=
message
+
attachments
```

---

# 47. 后端接口建议

最终推荐：

```http
POST /api/turn
```

例如：

```json
{
  "session_id": "...",
  "message": "请整理这些资料",
  "attachments": [
    "uploads/building_report.docx",
    "uploads/channel_layout.xlsx"
  ]
}
```

---

# 48. 上传接口只负责保存文件

```text
POST /api/upload
```

只返回：

```json
{
  "attachment_id": "...",
  "name": "...",
  "path": "..."
}
```

不立即调用 Agent。

---

# 49. Web UI 不需要引入大前端框架

本轮仍建议：

```text
HTML
CSS
Vanilla JS
```

即可。

暂不引入：

```text
React
Vue
Node build chain
复杂组件框架
```

因为当前核心任务还是 Agent 行为测试。

---

# 50. 但 server.py 应拆分

目前大量：

```text
Python
+ HTML
+ CSS
+ JavaScript
```

全部集中于一个文件已经不适合继续维护。

建议：

```text
src/qrest_agent/web/
    server.py

    static/
        index.html
        app.js
        style.css
```

---

# 51. server.py 职责

只保留：

```text
route
request parsing
response
static file serving
```

---

# 52. app.js 职责

负责：

```text
session
chat
attachments
render state
render evidence
render turn activity
artifacts
```

---

# 53. style.css

继续保持当前简洁风格即可。

本轮不建议大量做视觉美化。

核心是：

```text
信息结构正确
交互逻辑正确
```

---

# 54. API Session 输出同步调整

建议：

```json
{
  "session_id": "...",
  "runtime": {...},
  "report": {...},
  "records": {...},

  "skills": [...],

  "artifacts": [...],

  "last_turn": {
    "intent": "...",
    "skills": [...],
    "actions": [...],
    "tools": [...]
  }
}
```

不再暴露：

```text
skill_handlers
task_logs
```

---

# 55. 新增附件状态

Session 可维护：

```text
uploaded attachments
```

至少 Web UI 要知道：

```text
已经上传
尚未用于 Turn
已经用于 Turn
```

第一版可以简单一些：

```text
pending attachments
```

即可。

---

# 56. Web UI 中的 Export

保留：

```text
导出 metadata.json
```

按钮没有问题。

但建议状态明显显示：

```text
Ready
Not Ready
```

当无法导出时按钮可以保持可点击，让用户查看原因，也可以 disabled + tooltip。

推荐仍可点击：

```text
点击
→ Validator
→ 显示阻断原因
```

这样更利于调试。

---

# 57. Web UI 不直接修改 Working State

当前仍然坚持：

> 对话是主入口。

暂时不要把 UI 做成传统 Metadata Editor。

也就是说：

```text
点击字段
→ 直接编辑 value
```

暂时不是主功能。

如果要修改，优先：

```text
用户在聊天中说：
“把建筑长度改成 46.9m”
```

这样可以测试真实 Agent 能力。

---

# 58. 可以保留 Debug 命令

CLI 中：

```text
/state
/tools
/confirm
/load-qrest
/generate-qrest
```

这类命令可以继续保留。

但它们的定位必须明确：

```text
debug / low-level interface
```

而不是正式 Agent 用户流程。

---

# 59. 测试重点转向真实 LLM

现有 mock tests 应继续保留。

但下一阶段需要增加：

```text
real-model integration tests
```

不一定纳入每次 CI。

可以建立：

```text
tests/integration/
```

或：

```text
scripts/manual_e2e/
```

---

# 60. 真实测试重点

至少覆盖：

### 场景 1

自然语言：

```text
这是一栋14层RC框架建筑。
```

检查：

```text
Skill selection
Extraction
Evidence
Missing
Response
```

---

### 场景 2

上传 Word：

```text
无文字
+
building_report.docx
```

检查 Planner 是否知道：

```text
本轮有建筑资料
```

---

### 场景 3

文件 + 文字：

```text
“请根据附件整理建筑和传感器信息”
+
docx
+
xlsx
```

---

### 场景 4

多轮修正：

```text
第一轮：长度48m
第二轮：刚才长度改为46.9m
```

---

### 场景 5

Evidence 幻觉

资料中没有 StructuralType。

确认模型不会生成可导出的：

```text
RCFrame
```

---

### 场景 6

uncertain 表达

来源模糊时：

```text
Working State = uncertain
```

Responder 不得说：

```text
“已经确认……”
```

---

### 场景 7

qREST 生成缺文件

```text
Metadata ready
+
用户说生成 qREST
+
没有 data.txt
```

Agent 必须自然询问：

```text
请提供 data.txt
```

而不是仅告诉用户 Metadata ready。

---

### 场景 8

qREST 完整生成

```text
Metadata ready
+
data.txt
```

应：

```text
Skill
→ export
→ preflight
→ generate_qrest
→ artifact
→ response
```

---

# 61. 新增架构测试

除现有测试外，建议补以下测试。

## Test A：Skill 注入 Extractor

断言 Extraction LLM 请求中包含：

```text
building_info Skill 内容
```

---

## Test B：correction context

断言：

```text
intent = correction
```

真正传入 Extraction。

---

## Test C：Trusted Context 状态过滤

构造：

```text
extracted
uncertain
inferred
conflict
```

确认：

```text
accepted_facts
```

只包含：

```text
extracted
```

---

## Test D：file-only planning

调用：

```python
agent.run_turn(files=[...])
```

确认 Planner Context 中存在：

```text
input_sources
```

---

## Test E：ask action

模拟：

```text
missing data.txt
```

确认 Trusted Context 中出现：

```text
requested_inputs
```

---

## Test F：Responder receives history

确认：

```text
recent_conversation
```

真正送入 Responder。

---

# 62. Web UI 测试

建议测试：

```text
confirmed
uncertain
inferred
missing
conflict
```

分别被正确分类。

特别确认：

```text
uncertain
inferred
```

不再显示为“已知”。

---

# 63. API 测试

增加：

```text
POST /api/upload
POST /api/turn
GET /api/session
```

组合测试：

```text
upload
→ pending attachment
→ send turn
→ Agent uses attachment
```

---

# 64. 本轮建议的实施阶段

## Phase 1：修复 Agent 语义链

完成：

```text
Skill → Extraction
intent → Extraction
Trusted Context 分类
ask structure
```

这是最优先部分。

---

## Phase 2：补全输入与记忆上下文

完成：

```text
input_sources
attachments
Responder recent conversation
```

---

## Phase 3：调整 API

完成：

```text
统一 /api/turn
upload 不自动触发 Agent
TurnResult 输出 plan/tools/skills
```

---

## Phase 4：Web UI 数据模型更新

完成：

```text
已确认
待确认
缺失
冲突
Evidence
This Turn
Artifacts
Attachments
```

删除：

```text
skill_handlers
task_logs
```

---

## Phase 5：拆分 Web 静态文件

完成：

```text
server.py
index.html
app.js
style.css
```

---

## Phase 6：真实 LLM E2E

使用实际 Ollama 模型反复测试。

这一阶段原则：

> 不再优先修改架构，而是记录真实模型失败模式，再做针对性调整。

---

# 65. 本轮不建议做的事情

暂时不要：

```text
Multi-Agent
RAG
Vector DB
React/Vue
复杂数据库
用户权限
云部署系统
自动联网
Workflow DAG
复杂前端编辑器
```

当前阶段真正需要验证的是：

> 一个 Agent 能不能稳定、可信地完成 qREST 信息建立。

---

# 66. 完成标准

本轮完成后，理想交互如下。

---

## 第一轮

用户上传：

```text
building_report.docx
channel_layout.xlsx
```

并输入：

```text
请根据这些资料整理当前项目的信息。
```

Agent：

```text
→ 知道本轮包含两个附件
→ 选择 building_info / instrument_info / sensor_layout
→ 加载 Skills
→ Skill-aware Extraction
→ Tool 解析表格
→ Working State
→ Validator
→ 发现 NorthAngle 缺失
→ 自然回复用户
```

Web UI 同时显示：

```text
已确认 14
待确认 1
缺失 3
冲突 0

This Turn
building_info
instrument_info
sensor_layout

Actions
extract
table_reader
validate
```

---

## 第二轮

用户：

```text
局部 Y 轴顺时针偏离正北 20°。
```

Agent：

```text
intent = collect/correction
→ confirmed NorthAngle
→ Working State
→ Validator
→ 回复
```

---

## 第三轮

用户上传：

```text
data.txt
```

并说：

```text
用当前项目生成 qREST。
```

Agent：

```text
qrest_data Skill
→ export metadata
→ preflight
→ generate_qrest
→ Artifact
→ 回复生成结果
```

Web UI：

```text
Artifacts
✓ metadata.json
✓ generated.qrest
```

整个过程中用户不需要操作：

```text
TaskHandler
Metadata Workflow
Field Wizard
```

也无需理解系统内部架构。

---

# 67. 本轮最终原则

继续保持：

> **LLM 负责理解、选择和表达。**

> **Skill 负责专业知识。**

> **Tool 负责确定执行。**

> **Working State 负责工程事实。**

> **Evidence 负责说明事实来源。**

> **Validator 负责数据可信性。**

同时增加两条：

> **Skill 不仅影响“做什么”，还必须影响“怎样理解和提取”。**

> **UI 应展示 Agent 的真实状态，而不是为了兼容旧架构制造虚假的概念。**

最后，本轮最重要的工程目标可以概括为：

> **把已经正确的 Agent 架构真正“接通”，然后让 Web UI 成为这一架构的透明窗口，而不是另一套独立工作流。**