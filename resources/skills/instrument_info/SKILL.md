---
name: instrument_info
description: 监测设备、通道和传感器信息
---

# InstrumentInfo 专业知识 Skill

监测设备信息：每个测量通道的测量参数与安装位置。布设完成后基本不变。

## 字段含义

| 字段 | 含义 | 说明 |
| ---- | ---- | ---- |
| Provider | 系统提供者 | 资料明确写明，禁止猜测厂商 |
| ChannelNum | 有效通道总数 | 资料明确给出总数量时可直接确认（即使 Channels 尚未逐通道配置）；当 Channels 数组存在时由 len(Channels) 确定性推导 |
| Channels[].ChannelNo | 通道编号 | 从 1 开始连续递增，最大编号 = ChannelNum |
| Channels[].ChannelID | 通道唯一标识 | 未知时写 "UNKNOWN" 并向用户询问，不编造 |
| Channels[].Measurand | 测量物理量 | Acceleration / Velocity / Displacement 等 |
| Channels[].Scale | 缩放因子 | 包体原始值 × Scale = Units 规定单位；资料给灵敏度时按公式计算 |
| Channels[].Azimuth | 测量方向方位角 | Y 轴正方向为 0°，顺时针 0-360°；竖直方向为 -1 |
| Channels[].LocationXYZ | 局部坐标 | 以建筑底平面几何中心为原点，单位遵循 Units |

## ChannelNum 与 Channels 的关系（方案 §87-§88）

- 如果已有完整 Channels 数组：ChannelNum = len(Channels)（derive_counts 确定性推导）；
- 如果只有总数量（如“系统共布置18个传感器”）：ChannelNum = 18 可以直接确认，
  Channels 保持 missing——这是可接受的中间状态，**不要**因为 Channels 缺失而拒绝 ChannelNum；
- 禁止反向：由 ChannelNum 自动生成 18 个空的 Channels。

## 允许的确定性推导（调用计算 Tool）

- ChannelNum = len(Channels)（derive_counts，Channels 存在时）；
- 通道编号重排：按楼层/位置顺序从 1 连续编号；
- 完整通道表 → table_reader / 逐行提取 Channels 数组（最可靠路径）。
- 注意：当前没有注册的通道布置模板 Tool（derive_channel_layout 已移除）。
  只有资料明确给出完整逐通道配置（位置/方向/量程）时才能生成 Channels；
  仅有“每层几个传感器”这类模糊描述时，Channels 保持 missing 并询问实际布置。

## 必须询问，禁止猜测

- ChannelID：资料未给出时写 "UNKNOWN" 并询问；
- 每层测点数：资料没有明确“每层布置 N 个传感器”时，禁止按默认值生成通道；
- 监测楼层列表：只有“各楼层布置”而无具体楼层时，禁止假设覆盖所有层；
- Scale：资料给出灵敏度（如 100mV/g）时按公式计算；未给出时问；
- Azimuth 缺失：问，不按“典型布置”猜。

## 冲突处理

- 文档说 18 个通道但列出的通道数不是 18 → 冲突；
- 通道编号不连续或重复 → 标出并请用户确认；
- 同一测点两种坐标 → 请用户选择并保留证据。


## 结构严格区分（Schema 硬约束，方案 §44）

- ChannelNum 是 integer（通道总数）；Channels 是 array<object>（完整通道配置数组）。
- “系统共布置18个传感器 / 共有18个通道”只能支持：ChannelNum = 18。
  Channels = 18 是结构非法值，必须拒绝，绝不写入 Working State。
- Channels 必须是完整 channel object 数组（每项含 ChannelNo/ChannelID/Measurand/Scale/Azimuth/LocationXYZ）；
  如果资料只有总数量而没有逐通道配置，则：ChannelNum 可以确认；Channels 保持 missing。
- 禁止用 ChannelNum=18 反向生成 18 个空 Channels；也禁止把数量写进 Channels。
