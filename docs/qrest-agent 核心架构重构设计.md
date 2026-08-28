# qrest-agent 核心架构重构设计

## 1. 本轮工作的定位

本轮不再视为对现有 `qrest-agent` 的增量优化，而应视为一次围绕最终目标重新搭建核心架构的重构。

现有项目中已经存在一些有价值的实现，例如：

- qREST Metadata Schema；
- Working State；
- Evidence；
- Validator；
- Metadata Exporter；
- 文件读取能力；
- qREST 数据读写工具；
- 一些可靠的确定性计算函数；
- LLM Provider 接口；
- 已整理出的专业 Skill 文档。

这些内容可以选择性复用。

但现有目录、类、调用关系、API、CLI 以及旧 workflow **均不构成本轮设计约束**。

本轮遵循：

> **复用正确的能力，而不是复用已有架构。**

如果旧代码与新架构冲突，应优先删除、重写或迁移，而不是通过 Adapter、Facade 或兼容层继续保留。

---

# 2. 最终目标

qrest-agent 最终应成为：

> 一个由 AI 主导行为、具有 qREST 专业知识和确定性工程工具、能够通过自然语言和上传资料持续建立可信工程信息的专业 Agent。

用户可以自由地：

- 描述工程信息；
- 上传 Word、PDF、Excel、CSV、JSON 等资料；
- 补充信息；
- 修改之前的信息；
- 询问当前状态；
- 让 Agent 检查信息完整性；
- 请求生成 metadata；
- 请求生成或读取 qREST 数据。

用户不需要理解内部 Metadata Schema，也不需要按照固定顺序填写字段。

Agent 应负责理解：

```text
用户现在想做什么？
已经知道什么？
资料中又提供了什么？
应该读取哪个 Skill？
应该调用哪个 Tool？
哪些事实可以确认？
哪些信息存在冲突？
哪些信息仍然缺失？
下一步应该做什么？
应该怎样向用户解释？
```

---

# 3. 核心原则

## 3.1 AI 是系统的行为主体

新的系统不采用：

```text
Python 判断任务
→ Python 决定步骤
→ Python 调用 LLM 填字段
→ Python 拼接回复
```

而采用：

```text
用户输入
    ↓
主 Agent
    ↓
理解当前意图与上下文
    ↓
选择 Skill
    ↓
选择 Tool / 提取信息 / 询问用户
    ↓
更新 Working State
    ↓
Validator
    ↓
主 Agent 根据可信状态生成回复
```

Python 仍然控制安全边界和确定性执行，但不负责模拟“智能行为”。

---

## 3.2 LLM 决策，但不能直接修改最终工程数据

LLM 可以决定：

- 当前输入的意义；
- 需要使用哪些 Skill；
- 是否需要读取某个文件；
- 是否需要调用某个 Tool；
- 哪些内容值得提取；
- 是否应该询问用户；
- 如何自然地回复用户。

但 LLM 不允许：

- 直接写最终 Metadata；
- 绕过 Working State；
- 绕过 Validator；
- 自行创造工程数值；
- 将工程经验推测伪装成事实。

---

## 3.3 Skill 提供专业知识

Skill 应解决：

> “作为 qREST Agent，面对这一类问题应该怎样理解和处理？”

例如：

```text
skills/
    metadata/
    building_info/
    instrument_info/
    data_info/
    sensor_layout/
    qrest_data/
```

Skill 中应主要保存：

- 字段含义；
- 工程解释；
- 判断原则；
- 允许的推导；
- 禁止的推测；
- 应向用户询问的内容；
- 常见冲突；
- 可调用的 Tool 建议。

Skill **不是固定 workflow**。

---

## 3.4 Tool 只完成明确能力

Tool 应满足：

```text
输入明确
输出明确
行为确定
可独立测试
```

例如：

```text
read_document
read_table
calculate_frequency
calculate_bounding_box
validate_metadata
load_qrest
generate_qrest
write_metadata
```

Tool 不应决定：

```text
接下来应该问什么
应该选择哪个 Skill
某个字段是否应该相信
当前任务是否结束
```

