"""离线自检：核对冲突定位、线性域功率汇总、OR-Tools 求解。

运行：python scripts/selfcheck.py
不启动网络服务、不连数据库（使用内存存储 + 演示种子）。
"""
from __future__ import annotations

import sys

from app.models import (
    CrossPolRule,
    ScenarioIn,
    AssignRequest,
)
from app.optimizer import assign
from app.presets import demo_scenarios
from app.spectrum import analyze, dbm_to_mw, mw_to_dbm
from app.storage import MemoryStore

PASS, FAIL = "✅", "❌"
fails = 0


def check(label: str, cond: bool, extra: str = "") -> None:
    global fails
    print(f"  {PASS if cond else FAIL} {label} {extra}")
    if not cond:
        fails += 1


def codes_for(result, pair: tuple[str, str]) -> list[tuple[str, str]]:
    a, b = pair
    out = []
    for c in result.conflicts:
        if set(c.carriers) == {a, b}:
            out.append((c.code, c.severity))
    return out


def main() -> int:
    store = MemoryStore()
    masks = {m.name: m for m in store.list_masks()}
    seed = {s["name"]: s for s in demo_scenarios()}

    # ------------------------------------------------------------------ #
    print("1) 功率汇总：线性域求和")
    import math
    # 43 + 46 + 40 + 36 dBm
    vals = [43, 46, 40, 36]
    expect_mw = sum(dbm_to_mw(v) for v in vals)
    expect_dbm = mw_to_dbm(expect_mw)
    scn = ScenarioIn(**seed["核对用例：同带宽不同功率"])
    r = analyze(scn, masks)
    check("各载波 mW 换算正确",
          math.isclose(r.power_summary.per_carrier_mw["载波A"],
                       dbm_to_mw(43), rel_tol=1e-9))
    check(f"总功率在线性域求和 = {expect_mw:.2f} mW / {expect_dbm:.2f} dBm",
          math.isclose(r.power_summary.total_mw, expect_mw, rel_tol=1e-9)
          and math.isclose(r.power_summary.total_dbm, expect_dbm, abs_tol=1e-6),
          f"(得到 {r.power_summary.total_dbm:.2f} dBm)")
    check("总功率大于最大功率 46 dBm（不能直接平均/相加 dB）",
          r.power_summary.total_dbm > 46)

    # ------------------------------------------------------------------ #
    print("2) 核对用例：同带宽不同功率（mask_slow, guard=2 MHz）")
    print("   全部冲突明细：")
    for c in r.conflicts:
        print(f"    [{c.severity:7s}] {c.code:15s} {c.carriers} {c.message}")

    ab = codes_for(r, ("载波A", "载波B"))
    check("A-B 定位到保护带不足 GUARD_SHORTAGE",
          ("GUARD_SHORTAGE", "error") in ab, str(ab))
    tail_ab = [x for x in ab if x[0] == "TAIL_LEAK"]
    check("A-B 双向掩模尾部越界 TAIL_LEAK x2（43 vs 46 dBm 不同功率）",
          len(tail_ab) == 2, str(tail_ab))

    cd = codes_for(r, ("载波C", "载波D"))
    check("C-D 定位到频段重叠 OVERLAP",
          ("OVERLAP", "error") in cd, str(cd))
    check("重叠载波不再报保护带/尾部",
          all(code not in ("GUARD_SHORTAGE", "TAIL_LEAK")
              for code, _ in cd))

    # 其他载波对不应误报
    for pair in [(0, 2), (0, 3), (1, 2), (1, 3)]:
        p = (scn.carriers[pair[0]].name, scn.carriers[pair[1]].name)
        check(f"{p[0]}-{p[1]} 无冲突（避免误报）", codes_for(r, p) == [])

    check("该用例 error 数 = 4（1 保护带 + 2 尾部 + 1 重叠）",
          r.error_count == 4, f"(实际 {r.error_count})")

    # 尾部必须体现“功率不同”：B(46)->A 比 A(43)->B 越限更多
    leaks = [c for c in r.conflicts if c.code == "TAIL_LEAK"]
    b_to_a = next(c for c in leaks if c.detail["source"] == "载波B")
    a_to_b = next(c for c in leaks if c.detail["source"] == "载波A")
    check("高功率载波 B->A 尾部电平高于 A->B（功率不同可定位泄漏源）",
          b_to_a.detail["level_dbm"] > a_to_b.detail["level_dbm"],
          f"({b_to_a.detail['level_dbm']:.1f} vs "
          f"{a_to_b.detail['level_dbm']:.1f} dBm)")

    # 绘图曲线
    check("返回每载波频谱曲线（700 点）",
          all(len(v) == 700 for v in r.traces.values())
          and len(r.traces) == 4)

    # ------------------------------------------------------------------ #
    print("3) 异极化复用规则 unknown：待评估告警，可定位载波对")
    scn2 = ScenarioIn(**seed["核对用例：异极化复用待评估"])
    r2 = analyze(scn2, masks)
    for c in r2.conflicts:
        print(f"    [{c.severity:7s}] {c.code:17s} {c.carriers} {c.message}")
    h1v1 = codes_for(r2, ("H-1", "V-1"))
    check("H-1/V-1 PENDING_ISOLATION 待评估",
          ("PENDING_ISOLATION", "warning") in h1v1)
    check("H-1/V-1 重叠降级为 warning（不直接判死）",
          ("OVERLAP", "warning") in h1v1)
    h2v2 = codes_for(r2, ("H-2", "V-2"))
    check("H-2/V-2 PENDING_ISOLATION 待评估",
          ("PENDING_ISOLATION", "warning") in h2v2)
    check("H-2/V-2 保护带不足为 warning",
          ("GUARD_SHORTAGE", "warning") in h2v2)
    check("unknown 用例无 error（全部待评估）", r2.error_count == 0)
    check("unknown 用例有 warning", r2.warning_count > 0)

    # 规则 allow：同频段复用直接放行
    d2 = scn2.model_dump()
    d2["cross_pol_rule"] = CrossPolRule.ALLOW
    r2b = analyze(ScenarioIn(**d2), masks)
    for pair in (("H-1", "V-1"), ("H-2", "V-2")):
        got = codes_for(r2b, pair)
        check(f"allow 规则下 {pair} 仅记 CROSSPOL_REUSE 放行",
              got == [("CROSSPOL_REUSE", "info")], str(got))

    # 规则 deny：异极化也必须满足间隔
    d2["cross_pol_rule"] = CrossPolRule.DENY
    r2c = analyze(ScenarioIn(**d2), masks)
    check("deny 规则下 H-1/V-1 重叠为 error",
          ("OVERLAP", "error") in codes_for(r2c, ("H-1", "V-1")))

    # ------------------------------------------------------------------ #
    print("4) OR-Tools：拥挤频段重排")
    scn3 = ScenarioIn(**seed["OR-Tools：拥挤频段重排"])
    r3_before = analyze(scn3, masks)
    check("重排前存在重叠冲突", r3_before.error_count > 0)
    sol = assign(AssignRequest(scenario=scn3))
    print(f"    求解状态：{sol.status}；{sol.message}")
    check("求解状态 OPTIMAL/FEASIBLE", sol.status in ("OPTIMAL", "FEASIBLE"),
          sol.status)
    d3 = scn3.model_dump()
    for c in d3["carriers"]:
        c["fc"] = sol.positions[c["name"]]
    r3_after = analyze(ScenarioIn(**d3), masks)
    hard = [c for c in r3_after.conflicts if c.severity == "error"
            and c.code in ("OVERLAP", "GUARD_SHORTAGE")]
    check("重排后无重叠/保护带不足 error", not hard,
          "; ".join(f"{c.code}{c.carriers}" for c in hard))
    print("    指派结果：")
    for name, fc in sol.positions.items():
        print(f"      {name}: {fc:.3f} MHz")

    # 固定载波测试
    sol_fix = assign(AssignRequest(
        scenario=scn3, fixed={"C1": 3605.0}))
    check("固定 C1 后仍可行且 C1 位置保持",
          sol_fix.status in ("OPTIMAL", "FEASIBLE")
          and abs(sol_fix.positions["C1"] - 3605.0) < 1e-9,
          f"{sol_fix.status} {sol_fix.positions.get('C1')}")

    # 不可行测试：带宽 600 MHz 载波塞进 60 MHz
    d_bad = scn3.model_dump()
    d_bad["carriers"] = [d_bad["carriers"][0]]
    d_bad["carriers"][0]["bandwidth"] = 600.0
    sol_bad = assign(AssignRequest(scenario=ScenarioIn(**d_bad)))
    check("明显不可行时返回 INFEASIBLE",
          sol_bad.status == "INFEASIBLE", sol_bad.status)

    # allow 规则下异极化可省空间（同一点可放两个异极化载波）
    d_allow = scn3.model_dump()
    d_allow["cross_pol_rule"] = CrossPolRule.ALLOW
    sol_allow = assign(AssignRequest(scenario=ScenarioIn(**d_allow)))
    check("allow 规则仍可求解",
          sol_allow.status in ("OPTIMAL", "FEASIBLE"), sol_allow.status)

    # ------------------------------------------------------------------ #
    print("5) 单载波：频段越界与频段边缘掩模杂散")
    from app.models import ScenarioIn as SI

    # 贴齐频段边缘的载波：不应误报杂散（平台自然过渡到带外）
    flush = SI(name="flush", band_start=1000, band_stop=1010, guard_mhz=0,
               spurious_limit_dbm=-13, tail_threshold_db=10,
               noise_floor_dbm=-110, default_mask_name="mask_slow",
               carriers=[{"name": "F", "fc": 1005.0, "bandwidth": 10.0,
                          "power_dbm": 46.0, "polarization": "H"}])
    rf = analyze(flush, masks)
    check("贴齐低频段边缘不报 SPURIOUS_EDGE / BAND_OUTSIDE",
          all(c.code not in ("SPURIOUS_EDGE", "BAND_OUTSIDE")
              for c in rf.conflicts),
          str([(c.code, c.message) for c in rf.conflicts]))

    # 强功率载波深入频段内部：带外掩模电平仍超过 -13 dBm 杂散限值
    inside = SI(name="inside", band_start=1002, band_stop=1018, guard_mhz=0,
                spurious_limit_dbm=-13, tail_threshold_db=10,
                noise_floor_dbm=-110, default_mask_name="mask_slow",
                carriers=[{"name": "P", "fc": 1010.0, "bandwidth": 10.0,
                           "power_dbm": 46.0, "polarization": "H"}])
    ri = analyze(inside, masks)
    sp = [c for c in ri.conflicts if c.code == "SPURIOUS_EDGE"]
    check("内部强功率载波在两侧频段边缘报 SPURIOUS_EDGE x2",
          len(sp) == 2, f"(实际 {len(sp)})")

    # 完全越出频段
    out = SI(name="out", band_start=1000, band_stop=1020, guard_mhz=0,
             spurious_limit_dbm=-13, tail_threshold_db=10,
             noise_floor_dbm=-110, default_mask_name="mask_rect",
             carriers=[{"name": "O", "fc": 1030.0, "bandwidth": 10.0,
                        "power_dbm": 30.0, "polarization": "H"}])
    ro = analyze(out, masks)
    check("频段越出报 BAND_OUTSIDE 且定位载波",
          any(c.code == "BAND_OUTSIDE" and c.carriers == ["O"]
              for c in ro.conflicts))

    # 配置错误：倒序频段 / 重名
    bad = SI(name="bad", band_start=1020, band_stop=1000, guard_mhz=0,
             carriers=[{"name": "O", "fc": 1010, "bandwidth": 10.0,
                        "power_dbm": 30.0, "polarization": "H"},
                       {"name": "O", "fc": 1015, "bandwidth": 10.0,
                        "power_dbm": 30.0, "polarization": "H"}])
    rb = analyze(bad, masks)
    check("倒序频段与重名报 CONFIG_ERROR",
          sum(1 for c in rb.conflicts if c.code == "CONFIG_ERROR") == 2)

    print()
    if fails:
        print(f"{FAIL} {fails} 项检查未通过")
        return 1
    print(f"{PASS} 全部检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
