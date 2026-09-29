"""演示掩模与预置场景（PostgreSQL 与内存存储共用同一份种子数据）。

掩模设计面向 10 MHz 带宽载波（标称频段半宽 = 5 MHz）：
* mask_rect  —— 陡降矩形，频段外快速压制；
* mask_slow  —— 缓降尾部，用来制造“功率不同导致尾部泄漏”的定位例子。
"""
from __future__ import annotations


def demo_masks() -> list[dict]:
    return [
        {
            "name": "mask_rect",
            "points": [
                {"offset": 0.0, "attenuation_db": 0.0},
                {"offset": 5.0, "attenuation_db": 0.0},
                {"offset": 6.0, "attenuation_db": 30.0},
                {"offset": 10.0, "attenuation_db": 70.0},
                {"offset": 20.0, "attenuation_db": 100.0},
            ],
        },
        {
            "name": "mask_slow",
            "points": [
                {"offset": 0.0, "attenuation_db": 0.0},
                {"offset": 5.0, "attenuation_db": 0.0},
                {"offset": 7.0, "attenuation_db": 25.0},
                {"offset": 10.0, "attenuation_db": 45.0},
                {"offset": 15.0, "attenuation_db": 60.0},
                {"offset": 30.0, "attenuation_db": 80.0},
            ],
        },
    ]


def demo_scenarios() -> list[dict]:
    # 1) 同带宽不同功率：保护带不足 + 掩模尾部越界 + 频段重叠
    case_conflicts = {
        "name": "核对用例：同带宽不同功率",
        "band_start": 1430.0,
        "band_stop": 1530.0,
        "guard_mhz": 2.0,
        "cross_pol_rule": "deny",
        "spurious_limit_dbm": -13.0,
        "tail_threshold_db": 10.0,
        "noise_floor_dbm": -110.0,
        "default_mask_name": "mask_slow",
        "carriers": [
            {"name": "载波A", "fc": 1445.0, "bandwidth": 10.0,
             "power_dbm": 43.0, "polarization": "H", "mask_name": None},
            {"name": "载波B", "fc": 1455.3, "bandwidth": 10.0,
             "power_dbm": 46.0, "polarization": "V", "mask_name": None},
            {"name": "载波C", "fc": 1480.0, "bandwidth": 10.0,
             "power_dbm": 40.0, "polarization": "H", "mask_name": None},
            {"name": "载波D", "fc": 1488.0, "bandwidth": 10.0,
             "power_dbm": 36.0, "polarization": "V", "mask_name": None},
        ],
        # 预期：A-B 间隙 0.3<2（GUARD_SHORTAGE）且双向 TAIL_LEAK；
        #       C-D 重叠 2 MHz（OVERLAP）。全部定位到具体载波对。
    }

    # 2) 异极化复用：规则 unknown，全部为待评估告警
    case_crosspol = {
        "name": "核对用例：异极化复用待评估",
        "band_start": 2400.0,
        "band_stop": 2460.0,
        "guard_mhz": 5.0,
        "cross_pol_rule": "unknown",
        "spurious_limit_dbm": -13.0,
        "tail_threshold_db": 10.0,
        "noise_floor_dbm": -110.0,
        "default_mask_name": "mask_rect",
        "carriers": [
            {"name": "H-1", "fc": 2412.0, "bandwidth": 10.0,
             "power_dbm": 40.0, "polarization": "H", "mask_name": None},
            {"name": "V-1", "fc": 2412.0, "bandwidth": 10.0,
             "power_dbm": 40.0, "polarization": "V", "mask_name": None},
            {"name": "H-2", "fc": 2432.0, "bandwidth": 10.0,
             "power_dbm": 38.0, "polarization": "H", "mask_name": None},
            {"name": "V-2", "fc": 2442.0, "bandwidth": 10.0,
             "power_dbm": 35.0, "polarization": "V", "mask_name": None},
        ],
        # 预期：H-1/V-1 重叠 -> PENDING_ISOLATION + OVERLAP(warning)；
        #       H-2/V-2 间隙 0<5 -> PENDING + GUARD_SHORTAGE + 尾部(warning)。
    }

    # 3) OR-Tools：录入时拥挤重叠，交给求解器重排
    case_assign = {
        "name": "OR-Tools：拥挤频段重排",
        "band_start": 3600.0,
        "band_stop": 3660.0,
        "guard_mhz": 2.0,
        "cross_pol_rule": "deny",
        "spurious_limit_dbm": -13.0,
        "tail_threshold_db": 10.0,
        "noise_floor_dbm": -110.0,
        "default_mask_name": "mask_rect",
        "carriers": [
            {"name": "C1", "fc": 3608.0, "bandwidth": 10.0,
             "power_dbm": 30.0, "polarization": "H", "mask_name": None},
            {"name": "C2", "fc": 3612.0, "bandwidth": 10.0,
             "power_dbm": 33.0, "polarization": "H", "mask_name": None},
            {"name": "C3", "fc": 3616.0, "bandwidth": 10.0,
             "power_dbm": 28.0, "polarization": "V", "mask_name": None},
            {"name": "C4", "fc": 3620.0, "bandwidth": 10.0,
             "power_dbm": 31.0, "polarization": "H", "mask_name": None},
            {"name": "C5", "fc": 3624.0, "bandwidth": 10.0,
             "power_dbm": 35.0, "polarization": "V", "mask_name": None},
        ],
        # 5x10 MHz + 4x2 MHz 保护 = 58 <= 60 MHz，求解器可给出可行重排。
    }
    return [case_conflicts, case_crosspol, case_assign]