---

## 3.5 Working State 是唯一事实中心

所有工程信息都首先进入 Working State。

最终 Metadata 只是 Working State 在满足条件后的一个投影结果。

即：

```text
Sources
   ↓
Candidates
   ↓
Working State
   ↓
Validator
   ↓
Metadata
```

不能存在第二套并行状态，例如：

```text
MetadataState
ProjectState
AgentState
temporary metadata
```

如果不是必要的运行时信息，应统一收敛到 Working State。

---

# 4. 目标架构

建议总体结构：

```text
                      User
             text / files / commands
                        │
                        ▼
                ┌──────────────┐
                │  QrestAgent  │
                │     LLM      │
                └───────┬──────┘
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
       Skills         Tools       WorkingState
     专业知识        确定能力        工程事实
          │             │             │
          └─────────────┼─────────────┘
                        ▼
                    Validator
                        │
                        ▼
                Trusted Context
                        │
                        ▼
                 LLM Response
```

其中有两个 LLM 阶段：

```text
LLM Decision
```

和：

```text
LLM Response
```

中间由确定性系统保证数据可信。

---

# 5. 推荐的核心目录

不要求严格保持该目录，但建议按照职责组织：

```text
src/qrest_agent/

    agent/
        agent.py
        planner.py
        responder.py
        context.py

    skills/
        registry.py
        loader.py

    state/
        working_state.py
        field_state.py
        evidence.py

    schema/
        metadata_schema.py
        field_policy.py

    validation/
        validator.py
        rules.py

    extraction/
        extractor.py
        candidate.py

    tools/
        registry.py
        documents.py
        tables.py
        metadata.py
        calculations.py
        qrest_data.py

    llm/
        client.py
        provider.py

    storage/
        session.py
        artifacts.py

resources/

    skills/
        metadata/
            SKILL.md
        building_info/
            SKILL.md
        instrument_info/
            SKILL.md
        data_info/
            SKILL.md
        sensor_layout/
            SKILL.md
        qrest_data/
            SKILL.md
```

避免出现大量：

```text
task_coordinator
workflow_manager
metadata_agent
action_agent
task_router
```

第一版只保留一个 Agent。

---

# 6. Agent 的真正运行循环

本轮最核心的工作，是重新实现 Agent Loop。

推荐流程如下。

---

## Step 1：接收输入

输入可能包括：

```text
user_message
uploaded_files
current Working State
conversation history
```

首先构建本轮上下文。

---

## Step 2：Agent 判断当前意图

LLM 应首先理解：

```text
这是新增工程资料？
用户正在纠正信息？
用户提出问题？
用户要求读取文件？
用户希望生成 Metadata？
用户希望生成 qREST？
用户只是询问当前状态？
```

这里不要依赖大量正则表达式作为正常路径。

规则判断只允许作为：

```text
LLM unavailable fallback
```

---

# 7. Skill 的动态选择机制

这是本轮必须解决的核心问题。

当前输入进入 Agent 后，LLM 应能够看到可用 Skill 的摘要，例如：

```json
[
  {
    "name": "building_info",
    "description": "建筑位置、结构类型、尺寸、标高等信息"
  },
  {
    "name": "instrument_info",
    "description": "监测设备、通道和传感器信息"
  }
]
```

Agent 首先选择：

```text
selected_skills
```

例如：

```json
{
  "skills": [
    "building_info",
    "sensor_layout"
  ]
}
```

然后程序加载：

```text
resources/skills/building_info/SKILL.md
resources/skills/sensor_layout/SKILL.md
```

并将完整 Skill 内容加入下一阶段 Agent Context。

因此 Skill 的真正工作方式必须是：

```text
LLM
 ↓
选择 Skill
 ↓
加载 SKILL.md
 ↓
LLM 阅读 Skill
 ↓
基于专业规则继续决策
```

而不是：

```text
Python 已做完决定
 ↓
最后附上一句 Skill 提示
```

---

# 8. Agent Planning

