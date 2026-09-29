"""OR-Tools CP-SAT 频率指派：在允许频段内为载波寻找满足保护间隔的中心频率。

简化离线模型：仅几何约束
* 每载波完整落在 [band_start, band_stop] 内；
* 载波对边缘间隙 >= 保护间隔（频率轴上的 NoOverlap）；
* 异极化且输入规则允许复用时不施加间隔约束；
  隔离度未知时按保守策略施加间隔（不赌未知隔离）。
频率以 kHz 整数建模（MHz * 1000），目标是偏离原中心频率的总位移最小。
"""
from __future__ import annotations

from ortools.sat.python import cp_model

from .models import AssignRequest, AssignSolution, Carrier, CrossPolRule, Scenario

KHZ = 1000  # MHz -> kHz


def _cross_pol(a: Carrier, b: Carrier) -> bool:
    return {a.polarization.value, b.polarization.value} == {"H", "V"}


def assign(req: AssignRequest) -> AssignSolution:
    scn: Scenario = req.scenario  # type: ignore[assignment]
    model = cp_model.CpModel()
    n = len(scn.carriers)

    starts: dict[int, cp_model.LinearExpr] = {}  # 频段左边缘 kHz
    durations: dict[str, int] = {}
    pos_vars: dict[str, cp_model.IntVar] = {}
    fixed_pos: dict[str, int] = {}

    lo_band = round(scn.band_start * KHZ)
    hi_band = round(scn.band_stop * KHZ)

    for idx, c in enumerate(scn.carriers):
        half = round(c.bandwidth * KHZ / 2)
        # 中心频率域：整载波必须落在允许频段内
        dom_lo = lo_band + half
        dom_hi = hi_band - half
        if dom_lo > dom_hi:
            return AssignSolution(
                status="INFEASIBLE",
                message=f"载波 {c.name} 带宽 {c.bandwidth} MHz 超过允许频段宽度",
            )
        if c.name in req.fixed:
            fc_khz = round(req.fixed[c.name] * KHZ)
            if not (dom_lo <= fc_khz <= dom_hi):
                return AssignSolution(
                    status="INFEASIBLE",
                    message=(f"固定载波 {c.name} 的中心 {req.fixed[c.name]} MHz "
                             f"无法完整落在允许频段内"),
                )
            fixed_pos[c.name] = fc_khz
            starts[idx] = fc_khz - half
        else:
            fc_var = model.new_int_var(dom_lo, dom_hi, f"fc_{c.name}")
            pos_vars[c.name] = fc_var
            starts[idx] = fc_var - half
        durations[c.name] = 2 * half

    guard_khz = round(scn.guard_mhz * KHZ)
    intervals: dict[tuple[str, str], tuple] = {}
    names = [c.name for c in scn.carriers]

    for i in range(n):
        for j in range(i + 1, n):
            a, b = scn.carriers[i], scn.carriers[j]
            if (_cross_pol(a, b)
                    and scn.cross_pol_rule == CrossPolRule.ALLOW):
                continue  # 异极化允许复用，不施加间隔约束
            sep = (durations[names[i]] + durations[names[j]]) // 2 + guard_khz
            fci = fixed_pos.get(names[i]) or pos_vars[names[i]]
            fcj = fixed_pos.get(names[j]) or pos_vars[names[j]]
            # |fci - fcj| >= sep  <=>  NoOverlap：i 在 j 左侧或右侧
            bvar = model.new_bool_var(f"order_{names[i]}_{names[j]}")
            model.add(fci + sep <= fcj).only_enforce_if(bvar)
            model.add(fcj + sep <= fci).only_enforce_if(~bvar)

    # 目标：总位移最小（kHz）；固定载波位移为 0
    deltas = []
    for c in scn.carriers:
        if c.name in pos_vars:
            d = model.new_int_var(0, hi_band - lo_band, f"d_{c.name}")
            orig = round(c.fc * KHZ)
            model.add_abs_equality(d, pos_vars[c.name] - orig)
            deltas.append(d)
    model.minimize(sum(deltas))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 42
    status = solver.solve(model)

    status_name = solver.status_name(status)
    positions = {name: fc / KHZ for name, fc in fixed_pos.items()}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for name, var in pos_vars.items():
            positions[name] = solver.value(var) / KHZ
        # 按载波录入顺序返回
        ordered = {c.name: positions[c.name] for c in scn.carriers}
        pending_note = ""
        if scn.cross_pol_rule == CrossPolRule.UNKNOWN:
            pending_note = "（异极化隔离度未知，已按最保守方式要求全部间隔）"
        return AssignSolution(
            status=status_name,
            positions=ordered,
            message=(f"找到{'最优' if status == cp_model.OPTIMAL else '可行'}"
                     f"频率配置，总位移 {solver.objective_value / KHZ:.3f} MHz"
                     + pending_note),
            objective_hz=int(solver.objective_value),
        )
    return AssignSolution(
        status=status_name,
        message=("在给定频段/保护间隔/复用规则下无可行解，"
                 "请放宽保护带、扩大频段或允许异极化复用"),
    )
