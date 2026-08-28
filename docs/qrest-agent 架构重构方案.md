# qrest-agent 架构重构方案

## 1. 背景

`qrest-agent` 的目标是为 qREST 提供一个基于 AI 的智能信息获取工具。

用户不需要按照固定表格逐项填写工程信息，而是可以通过自然语言对话、上传 Word/PDF/表格/配置文件等方式提供已有资料。Agent 应能够理解这些信息，从不同来源中提取与 qREST 有关的内容，逐步整理为统一的数据结构。

与普通的信息抽取程序相比，qrest-agent 还必须解决一个关键问题：

> 当资料中缺少必要信息时，Agent 应明确识别缺失项并向用户询问，而不能凭经验、常识或概率自行补全工程信息。

因此，qrest-agent 不应只是“LLM + JSON 填写程序”，而应成为一个理解 qREST 专业规范、能够自主使用工具和专业知识、持续维护工程信息状态的专业 Agent。

---

# 2. 最终目标

## 2.1 产品定位

qrest-agent 最终应被定义为：

> 一个面向 qREST 的专业 AI Agent，能够通过自然语言交流和异构资料读取，自主收集、理解、核验和组织工程信息，并最终生成可信、完整且符合 qREST 数据规范的标准化信息。

其核心不是“自动填写字段”，而是：

**理解任务 → 获取证据 → 判断信息 → 使用专业能力 → 发现缺失 → 主动交流 → 完成标准化数据。**

---

## 2.2 用户期望的交互方式

用户可以自由地提供信息，例如：

- 直接通过对话描述工程；
- 上传项目介绍 Word；
- 上传监测系统布置表；
- 上传已有 JSON/YAML 配置；
- 上传数据文件；
- 对 Agent 已提取的信息进行补充、纠正和确认。

Agent 不应要求用户按照程序预设的顺序工作。

例如，用户可以先给建筑资料，再给测点资料；也可以只上传一个包含大量混杂信息的项目报告。

Agent 应根据当前信息状态自主决定：

- 哪些内容与当前任务有关；
- 应读取哪些资料；
- 应使用什么 Skill；
- 是否需要调用 Tool；
- 哪些字段已经确定；
- 哪些字段存在冲突；
- 哪些必要信息仍然缺失；
- 下一步是否需要向用户提问。

---

# 3. 核心设计理念

新的 qrest-agent 应采用：

> **一个主 Agent + 多个 Skills + 多个 Tools + Working State + Schema/Validator**

的总体设计。

其关系可以表示为：

```text
                    用户
             对话 / 文件 / 配置
                     │
                     ▼
              ┌───────────────┐
              │  qREST Agent  │
              │     LLM       │
              └───────┬───────┘
                      │
          ┌───────────┼────────────┐
          ▼           ▼            ▼
       Skills       Tools       Working State
      专业知识      执行能力       当前事实
          │           │            │
          └───────────┼────────────┘
                      ▼
              Schema / Validator
                      │
              ┌───────┴────────┐
              ▼                ▼
          信息不足          信息完整
              │                │
           询问用户        qREST Metadata
```

---

# 4. 主 Agent 的职责

整个系统只需要一个主要 Agent。

它本质上类似一个具有 qREST 专业背景的对话 AI。

Agent 负责：

1. 理解用户当前希望完成什么；
2. 理解用户提供的新信息；
3. 判断哪些信息与 qREST 有关；
4. 判断当前已经掌握哪些事实；
5. 判断需要调用哪些 Skill；
6. 判断是否需要调用 Tool；
7. 合并不同来源的信息；
8. 处理信息冲突；
9. 判断信息是否足以生成最终结果；
10. 主动询问缺失的重要信息；
11. 向用户解释当前状态和结果。

Agent 应拥有决策权。

程序不再通过大量 `if / else` 或固定步骤决定 Agent 接下来应该做什么。

---

# 5. Skill 的定位

Skill 用于向 Agent 提供专业知识和任务处理原则。

Skill 不是业务流程，也不是普通函数。

例如可以逐步建立：

```text
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

    coordinate_system/
        SKILL.md

    unit_normalization/
        SKILL.md
```

例如 `building_info` Skill 可以说明：

- BuildingInfo 各字段的工程含义；
- 哪些字段通常可以从建筑资料中提取；
- 楼层、层数和 Elevation 的关系；
- StructuralFootprint 如何判断；
- 哪些信息可以推导；
- 哪些信息不能根据经验猜测；
- 发现冲突时应怎样处理；
- 哪些缺失项需要向用户询问。