在获得 Skill 后，Agent 再生成真正的行动计划。

建议计划结构：

```json
{
  "intent": "collect_metadata",
  "skills": [
    "building_info"
  ],
  "actions": [
    {
      "type": "extract"
    },
    {
      "type": "tool",
      "tool": "calculate_bounding_box",
      "arguments": {
        "length": 46.9,
        "width": 30.0
      }
    }
  ],
  "need_user_input": false,
  "reason": "用户提供了建筑尺寸，可提取参数并计算包围盒"
}
```

允许的基础 Action 建议只有：

```text
extract
tool
ask
respond
export
```

不要额外创造大量业务 Action。

例如 qREST 文件生成，本质仍然可以表示：

```text
tool: generate_qrest
```

如果某项操作需要多步执行，可以由 Skill 告诉 Agent 应调用哪些 Tools，而不是再建立独立业务框架。

---

# 9. Extraction 应回归“语义提取”

新的正式运行路径中：

```text
LLM + selected Skills
```

负责从自然语言和文件内容中提取 Candidate。

RuleBasedExtractor 不应继续与 LLM 并行参与正式抽取。

建议：

```text
LLM mode:
    LLMExtractor only

offline / testing mode:
    RuleBasedExtractor

LLM failure:
    optional RuleBasedExtractor fallback
```

已有大量正则可以选择性保留，用于：

- 单元测试；
- Benchmark；
- 无模型环境；
- 非 AI 模式；
- 极明确格式文件。

应逐步删除诸如：

```text
_extract_kunming_document_patterns
```

这类项目特定解析逻辑。

---

# 10. Candidate

Candidate 是 LLM 与可信状态之间的接口。

建议结构：

```json
{
  "field_path": "BuildingInfo.StructuralType",
  "value": "RCFrame",
  "status": "extracted",
  "confidence": 0.92,
  "evidence": [
    {
      "source_id": "building_report.docx",
      "location": "page 3 / paragraph 2",
      "text": "The building uses a reinforced concrete frame system."
    }
  ]
}
```

Candidate 不是最终事实。

必须经过：

```text
Candidate validation
        ↓
Working State merge
```

---

# 11. Evidence 必须进一步加强

Evidence 是防幻觉的核心机制。

## 11.1 禁止自动补 Evidence

当前类似：

```text
LLM 给出 value
但 evidence 为空
→ 自动把整个 chunk 当 evidence
```

的行为必须删除。

新的规则：

```text
value != null
AND
status in extracted / confirmed
AND
evidence empty
        ↓
reject candidate
```

或者：

```text
status = uncertain
```

---

## 11.2 Evidence 必须可验证

对于文本来源：

```text
evidence.text
```

原则上应该能够在：

```text
source chunk
```

中找到。

可建立简单验证：

```python
evidence.text in source_text
```

允许轻微归一化：

- 空格；
- 换行；
- 标点；
- 大小写。

这样可以防止 LLM 同时幻觉：

```text
value
+
伪造 evidence
```

---

## 11.3 Derived Evidence

确定性推导应明确标识：

```json
{
  "source_type": "tool",
  "tool": "derive_counts",
  "derived_from": [
    "BuildingInfo.Elevation"
  ]
}
```

而不是伪装成文档证据。

---

# 12. Working State

现有 Working State 设计总体值得保留。

建议继续采用：

```text
missing
extracted
uncertain
derived
inferred
confirmed
conflict
```

其中：

```text
confirmed
extracted
derived
```

可进入 Metadata。

```text
uncertain
inferred
conflict
missing
```

不可进入最终数据。

---

## 12.1 confirmed

只能来自：

```text
用户明确提供
用户明确确认
可信 Metadata 导入
```

---

## 12.2 extracted

只能来自：

```text
资料中存在明确证据
```

---

## 12.3 derived

只能用于：

> 数学或协议意义上唯一确定的结果。

例如：

```text
ElevationNum = len(Elevation)
ChannelNum = len(Channels)
Frequency = 1 / DT
```

---

## 12.4 inferred

