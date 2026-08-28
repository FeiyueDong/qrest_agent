# DataInfo 专业知识 Skill

数据包信息：时序数据的采集时间与采样参数。

## 字段含义

| 字段 | 含义 | 说明 |
| ---- | ---- | ---- |
| EventName | 事件唯一标识 | 如 "2025_MYANMAR_7.9"，只取资料明确写法 |
| StartTime | 记录起始时间 | ISO 8601 且含时区，如 2025-03-28T14:20:00.000+08:00 |
| NPTS | 采样点数 | 各通道一致；必须与数据文件行数一致（由 preflight 校验） |
| DT | 采样间隔 | 单位遵循 Units（通常 s），必须为正值 |
| Corrected | 数据是否处理过 | "NULL" 表示原始未处理数据；只取资料明确写法 |

## 允许的确定性推导（调用计算 Tool）

- Frequency = 1 / DT（calculate_frequency）：DT=0.02 → 50 Hz；
  派生值只作为展示/辅助，不新增 qREST 必填字段；
- NPTS 与数据行数的核对由 preflight_generate_qrest / inspect_data_txt 完成，
  不要把不一致当作可忽略的细节。

## 必须询问，禁止猜测

- StartTime：资料只有日期没有时刻/时区时问；
- DT：资料说“采样率 100Hz”时可以推导 DT=0.01（确定性关系 DT = 1/采样率），
  需记录 derived_from 与证据；
- NPTS：资料没有数据文件时问；不要按时长估算；
- Corrected：资料未提及时保持 missing，不默认 "NULL"。

## 冲突处理

- 采样间隔与采样率矛盾 → 冲突，请用户确认；
- NPTS 与数据行数不一致 → 由 preflight 报告为警告/错误，不静默修正；
- 事件名/时间在文档不同位置不一致 → 列出出处请用户选择。
