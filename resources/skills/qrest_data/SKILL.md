---
name: qrest_data
description: qREST 数据文件的加载、预检与生成流程知识
---

# qREST Data Skill

用于处理 .qrest 文件的读取与生成任务。

## 适用场景

- 用户要求读取/解析/导入一个 .qrest 文件；
- 用户要求检查 metadata 与 data 能否生成 qREST；
- 用户要求用当前工程信息与数据文件生成 qREST。

## 生成流程（按顺序调用 Tools）

1. 确定 metadata 来源：显式 metadata.json 路径，或先执行 export 动作
   （从当前 Working State 按导出策略生成，blocked 时停止并向用户说明缺失字段）。
2. 确定 data.txt 路径：必须由用户提供，禁止猜测。
3. 调用 preflight_generate_qrest：有硬错误 → 报告并停止；
   有警告 → 报告警告；严格模式下警告也阻断。
4. 调用 generate_qrest 生成 .qrest 文件，报告产物路径与警告。

## 加载流程

1. 调用 load_qrest 解析 .qrest → loaded_metadata.json / loaded_data.txt。
2. 将 loaded_metadata.json 作为资料提取候选（extract），合并进 Working State。
3. 报告解析结果、与现有状态的差异和冲突。

## 禁止行为

- 不猜测文件路径；
- 不掩盖 preflight 警告；
- 不宣称输入完全一致（除非 preflight 无警告）；
- 不跳过 Validator 直接生成。