因此 Skill 的作用是：

> **告诉 Agent 在某个专业问题上应该怎样思考。**

而不是代替 Agent 决策。

---

# 6. Tool 的定位

Tool 用于完成确定性的程序操作。

例如：

```text
read_document
read_pdf
read_table
read_metadata

validate_metadata

calculate_frequency
calculate_bounding_box
normalize_unit
normalize_azimuth

inspect_data_file
inspect_channel_table

save_metadata
```

Tool 应尽量：

- 输入明确；
- 输出明确；
- 行为确定；
- 容易测试；
- 不承担整体决策。

例如：

```text
DT = 0.02 s
```

则：

```text
Frequency = 1 / DT = 50 Hz
```

属于确定性关系，应由程序计算，而不是让 Agent 再进行一次语言推理。

类似地：

```text
ElevationNum = len(Elevation)
ChannelNum = len(Channels)
```

也应该由 Tool 或 Validator 自动完成。

当前 qREST Metadata 本身已经具有较严格的 BuildingInfo、InstrumentInfo 和 DataInfo 结构，因此这些结构可以继续作为最终输出契约。

---

# 7. Working State：本次重构的核心

新的 Agent 不应直接修改最终 Metadata。

应增加一个独立的 Working State，用于表示 Agent 当前对工程的理解。

推荐至少记录：

```text
value
status
source / evidence
```

例如：

```json
{
  "BuildingInfo.ProjectName": {
    "value": "Kunming_SSJY",
    "status": "confirmed",
    "evidence": [
      {
        "type": "document",
        "source": "project_description.docx"
      }
    ]
  },

  "BuildingInfo.StructuralType": {
    "value": null,
    "status": "missing",
    "evidence": []
  },

  "BuildingInfo.ElevationNum": {
    "value": 16,
    "status": "derived",
    "derived_from": "BuildingInfo.Elevation"
  }
}
```

推荐至少支持：

```text
confirmed
derived
uncertain
conflict
missing
```

必要时可以增加：

```text
inferred
```

但 `inferred` 默认不能直接进入最终 qREST Metadata。

---

# 8. 防止 AI 胡编的机制

禁止幻觉不能只依赖 Prompt。

系统应从架构上保证：

> **关键工程信息必须存在证据。**

一个字段只有在以下情况之一成立时才能进入最终数据：

### 8.1 用户明确提供

例如：

> 建筑共14层，高47.4 m。

---

### 8.2 从资料中明确提取

例如 Word 中明确写有：

> The building has 14 stories above ground.

---

### 8.3 可以由确定关系计算

例如：

```text
DT = 0.02
→ Frequency = 50 Hz
```

---

如果都不满足，则：

```text
status = missing
```

而不是根据工程经验推测。

例如：

> 14层建筑通常层高约3.3 m。

这种知识只能用于帮助理解问题，不能自动产生：

```text
Elevation = [0, 3.3, 6.6, ...]
```

最终应形成：

```text
事实来源
    ↓
Working State
    ↓
Validator
    ↓
可信 Metadata
```

---

# 9. 当前设计存在的主要问题

根据目前 qrest-agent 的设计思路，本轮重构主要针对以下问题。

## 9.1 AI 不是系统主体

当前实现更接近：

```text
固定程序流程
    ↓
调用 LLM
    ↓
填写指定内容
```

AI 实际承担的是高级解析器的角色。

这种方式虽然可控，但很难体现 Agent 的智能性。

当任务逐渐复杂以后，程序中会不断增加：

- 条件判断；
- 特殊情况；
- 固定问答顺序；
- 字段映射；
- 专用处理路径。

最终容易演变成复杂的传统业务系统。

---

## 9.2 业务逻辑大量固化在代码中

如果程序提前决定：

```text
先处理 BuildingInfo
再处理 InstrumentInfo
最后处理 DataInfo
```

那么用户的信息输入顺序实际上仍被程序控制。

但现实资料通常并不按照 qREST Schema 的顺序组织。

一个项目报告可能同时包含：

- 建筑信息；
- 测点信息；
- 仪器厂家；
- 数据采样率；
- 地震事件；
- 无关工程背景。

这些内容应该由 Agent 自主理解，而不是由程序强行拆分。

---

## 9.3 专业知识、业务流程与代码耦合

当前实现中如果大量专业判断被直接写入 Python 代码，那么每次调整 qREST 的理解原则都需要修改程序。

