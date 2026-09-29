"""Pydantic 数据模型 —— 全部频率单位 MHz，功率 dBm（仅展示），内部线性换算 mW。"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Polarization(str, Enum):
    H = "H"   # 水平极化
    V = "V"   # 垂直极化
    X = "X"   # 未指定/其他


class CrossPolRule(str, Enum):
    """相同频段在不同极化下能否复用的输入规则。"""
    ALLOW = "allow"      # 允许复用（已知隔离度足够）
    DENY = "deny"        # 不允许复用
    UNKNOWN = "unknown"  # 未知隔离度 -> 待评估


class MaskPoint(BaseModel):
    offset: float = Field(..., description="距载波中心的频偏绝对值 MHz（>=0）")
    attenuation_db: float = Field(..., description="该频偏处的掩模衰减 dB（正数）")


class Mask(BaseModel):
    id: Optional[int] = None
    name: str
    points: list[MaskPoint] = Field(default_factory=list)


class MaskIn(BaseModel):
    name: str
    points: list[MaskPoint]


class Carrier(BaseModel):
    id: Optional[int] = None
    name: str
    fc: float = Field(..., description="中心频率 MHz")
    bandwidth: float = Field(..., gt=0, description="带宽 MHz")
    power_dbm: float = Field(..., description="载波功率 dBm")
    polarization: Polarization = Polarization.X
    mask_name: Optional[str] = Field(
        None, description="掩模名称；为空时使用场景默认掩模"
    )


class Scenario(BaseModel):
    id: Optional[int] = None
    name: str
    band_start: float = Field(..., description="允许频段起点 MHz")
    band_stop: float = Field(..., description="允许频段终点 MHz")
    guard_mhz: float = Field(0.0, ge=0, description="保护间隔（频段边缘间隙）MHz")
    cross_pol_rule: CrossPolRule = CrossPolRule.DENY
    spurious_limit_dbm: float = Field(
        -13.0, description="允许频段外的杂散发射限值 dBm/MHz"
    )
    tail_threshold_db: float = Field(
        10.0, ge=0,
        description="尾部泄漏保护裕度 dB：干扰尾部须低于受害载波功率该裕度；"
                    "门限不低于底噪"
    )
    noise_floor_dbm: float = Field(-110.0, description="底噪 dBm/MHz")
    default_mask_name: Optional[str] = None
    carriers: list[Carrier] = Field(default_factory=list)


class ScenarioIn(BaseModel):
    name: str
    band_start: float
    band_stop: float
    guard_mhz: float = 0.0
    cross_pol_rule: CrossPolRule = CrossPolRule.DENY
    spurious_limit_dbm: float = -13.0
    tail_threshold_db: float = 10.0
    noise_floor_dbm: float = -110.0
    default_mask_name: Optional[str] = None
    carriers: list[Carrier] = Field(default_factory=list)


class Conflict(BaseModel):
    code: str
    severity: str = Field(..., description="error | warning | info")
    message: str
    carriers: list[str] = Field(default_factory=list, description="冲突定位到的载波（对）")
    detail: dict = Field(default_factory=dict)


class PowerSummary(BaseModel):
    total_mw: float
    total_dbm: float
    per_carrier_mw: dict[str, float]


class AnalysisResult(BaseModel):
    scenario_name: str
    power_summary: PowerSummary
    conflicts: list[Conflict]
    error_count: int
    warning_count: int
    traces: dict[str, list[dict]] = Field(
        default_factory=dict,
        description="每载波频谱曲线 {carrier: [{x_mhz, y_dbm}, ...]}",
    )


class AssignRequest(BaseModel):
    scenario: ScenarioIn
    fixed: dict[str, float] = Field(
        default_factory=dict, description="固定不动的载波 {名称: 中心频率 MHz}"
    )


class AssignSolution(BaseModel):
    status: str = Field(..., description="OPTIMAL | FEASIBLE | INFEASIBLE | UNKNOWN")
    positions: dict[str, float] = Field(default_factory=dict)
    message: str = ""
    objective_hz: Optional[int] = None


class Health(BaseModel):
    status: str
    storage: str = Field(..., description="postgres | memory")