任何带工程假设的结果都必须是 inferred。

例如：

```text
根据建筑宽度猜测传感器可能放在 1/6 跨位置
```

即使计算过程完全确定，也不是 `derived`。

这一点必须严格区分：

> deterministic computation ≠ factual derivation

---

# 13. 删除“假设型 Tool”

Tool 中需要重新审查所有所谓确定性推导。

例如当前类似：

```text
已知建筑尺寸
+
每层3个传感器
→ 默认左右+中间位置
```

不能作为普通 derived Tool。

只有在存在明确模板，例如：

```text
layout_standard = "qrest_three_sensor_template_v1"
```

且用户或资料明确指出采用该模板时，才可以调用。

否则应该：

```text
Agent 询问实际布置
```

或：

```text
inferred
```

---

# 14. Validator

Validator 应保持完全确定性。

主要负责：

```text
Schema Validation
Required Validation
Consistency Validation
Evidence Validation
Conflict Validation
Type Validation
```

例如：

```text
ElevationNum == len(Elevation)

ChannelNum == len(Channels)

NPTS > 0

DT > 0

ChannelNo 连续

LocationXYZ 长度 == 3
```

Validator 永远不调用 LLM。

---

# 15. Metadata Export

最终 Metadata 必须满足：

```text
Working State
       ↓
Validator
       ↓
Export Policy
       ↓
Metadata
```

对于字段策略：

```text
mandatory
important
optional
```

可以继续保留。

但必须明确区分：

```text
evidenced
derived
defaulted
blank
blocked
```

默认值永远不能被重新标记为 extracted 或 confirmed。

---

# 16. 最终 Response 必须重新交给 LLM

当前 Python 模板化回复可以保留作为：

```text
debug mode
fallback mode
```

但正式 Agent 模式应增加：

```text
Responder
```

Responder 输入：

```text
user message
conversation context
selected skills
Working State summary
Validator report
tool results
changes in this turn
```

然后由 LLM 生成自然回复。

例如内部上下文：

```json
{
  "new_facts": [
    "BuildingInfo.ProjectName = Kunming_SSJY"
  ],
  "missing_required": [
    "BuildingInfo.GeoLocation.NorthAngle"
  ],
  "conflicts": [],
  "tool_results": []
}
```

LLM 可以自然回复：

> 我已经从资料中确认了项目名称等信息。目前建筑朝向 `NorthAngle` 仍没有可靠来源，这一项不能根据建筑所在地推测。如果有设计图或测点坐标说明，可以继续上传；也可以直接告诉我局部 Y 轴与正北方向的夹角。

而不是程序固定输出：

```text
missing fields:
- BuildingInfo.GeoLocation.NorthAngle
```

---

## 16.1 Response 阶段禁止修改状态

Responder 是纯输出层：

```text
Trusted Context
      ↓
LLM
      ↓
Natural Language
```

不得再产生 Candidate。

这样可以保证：

> 回复可以自由，事实不能自由。

---

# 17. 对话历史

Agent 需要真正具备多轮对话能力。

应保存：

```text
User message
Agent response
important tool events
important state changes
```

但不应每次把所有历史全文塞给模型。

可以维护：

```text
conversation summary
+
recent turns
+
Working State
```

其中工程事实始终以 Working State 为准。

对话历史不能覆盖 Working State。

---

# 18. 用户修改信息

例如：

> 前面建筑长度写错了，应该是 46.9m。

应该由主 Agent 直接识别：

```text
intent = correction
```

产生：

```text
confirmed Candidate
```

然后 Working State 更新。

不建议再建立独立：

```text
ActionInterpreter
```

去作为第二个“半 Agent”。

如果确实需要结构化解析用户修改，可以仍由主 Agent 的 plan/action schema 完成。

目标是减少：

```text
Planner LLM
Extractor LLM
ActionInterpreter LLM
Task Router
```

这种碎片化的“多个小脑”。

---

# 19. qREST 数据读取与生成

这类能力应进一步 Tool 化。

例如：

```text
load_qrest
preflight_qrest
generate_qrest
```