这些规则中很大一部分实际上更适合成为 Skill。

例如：

```text
如何判断楼层信息是否完整；
什么时候需要询问 NorthAngle；
如何解释 Azimuth；
什么情况下允许从数据文件得到 NPTS；
什么情况下不能推测结构类型。
```

这些属于 Agent 的专业行为规范，而不是普通程序算法。

---

## 9.4 缺少明确的信息来源管理

如果只保存：

```json
"StructuralType": "RCFrame"
```

后续无法判断：

- 用户明确告诉 Agent 的；
- Word 中提取的；
- AI 推断的；
- 默认值；
- 某段旧代码自动填的。

对于工程软件而言，这是一个明显风险。

因此新的系统必须从：

```text
value
```

升级为：

```text
value + status + evidence
```

---

## 9.5 “缺失”与“默认值”容易混淆

当前 qREST C++ Metadata 中大量数值成员采用默认初始化，例如 `double{}` 和 `int{}`。

因此：

```text
Longitude = 0
```

无法天然区分：

```text
真实值为 0
```

和：

```text
尚未获得
```

Agent 工作阶段不能继续沿用这种语义。

Working State 必须显式表示：

```text
missing
```

最终确认完成以后，再生成严格 Metadata。

---

# 10. 本轮重构原则

本次修改是一次较大的架构调整，不应按照普通功能升级处理。

核心原则是：

> **优先得到正确、清晰和可持续的架构，不以兼容旧实现为首要目标。**

具体包括以下原则。

## 10.1 不为兼容性保留错误设计

旧代码是否保留，只判断：

> 它是否符合新的架构职责。

而不是判断：

> 已经写了这么多，删除是不是可惜。

---

## 10.2 可以复用能力，但不复用错误控制关系

例如旧项目中已有：

- 文件解析；
- JSON 操作；
- Schema；
- 数据验证；
- 单位转换；

这些代码可以复用。

但如果某段代码负责：

```text
决定下一步问什么
```

或：

```text
控制固定任务流程
```

则应该重新评估。

---

## 10.3 允许直接删除旧模块

对于明显服务于旧 workflow 的代码：

```text
能删除则删除；
能简化则简化；
不要增加新的 compatibility wrapper。
```

本轮不是迁移企业遗留系统，不需要承担长期 API 兼容责任。

---

## 10.4 不提前设计过多抽象

第一阶段不需要：

- Multi-Agent；
- Agent 编排系统；
- DAG Workflow；
- 大量 Agent 基类；
- 复杂 Plugin 系统。

优先完成：

```text
1 Agent
+
Skills
+
Tools
+
State
+
Validator
```

先把核心交互做正确。

---

# 11. 建议的新目录结构

可以考虑重构为类似：

```text
qrest-agent/

    qrest_agent/
        agent/
            agent.py
            prompt.py

        state/
            working_state.py
            evidence.py

        schema/
            metadata.py
            validation.py

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

        tools/
            document_reader.py
            table_reader.py
            metadata_tools.py
            calculation_tools.py
            validation_tools.py

        llm/
            client.py
            messages.py

        storage/
            session.py
            metadata_store.py

    tests/

    examples/

    docs/

    main.py
```

目录不必立即完全照搬，但职责边界应保持清晰。

---

# 12. 修改计划

## Phase 1：重新定义 Agent

首先停止继续扩展旧 workflow。

建立新的主 Agent，并明确：

```text
Agent 的任务是什么；
Agent 有哪些能力；
Agent 能调用哪些 Tool；
Agent 怎样使用 Skill；
Agent 怎样操作 Working State；
什么时候允许输出 Metadata。
```

同时重新设计 System Prompt。

---

## Phase 2：建立 Working State

这是第一项真正需要实现的基础设施。

至少完成：

```text
FieldState
Evidence
WorkingState
```

并支持：

```text
set
update
missing
conflict
confirm
derive
```

所有 Agent 提取结果首先进入 Working State。

不再直接修改最终 Metadata。

---

## Phase 3：拆分现有代码

逐个检查旧 qrest-agent 模块。

按照下面规则处理：

### 保留

真正确定性的底层能力，例如：

```text
文件读取
JSON读取
字段验证
数学计算
单位转换
保存
```

---

### 改造成 Tool

原本被 workflow 直接调用，但本质属于能力的代码。

例如：

```text
parse_document
inspect_table
calculate_xxx
validate_xxx
```

