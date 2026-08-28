# InstrumentInfo 专业知识 Skill

监测设备信息：每个测量通道的测量参数与安装位置。布设完成后基本不变。

## 字段含义

| 字段 | 含义 | 说明 |
| ---- | ---- | ---- |
| Provider | 系统提供者 | 资料明确写明，禁止猜测厂商 |
| ChannelNum | 有效通道总数 | 必须等于 Channels 数组长度 |
| Channels[].ChannelNo | 通道编号 | 从 1 开始连续递增，最大编号 = ChannelNum |
| Channels[].ChannelID | 通道唯一标识 | 未知时写 "UNKNOWN" 并向用户询问，不编造 |
| Channels[].Measurand | 测量物理量 | Acceleration / Velocity / Displacement 等 |
| Channels[].Scale | 缩放因子 | 包体原始值 × Scale = Units 规定单位；资料给灵敏度时按公式计算 |
| Channels[].Azimuth | 测量方向方位角 | Y 轴正方向为 0°，顺时针 0-360°；竖直方向为 -1 |
| Channels[].LocationXYZ | 局部坐标 | 以建筑底平面几何中心为原点，单位遵循 Units |

## 允许的确定性推导（调用计算 Tool）

- ChannelNum = len(Channels)（derive_counts）；
- 通道编号重排：按楼层/位置顺序从 1 连续编号；
- 已知监测楼层、每层测点数与平面尺寸时的布置生成（derive_channel_layout）：
  仅当资料明确给出每层测点数（当前支持每层 3 个：左右 + 中部）与楼层列表时使用；
  该布局约定（x_edge、y 线、Azimuth）是确定性约定，必须在证据中记录。

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