Agent 可以通过 qREST Skill 了解：

```text
什么时候加载
什么时候生成
生成前需要检查什么
哪些错误必须阻断
```

实际执行全部交给 Tool。

不再需要：

```text
QrestDataGenerationHandler
QrestDataLoadingHandler
```

这种专门 workflow class，除非某个流程复杂到 Tool 本身无法表达。

优先尝试：

```text
Agent + Skill + Tools
```

完成。

---

# 20. System Prompt

新的 System Prompt 应尽量稳定、简洁。

只定义：

```text
你是谁
你的目标是什么
你有哪些能力
你的行为边界是什么
Working State 的地位
Evidence 规则
Validator 的权威
```

不要在 System Prompt 中写大量字段知识。

字段专业知识全部移到 Skill。

---

# 21. Tool 调用安全边界

所有 Tool 调用必须经过：

```text
Tool Registry
```

禁止 LLM 直接执行任意 Python/Shell。

Tool Registry 应：

```text
校验 tool 名称
校验参数
执行
捕获异常
返回结构化结果
```

建议逐步给 ToolSpec 增加真正的参数 Schema，而不是只有文字描述。

例如：

```json
{
  "name": "calculate_frequency",
  "arguments": {
    "dt": {
      "type": "number",
      "minimum": 0
    }
  }
}
```

---

# 22. 第一版主 Agent 推荐流程

最终希望达到：

```text
run_turn()

1. ingest input
2. build context

3. LLM intent + skill selection

4. load selected Skills

5. LLM action planning

6. execute actions
   ├─ extraction
   ├─ tools
   └─ state updates

7. deterministic derivations

8. validate Working State

9. determine trusted turn context

10. LLM response

11. persist session
```

这是新的核心。

---

# 23. 建议减少的旧模块

本轮应重点检查并考虑删除：

```text
RuleBasedExtractor 中项目特定正则
ActionInterpreter
TaskCoordinator 类逻辑
TaskHandlerRegistry
QrestDataGenerationHandler
QrestDataLoadingHandler
固定 Python 回复模板
旧 facade
重复 Metadata State
重复 planning abstraction
```

如果某些功能有价值，应迁移为：

```text
Skill
Tool
Validator rule
fallback
```

而不是保留旧架构。

---

# 24. 建议复用的现有实现

优先复用：

### 可以基本保留

```text
WorkingState
FieldState
Evidence
Validator
MetadataExporter
Schema
Metadata Policy
LLM Provider
ArtifactManager
qREST Data Tools
Document ingestion
Skill Registry
```

---

### 需要修改后复用

```text
QrestAgent
ToolRegistry
LLMExtractor
Planner
Dialogue
```

---

### 建议大幅削减或移除

```text
RuleBasedExtractor
ActionInterpreter
Task Handler
固定 workflow
Python response generator
项目特定 regex
假设型 metadata calculator
```

---

# 25. 推荐的重构阶段

## Phase A：清理核心

先建立新的最小核心：

```text
QrestAgent
WorkingState
SkillRegistry
ToolRegistry
Validator
LLMClient
```

删除不必要中间层。

---

## Phase B：Skill 真正接入 Agent

实现：

```text
skill discovery
skill selection
skill loading
skill context injection
```

并确认 Agent 决策确实会受到 Skill 内容影响。

---

## Phase C：统一 Planning

重新设计一个统一的 Plan Schema。

覆盖：

```text
extract
tool
ask
respond
export
```

停止依赖正则 Task Router。

---

## Phase D：重写 Extraction

正式模式只使用：

```text
LLM + Skill
```

规则提取降级成 fallback。

---

## Phase E：强化 Evidence

完成：

```text
no evidence → reject
evidence-source verification
derived evidence
source audit
```

---

## Phase F：LLM Response

引入独立的只读 Responder。

让正式交互真正变成自然对话。

---

## Phase G：删除旧 workflow

最后删除所有：

```text
兼容 facade
旧 Handler
旧 Router
重复状态
重复回复系统
```

---

