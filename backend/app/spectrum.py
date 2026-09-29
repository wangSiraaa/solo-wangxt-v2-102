"""频谱分析核心：掩模尾部插值、冲突检测、线性域功率汇总。

约定
----
* 频率一律 MHz，功率对外 dBm；求和等线性运算一律先换算 mW。
* 掩模点为 (|频偏|, 衰减dB)，频偏超出定义范围时取端点衰减（平台外推）。
* 仅离线简化模型：矩形/折线发射掩模，不连接任何无线电设备。
"""
from __future__ import annotations

import numpy as np
from scipy.interpolate import interp1d

from .models import (
    AnalysisResult,
    Carrier,
    Conflict,
    CrossPolRule,
    Mask,
    PowerSummary,
    Scenario,
)


# ---------------------------------------------------------------------------
# 基础换算
# ---------------------------------------------------------------------------
def dbm_to_mw(dbm: float) -> float:
    return 10.0 ** (dbm / 10.0)


def mw_to_dbm(mw: float) -> float:
    if mw <= 0:
        return -np.inf
    return 10.0 * np.log10(mw)


def mask_attenuation(mask: Mask | None) -> interp1d:
    """返回 f(offset_mhz >= 0) -> attenuation_db 的单调查表函数。

    未提供掩模时按理想矩形（带内 0 dB、带外无穷衰减）处理，
    简化为 bw/2 以内 0、以外 200 dB。
    """
    if mask is None or not mask.points:
        offs = np.array([0.0, 1e-9, 1.0])
        atts = np.array([0.0, 200.0, 200.0])
    else:
        pts = sorted(mask.points, key=lambda p: p.offset)
        offs = np.array([max(0.0, p.offset) for p in pts])
        atts = np.array([p.attenuation_db for p in pts])
    # np.interp 语义：超出范围按端点值外推（掩模平台）
    return lambda x: np.interp(np.asarray(x, dtype=float), offs, atts)


def _carrier_mask(scn: Scenario, c: Carrier, masks: dict[str, Mask]) -> Mask | None:
    name = c.mask_name or scn.default_mask_name
    return masks.get(name) if name else None


def _edges(c: Carrier) -> tuple[float, float]:
    return c.fc - c.bandwidth / 2.0, c.fc + c.bandwidth / 2.0


def _is_cross_pol(a: Carrier, b: Carrier) -> bool:
    """仅 H/V 明确正交才算不同极化；X（未指定）不能主张极化隔离。"""
    return {a.polarization.value, b.polarization.value} == {"H", "V"}


