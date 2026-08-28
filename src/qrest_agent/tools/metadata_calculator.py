from __future__ import annotations

"""确定性计算工具（方案 §6：计算类 Tool 的职责边界）。

这些函数只做“输入明确、输出明确、行为确定”的计算，不做任何决策：
- ElevationNum / ChannelNum 等计数由数组长度推导；
- Frequency 由 DT 确定计算（1/DT）；
- 楼层标高序列由层高参数确定生成；
- 通道布置由监测楼层、每层测点数与建筑平面尺寸确定生成；
- Azimuth 归一化、矩形包围盒计算。

Agent 或规则提取器应先把文本中的参数解析出来，再调用这些函数。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ElevationProfile:
    """楼层标高剖面：由层高参数确定的标高序列。"""

    above_ground_floors: int
    basement_floors: int
    first_floor_height: float
    typical_above_height: float
    basement_first_height: float | None
    basement_second_height: float | None
    elevations: list[float]

    def monitored_floor_height(self, floor: str | int) -> float | None:
        if floor == "B1F":
            return self.elevations[0] if self.elevations and self.elevations[0] < 0 else None
        if floor == 1:
            return 0.0
        if isinstance(floor, int) and floor > 1:
            return _round_m(self.first_floor_height + (floor - 1) * self.typical_above_height)
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "above_ground_floors": self.above_ground_floors,
            "basement_floors": self.basement_floors,
            "first_floor_height": self.first_floor_height,
            "typical_above_height": self.typical_above_height,
            "basement_first_height": self.basement_first_height,
            "basement_second_height": self.basement_second_height,
            "elevations": list(self.elevations),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ElevationProfile":
        return cls(
            above_ground_floors=int(data["above_ground_floors"]),
            basement_floors=int(data["basement_floors"]),
            first_floor_height=float(data["first_floor_height"]),
            typical_above_height=float(data["typical_above_height"]),
            basement_first_height=data.get("basement_first_height"),
            basement_second_height=data.get("basement_second_height"),
            elevations=list(data.get("elevations", [])),
        )


def derive_elevation_profile(
    above_ground_floors: int,
    basement_floors: int,
    first_floor_height: float,
    typical_above_height: float,
    basement_first_height: float | None = None,
    basement_second_height: float | None = None,
) -> ElevationProfile:
    """由层数/层高参数生成绝对标高序列（含地下室代表标高与正负零）。

    规则（保持与既有测试案例一致的确定性约定）：
    - 地下室最多保留一个代表标高：优先地下第二层，其次地下第一层；
    - 正负零固定为 0.0；
    - 地上第 N 层标高 = 首层高度 + (N-1) * 标准层层高。
    """
    elevations: list[float] = []
    if basement_floors > 0:
        if basement_floors >= 2 and basement_second_height is not None:
            elevations.append(_round_m(-basement_second_height))
        elif basement_first_height is not None:
            elevations.append(_round_m(-basement_first_height))
    elevations.append(0.0)
    for index in range(above_ground_floors):
        elevations.append(_round_m(first_floor_height + index * typical_above_height))
    return ElevationProfile(
        above_ground_floors=above_ground_floors,
        basement_floors=basement_floors,
        first_floor_height=first_floor_height,
        typical_above_height=typical_above_height,
        basement_first_height=basement_first_height,
        basement_second_height=basement_second_height,
        elevations=elevations,
    )


def derive_elevation_num(elevations: list[Any]) -> int:
    return len(elevations)


def derive_channel_num(channels: list[Any]) -> int:
    return len(channels)


def calculate_frequency(dt: float) -> float:
    """DT → Frequency = 1 / DT（采样间隔的单位由 Units 规定）。"""
    value = float(dt)
    if value <= 0:
        raise ValueError(f"DT must be positive, got {dt}")
    return 1.0 / value


def calculate_bounding_box(length: float, width: float) -> dict[str, float]:
    """矩形结构轮廓 → 以几何中心为原点的外接包围盒。"""
    return {
        "MaxX": float(length) / 2,
        "MinX": -float(length) / 2,
        "MaxY": float(width) / 2,
        "MinY": -float(width) / 2,
    }


def normalize_azimuth(azimuth: float) -> float:
    """方位角归一化：-1（竖直方向）保留，其余映射到 [0, 360)。"""
    value = float(azimuth)
    if value == -1:
        return -1.0
    return value % 360.0


def build_channel_layout(
    monitored_floors: list[str | int],
    profile: ElevationProfile,
    footprint_length: float,
    footprint_width: float,
    device_type: str | None = None,
    per_floor_count: int = 3,
) -> list[dict[str, Any]]:
    """由监测楼层与平面尺寸生成确定性的通道布置。

    约定（与既有测试案例一致）：
    - 每层 3 个测点：左右两侧（X = ±x_edge，Azimuth=90°）与中部（X=0，Azimuth=0°）；
    - x_edge = max(长度/2 - 0.4, 长度/2 * 0.95)，y 线 = -宽度/6；
    - ChannelNo 从 1 起连续递增；ChannelID 未知时写 "UNKNOWN"（待用户确认，不猜测）；
    - 仅当每层测点数明确为 3 时才生成（其余情况返回空列表，交由询问）。
    """
    if per_floor_count != 3:
        return []
    x_edge = _round_m(max(footprint_length / 2 - 0.4, footprint_length / 2 * 0.95), digits=1)
    y_line = _round_m(-footprint_width / 6, digits=1)
    channel_templates = [
        (-x_edge, y_line, 90.0),
        (x_edge, y_line, 90.0),
        (0.0, y_line, 0.0),
    ]

    channels: list[dict[str, Any]] = []
    channel_no = 1
    for floor in monitored_floors:
        z = profile.monitored_floor_height(floor)
        if z is None:
            return []
        for x, y, azimuth in channel_templates:
            channel: dict[str, Any] = {
                "ChannelNo": channel_no,
                "ChannelID": "UNKNOWN",
                "Measurand": "Acceleration",
                "Scale": 1.0,
                "Azimuth": azimuth,
                "LocationXYZ": [_round_m(x, digits=1), _round_m(y, digits=1), _round_m(z, digits=1)],
            }
            if device_type is not None:
                channel["DeviceType"] = device_type
            channels.append(channel)
            channel_no += 1
    return channels


def _round_m(value: float, digits: int = 3) -> float:
    rounded = round(float(value), digits)
    return 0.0 if rounded == -0.0 else rounded