# 26. 新的验收测试

本轮测试不再只验证“功能是否能跑”，而要验证“系统是否真的表现为 Agent”。

---

## Test 1：Skill 动态选择

用户说：

> 建筑共14层，地下一层，结构为RC框架。

应看到：

```text
selected skill = building_info
```

且 Agent 真正读取 `building_info/SKILL.md`。

---

## Test 2：Skill 改变行为

临时修改 Skill：

```text
StructuralType 必须向用户确认，不允许直接采用文档信息
```

Agent 行为应随之变化。

这可以证明 Skill 不是装饰。

---

## Test 3：没有正则仍能提取

换一种此前从未编写过的自然语言表达：

> The structure consists primarily of reinforced-concrete moment frames.

Agent 仍应正确理解结构类型。

---

## Test 4：禁止伪 Evidence

Mock LLM 返回：

```text
value = RCFrame
evidence = []
```

Candidate 必须被拒绝。

---

## Test 5：伪造 Evidence

Mock LLM 返回文档中不存在的 evidence text。

Candidate 必须被拒绝或降为 uncertain。

---

## Test 6：缺信息

用户仅提供：

> 这是一个14层建筑。

Agent 不生成：

```text
Elevation
StructuralType
NorthAngle
```

---

## Test 7：真正 Derived

已知：

```text
Elevation = [...]
```

自动得到：

```text
ElevationNum
```

状态必须是 `derived`。

---

## Test 8：工程假设不能 Derived

仅知道：

```text
建筑长宽
每层3个传感器
```

不得自动产生具体测点坐标。

---

## Test 9：自然回复

缺少 `NorthAngle` 时，Agent 应生成自然解释和补充建议，而不是只打印 Schema 字段列表。

---

## Test 10：用户修正

用户：

> 前面的长度不对，改为46.9m。

主 Agent 应直接完成 Working State 修改，不依赖第二套 Action Agent。

---

## Test 11：qREST 生成

用户：

> 用当前工程信息和 data.txt 生成 qREST。

Agent：

```text
选择 qrest_data Skill
→ Validator
→ metadata export
→ preflight Tool
→ generate Tool
→ 自然回复
```

而不是进入固定 Python workflow。

---

# 27. 第一阶段暂时不做

仍然不建议引入：

```text
Multi-Agent
复杂 RAG
Vector DB
Agent DAG
长期自主任务
自动联网搜索
自动代码执行
复杂 Plugin Framework
```

先把一个 Agent 做正确。

---

# 28. 完成标准

当系统能够表现为下面这种交互时，本轮重构才算完成：

```text
User:
我这里有一栋昆明的14层RC建筑，这是项目介绍和监测系统Excel。

Agent:
→ 判断这是 Metadata 构建任务
→ 选择 building_info + instrument_info + sensor_layout Skills
→ 读取 Word / Excel
→ LLM 提取有证据的事实
→ Tool 解析通道表
→ Working State 合并
→ Validator
→ 发现 NorthAngle 缺失
→ 自然回复用户目前已确认哪些信息，以及为什么还需要 NorthAngle
```

用户再说：

```text
局部Y轴偏北方向顺时针20°。
```

Agent：

```text
→ 理解为补充信息
→ confirmed
→ Working State
→ Validator ready
→ 告诉用户资料已经满足 Metadata 要求
→ 用户要求时才导出
```

整个过程中不要求用户理解：

```text
BuildingInfo.GeoLocation.NorthAngle
```

这种内部字段。

这才是 qrest-agent 的目标用户体验。

---

# 29. 最终架构原则

本轮开发中始终遵循以下几句话：

> **AI 负责理解、选择和表达。**

> **Skill 负责提供专业判断原则。**

> **Tool 负责可靠执行。**

> **Working State 负责保存事实。**

> **Evidence 负责证明事实从哪里来。**

> **Validator 负责决定数据是否可信。**

> **Metadata 是结果，不是 Agent 的工作空间。**

以及最重要的一条：

> **代码应该约束 AI 的边界，而不是代替 AI 思考。**