# ---------------------------------------------------------------------------
# 主分析
# ---------------------------------------------------------------------------
def analyze(scn: Scenario, masks: dict[str, Mask]) -> AnalysisResult:
    conflicts: list[Conflict] = []

    # 配置合法性
    if scn.band_stop <= scn.band_start:
        conflicts.append(Conflict(
            code="CONFIG_ERROR", severity="error",
            message="频段终点必须大于起点",
        ))
    names = [c.name for c in scn.carriers]
    if len(set(names)) != len(names):
        dup = {n for n in names if names.count(n) > 1}
        conflicts.append(Conflict(
            code="CONFIG_ERROR", severity="error",
            message=f"载波名称重复：{sorted(dup)}", carriers=sorted(dup),
        ))

    carriers = scn.carriers
    att_funcs = {c.name: mask_attenuation(_carrier_mask(scn, c, masks))
                 for c in carriers}

    # ---- 功率汇总：在线性域 mW 求和，再转回 dB --------------------------
    per_mw = {c.name: dbm_to_mw(c.power_dbm) for c in carriers}
    total_mw = float(sum(per_mw.values()))
    power_summary = PowerSummary(
        total_mw=total_mw,
        total_dbm=float(mw_to_dbm(total_mw)),
        per_carrier_mw=per_mw,
    )

    tail_margin = scn.tail_threshold_db  # 相对受害载波功率要求的保护裕度 dB

    # ---- 单载波检查：越出频段、频段边缘掩模杂散 --------------------------
    for c in carriers:
        lo, hi = _edges(c)
        att = att_funcs[c.name]
        if lo < scn.band_start or hi > scn.band_stop:
            conflicts.append(Conflict(
                code="BAND_OUTSIDE", severity="error",
                message=(f"载波 {c.name} 的标称频段 [{lo:.3f}, {hi:.3f}] MHz "
                         f"越出允许频段 [{scn.band_start}, {scn.band_stop}] MHz"),
                carriers=[c.name],
                detail={"edge_lo": lo, "edge_hi": hi},
            ))
        # 频段边缘处的掩模电平（杂散）。仅当载波边缘严格落在频段内部
        # （不贴齐边界，贴齐时掩模平台自然过渡到带外）时评估。
        if scn.band_stop > scn.band_start:
            if lo > scn.band_start + 1e-12 and c.fc >= scn.band_start:
                off_left = max(0.0, c.fc - scn.band_start)
                lvl = c.power_dbm - float(att(off_left))
                if lvl > scn.spurious_limit_dbm:
                    conflicts.append(Conflict(
                        code="SPURIOUS_EDGE", severity="error",
                        message=(f"载波 {c.name} 掩模在低频段边缘 {scn.band_start} MHz "
                                 f"处电平 {lvl:.1f} dBm，超过杂散限值 "
                                 f"{scn.spurious_limit_dbm:.1f} dBm"),
                        carriers=[c.name],
                        detail={"edge_mhz": scn.band_start, "level_dbm": lvl,
                                "limit_dbm": scn.spurious_limit_dbm},
                    ))
            if hi < scn.band_stop - 1e-12 and c.fc <= scn.band_stop:
                off_right = max(0.0, scn.band_stop - c.fc)
                lvl = c.power_dbm - float(att(off_right))
                if lvl > scn.spurious_limit_dbm:
                    conflicts.append(Conflict(
                        code="SPURIOUS_EDGE", severity="error",
                        message=(f"载波 {c.name} 掩模在高频段边缘 {scn.band_stop} MHz "
                                 f"处电平 {lvl:.1f} dBm，超过杂散限值 "
                                 f"{scn.spurious_limit_dbm:.1f} dBm"),
                        carriers=[c.name],
                        detail={"edge_mhz": scn.band_stop, "level_dbm": lvl,
                                "limit_dbm": scn.spurious_limit_dbm},
                    ))

    # ---- 载波对检查 -------------------------------------------------------
    for i in range(len(carriers)):
        for j in range(i + 1, len(carriers)):
            a, b = carriers[i], carriers[j]
            lo_a, hi_a = _edges(a)
            lo_b, hi_b = _edges(b)
            gap = max(lo_a, lo_b) - min(hi_a, hi_b)  # >0 有间隙, <0 重叠
            overlap = max(lo_a, lo_b) < min(hi_a, hi_b)

            cross = _is_cross_pol(a, b)
            if cross and scn.cross_pol_rule == CrossPolRule.ALLOW:
                conflicts.append(Conflict(
                    code="CROSSPOL_REUSE", severity="info",
                    message=(f"载波 {a.name}({a.polarization.value}) 与 "
                             f"{b.name}({b.polarization.value}) 异极化，"
                             f"按输入规则允许同频段复用，跳过间隔检查"),
                    carriers=[a.name, b.name],
                ))
                continue

            pending = cross and scn.cross_pol_rule == CrossPolRule.UNKNOWN
            severity = "warning" if pending else "error"

            # 仅当几何上确有交互（重叠/保护带不足）时才提示隔离度待评估，
            # 相距很远的异极化载波无需人工评估隔离度。
            if pending and (overlap or gap < scn.guard_mhz - 1e-12):
                conflicts.append(Conflict(
                    code="PENDING_ISOLATION", severity="warning",
                    message=(f"载波 {a.name}({a.polarization.value}) 与 "
                             f"{b.name}({b.polarization.value}) 异极化，但隔离度"
                             f"未知，复用可行性待评估；以下几何检查结果仅供参考"),
                    carriers=[a.name, b.name],
                ))

            if overlap:
                ov = -gap
                conflicts.append(Conflict(
                    code="OVERLAP", severity=severity,
                    message=(f"载波 {a.name} 与 {b.name} 标称频段重叠 "
                             f"{ov:.3f} MHz"
                             + ("（异极化隔离度待评估）" if pending else "")),
                    carriers=[a.name, b.name],
                    detail={"overlap_mhz": ov, "pending_isolation": pending},
                ))
                continue  # 已重叠时不再讨论保护带与尾部

            if gap < scn.guard_mhz - 1e-12:
                conflicts.append(Conflict(
                    code="GUARD_SHORTAGE", severity=severity,
                    message=(f"载波 {a.name} 与 {b.name} 频段间隙 {gap:.3f} MHz，"
                             f"小于保护间隔 {scn.guard_mhz:.3f} MHz"
                             f"（差 {scn.guard_mhz - gap:.3f} MHz）"
                             + ("（异极化隔离度待评估）" if pending else "")),
                    carriers=[a.name, b.name],
                    detail={"gap_mhz": gap, "guard_mhz": scn.guard_mhz,
                            "shortage_mhz": scn.guard_mhz - gap,
                            "pending_isolation": pending},
                ))

            # 尾部越界检查：left->right 与 right->left 两个方向分别定位。
            # 越界门限按受害载波功率定义（要求尾部比受害载波低 margin dB），
            # 同时不低于底噪——低于底噪的泄漏无害。
            left, right = (a, b) if hi_a <= lo_b else (b, a)
            lo_l, hi_l = _edges(left)
            lo_r, hi_r = _edges(right)

            def _tail_limit(victim_power: float) -> float:
                return max(victim_power - tail_margin, scn.noise_floor_dbm)

            # 左载波尾部进入右载波频段入口处的电平
            lvl_lr = left.power_dbm - float(
                att_funcs[left.name](lo_r - left.fc))
            lim_lr = _tail_limit(right.power_dbm)
            if lvl_lr > lim_lr:
                conflicts.append(Conflict(
                    code="TAIL_LEAK", severity=severity,
                    message=(f"载波 {left.name} 掩模尾部进入 {right.name} "
                             f"频段入口 ({lo_r:.3f} MHz) 处电平 "
                             f"{lvl_lr:.1f} dBm，高于受害载波保护门限 "
                             f"{lim_lr:.1f} dBm（{right.power_dbm:.0f} dBm"
                             f"-{tail_margin:.0f} dB）共 "
                             f"{lvl_lr - lim_lr:.1f} dB"),
                    carriers=[left.name, right.name],
                    detail={"source": left.name, "victim": right.name,
                            "at_mhz": lo_r, "level_dbm": lvl_lr,
                            "limit_dbm": lim_lr,
                            "pending_isolation": pending},
                ))
            lvl_rl = right.power_dbm - float(
                att_funcs[right.name](right.fc - hi_l))
            lim_rl = _tail_limit(left.power_dbm)
            if lvl_rl > lim_rl:
                conflicts.append(Conflict(
                    code="TAIL_LEAK", severity=severity,
                    message=(f"载波 {right.name} 掩模尾部进入 {left.name} "
                             f"频段入口 ({hi_l:.3f} MHz) 处电平 "
                             f"{lvl_rl:.1f} dBm，高于受害载波保护门限 "
                             f"{lim_rl:.1f} dBm（{left.power_dbm:.0f} dBm"
                             f"-{tail_margin:.0f} dB）共 "
                             f"{lvl_rl - lim_rl:.1f} dB"),
                    carriers=[right.name, left.name],
                    detail={"source": right.name, "victim": left.name,
                            "at_mhz": hi_l, "level_dbm": lvl_rl,
                            "limit_dbm": lim_rl,
                            "pending_isolation": pending},
                ))

    # ---- 绘图曲线：频段两侧各扩一个带宽的边距 -----------------------------
    traces = _build_traces(scn, att_funcs)

    err = sum(1 for c in conflicts if c.severity == "error")
    warn = sum(1 for c in conflicts if c.severity == "warning")
    return AnalysisResult(
        scenario_name=scn.name,
        power_summary=power_summary,
        conflicts=conflicts,
        error_count=err,
        warning_count=warn,
        traces=traces,
    )


def _build_traces(scn: Scenario, att_funcs: dict) -> dict[str, list[dict]]:
    if not scn.carriers:
        return {}
    pad = max(c.bandwidth for c in scn.carriers)
    x0 = scn.band_start - pad
    x1 = scn.band_stop + pad
    n = 700
    xs = np.linspace(x0, x1, n)
    out: dict[str, list[dict]] = {}
    for c in scn.carriers:
        att = att_funcs[c.name](np.abs(xs - c.fc))
        ys = c.power_dbm - att
        # 掩模平台以下截断，避免绘图出现无意义的极深值
        ys = np.where(ys < scn.noise_floor_dbm - 20,
                      scn.noise_floor_dbm - 20, ys)
        out[c.name] = [{"x": float(x), "y": float(y)}
                       for x, y in zip(xs, ys)]
    return out
