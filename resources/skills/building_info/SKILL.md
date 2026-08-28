---
name: building_info
description: 建筑位置、结构类型、尺寸、标高等工程信息
---

# BuildingInfo 专业知识 Skill

建筑信息：监测对象的位置与几何参数。建筑施工完成后基本不变。

## 字段含义

| 字段 | 含义 | 说明 |
| ---- | ---- | ---- |
| ProjectName | 项目/建筑唯一标识 | 用户命名或文档标题 |
| GeoLocation.Longitude/Latitude | 绝对地理位置 | 必须由用户或资料明确提供，禁止根据城市名猜测 |
| GeoLocation.NorthAngle | 局部 Y 轴与正北夹角 | 0°=Y 轴朝北；270°=Y 轴朝东；必须提供，禁止猜测 |
| StructuralType | 结构类型 | SteelFrame / RCFrame / ShearWall / Masonry 等；只取资料明确写法 |
| StructuralFootprint.Shape | 底平面形状 | Rectangular / Circular / Polygon 等 |
| StructuralFootprint.Parameters | 形状参数 | 矩形={Length, Width}；圆形={Radius}；多边形=顶点数组 |
| StructuralFootprint.BoundingBox | 外接包围盒 | 以几何中心为原点的 MaxX/MinX/MaxY/MinY |
| ElevationNum | 标高层数 | 含地下室、地坪、各楼层与屋顶 |
| Elevation | 绝对标高数组 | 负值为地下；长度必须等于 ElevationNum |

## 允许的确定性推导（调用计算 Tool）

- ElevationNum = len(Elevation)（derive_counts）；
- 矩形轮廓：BoundingBox = {MaxX: Length/2, MinX: -Length/2, MaxY: Width/2, MinY: -Width/2}
  （calculate_bounding_box）；
- 由“地上层数 + 地下层数 + 首层层高 + 标准层层高”确定生成标高序列
  （derive_elevation_profile，规则：地下保留一个代表标高、正负零为 0.0、
  第 N 层 = 首层 + (N-1) × 标准层高）。仅当资料给出全部层高参数时才可推导。

## 必须询问，禁止猜测

- 经纬度、NorthAngle：资料没有时只能问；
- StructuralType：资料未明确写“钢框架/钢筋混凝土框架/剪力墙”等字样时不能推断；
- Elevation 全序列：资料只有层数没有层高时，不能按“通常 3.3m”补全；
- 楼层数（ElevationNum）：应优先由 Elevation 长度推导；若资料说“地上 14 层”，
  需与“是否含地下室/屋顶”核对，避免与文档描述的标高数冲突。

## 冲突处理

- 文档标高数与层数不一致 → 标出双方证据，请用户确认；
- 不同资料的结构类型写法不同（如 SteelFrame vs 钢框架）→ 确认后再规范化；
- 楼层高度与总高度矛盾 → 冲突，请用户提供权威来源。


## 结构严格区分（Schema 硬约束，方案 §45）

- ElevationNum 是 integer（标高层数）；Elevation 是 array<number>（绝对标高数组）。
- “建筑有16个标高层”只能支持：ElevationNum = 16。
  Elevation = 16 是结构非法值，必须拒绝，绝不写入 Working State。
- 只有明确层高或标高数据时才能生成 Elevation = [...]；只有层数而没有层高时 Elevation 保持 missing。