---

### 改造成 Skill

主要由规则、知识、判断原则构成的逻辑。

例如：

```text
建筑信息应该怎样理解；
测点布置如何判断；
哪些字段允许推导；
哪些字段需要询问。
```

---

### 删除

仅用于维护旧固定流程的代码，例如：

```text
固定阶段状态机；
大量字段级 if/else；
固定询问顺序；
为旧逻辑服务的中间对象；
无实际必要的 Adapter。
```

---

## Phase 4：建立 Skill 系统

第一阶段只需要几个核心 Skill：

```text
metadata
building_info
instrument_info
data_info
```

之后根据实际使用再增加。

Skill 不追求数量。

应该优先保证每个 Skill：

```text
边界清楚；
专业规则明确；
容易修改；
容易独立测试 Agent 行为。
```

---

## Phase 5：建立 Tool 系统

将已有可靠代码整理为 Agent Tools。

优先完成：

```text
document reader
table reader
metadata validator
metadata calculator
metadata writer
```

Tool 应保持小而稳定。

---

## Phase 6：实现 Agent Loop

建立真正由 Agent 驱动的交互：

```text
用户输入
    ↓
Agent理解
    ↓
读取相关 Skill
    ↓
需要时调用 Tool
    ↓
更新 Working State
    ↓
Validator
    ↓
决定：
    ├─继续处理
    ├─询问用户
    └─生成 Metadata
```

程序不预先指定流程。

---

## Phase 7：重新设计验证机制

Validator 至少负责：

### Schema validation

最终数据结构是否合法。

### Required-field validation

必要信息是否存在。

### Consistency validation

例如：

```text
ElevationNum == len(Elevation)

ChannelNum == len(Channels)

Frequency ≈ 1 / DT
```

### Evidence validation

关键字段是否存在可靠来源。

### Conflict validation

不同资料之间是否存在矛盾。

---

# 13. 第一阶段不建议实现的内容

本轮应控制范围，暂时不要过早开发：

- 多 Agent 系统；
- 自动长期记忆；
- RAG 知识库；
- Agent 自主联网搜索；
- 大规模向量数据库；
- 自动规划复杂工作流；
- GUI 中的高级 Agent 可视化；
- 大量可配置 Workflow。

这些能力未来都可能有价值，但不是当前架构的核心。

当前首先应解决：

> Agent 是否真正成为系统的决策主体。

---

# 14. 重构完成后的验收标准

本轮重构不能只以“程序还能运行”作为成功标准。

应至少满足以下测试。

### 测试 1：自由输入

用户一次性提供大量无结构文本。

Agent 能自主提取多个类别的信息，而不依赖固定步骤。

---

### 测试 2：资料上传

用户上传工程文档。

Agent 能调用文件工具读取，并从中提取相关信息。

---

### 测试 3：信息缺失

资料中缺少关键字段。

Agent 明确告诉用户：

```text
目前仍缺少哪些信息
```

而不是生成默认值。

---

### 测试 4：信息冲突

用户输入与文档内容存在冲突。

Agent 标记 `conflict` 并请求确认。

---

### 测试 5：确定性推导

已知：

```text
DT = 0.02
```

Agent 不再询问 Frequency，而通过 Tool 得到：

```text
50 Hz
```

---

### 测试 6：多轮修正

用户后续说：

> 前面的建筑长度写错了，应该是46.9 m。

Agent 可以更新 State，并保留新的证据状态。

---

### 测试 7：最终导出

只有在必要字段满足要求后，才将 Working State 转换为正式 qREST Metadata。

---

# 15. 本轮重构的最终方向

新的 qrest-agent 不应继续沿着：

```text
程序定义流程
+
AI帮助填写
```

发展。

而应改为：

```text
AI Agent
    ↓
理解和决策
    ↓
Skill 提供专业知识
    ↓
Tool 提供可靠能力
    ↓
Working State 保存事实
    ↓
Validator 保证可信
    ↓
qREST Metadata
```

可以把整个架构总结为一句话：

> **LLM 负责理解与决策，Skill 负责专业知识，Tool 负责确定性执行，State 负责保存事实和证据，Validator 负责守住最终数据质量。**

本轮修改应视为 qrest-agent 的一次重新设计。

旧项目的意义是提供已经验证过的代码、经验和数据结构，而不是限制新的架构。

因此开发过程中应始终坚持：

> **复用有价值的能力，而不是继承历史包袱。**