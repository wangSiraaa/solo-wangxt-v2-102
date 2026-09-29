import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import CarrierTable from './components/CarrierTable.jsx'
import ConflictList from './components/ConflictList.jsx'
import SpectrumPlot from './components/SpectrumPlot.jsx'

const blankScenario = () => ({
  name: '新场景',
  band_start: 1430,
  band_stop: 1530,
  guard_mhz: 2,
  cross_pol_rule: 'deny',
  spurious_limit_dbm: -13,
  tail_threshold_db: 10,
  noise_floor_dbm: -110,
  default_mask_name: 'mask_slow',
  carriers: [],
})

const newCarrier = (i) => ({
  name: `载波${String.fromCharCode(65 + (i % 26))}`,
  fc: 1440 + i * 12,
  bandwidth: 10,
  power_dbm: 40,
  polarization: 'H',
  mask_name: null,
})

export default function App() {
  const [health, setHealth] = useState(null)
  const [masks, setMasks] = useState([])
  const [scenarios, setScenarios] = useState([])
  const [scenario, setScenario] = useState(blankScenario())
  const [result, setResult] = useState(null)
  const [highlight, setHighlight] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [solution, setSolution] = useState(null)
  const [savedId, setSavedId] = useState(null)
  const timer = useRef(null)

  const refreshScenarios = useCallback(async () => {
    setScenarios(await api.listScenarios())
  }, [])

  useEffect(() => {
    ;(async () => {
      setHealth(await api.health())
      setMasks(await api.listMasks())
      const list = await api.listScenarios()
      setScenarios(list)
      if (list[0]) loadScenario(list[0])
    })().catch((e) => setError(String(e)))
  }, [])

  const loadScenario = (s) => {
    setSavedId(s.id)
    setSolution(null)
    setResult(null)
    const { id, ...rest } = s
    setScenario(rest)
  }

  // 录入后自动重新分析（防抖）
  const analyze = useCallback(async (s) => {
    setLoading(true)
    setError('')
    try {
      const r = await api.analyze(s)
      setResult(r)
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => analyze(scenario), 250)
    return () => clearTimeout(timer.current)
  }, [scenario, analyze])

  const setField = (field, value) =>
    setScenario((s) => ({ ...s, [field]: value }))

  const totalMw = result?.power_summary?.total_mw
  const totalDbm = result?.power_summary?.total_dbm

  const applySolution = () => {
    if (!solution) return
    setScenario((s) => ({
      ...s,
      carriers: s.carriers.map((c) =>
        solution.positions[c.name] != null
          ? { ...c, fc: solution.positions[c.name] }
          : c,
      ),
    }))
    setSolution(null)
  }

  const runAssign = async () => {
    setError('')
    try {
      setSolution(await api.assign(scenario))
    } catch (e) {
      setError(String(e.message || e))
    }
  }

  const save = async () => {
    try {
      const saved = await api.createScenario(scenario)
      setSavedId(saved.id)
      await refreshScenarios()
    } catch (e) {
      setError(String(e.message || e))
    }
  }

  const removeSaved = async (id) => {
    if (id === savedId) {
      setSavedId(null)
    }
    await api.deleteScenario(id)
    await refreshScenarios()
  }

  const resetPresets = async () => {
    await api.resetPresets()
    const list = await api.listScenarios()
    setMasks(await api.listMasks())
    setScenarios(list)
    if (list[0]) loadScenario(list[0])
  }

  return (
    <div className="app">
      <header className="topbar">
        <h1>📡 频谱工作台</h1>
        <div className="sub">
          载波频率配置核对 · 频带重叠 / 保护带 / 掩模尾部 · 离线简化模型，
          不连接无线电设备、不产生发射指令
        </div>
        <div className="health">
          存储：{health?.storage === 'postgres'
            ? 'PostgreSQL 🐘'
            : '内存（未连 PostgreSQL）'}
        </div>
      </header>

      <div className="layout">
        {/* 左栏：场景与载波录入 */}
        <section className="panel left">
          <div className="saved-row">
            <label>已存场景：</label>
            <select
              value={savedId ?? ''}
              onChange={(e) => {
                const s = scenarios.find(
                  (x) => x.id === Number(e.target.value),
                )
                if (s) loadScenario(s)
              }}
            >
              <option value="" disabled>选择…</option>
              {scenarios.map((s) => (
                <option key={s.id} value={s.id}>{s.name} (#{s.id})</option>
              ))}
            </select>
            {savedId && (
              <button
                className="btn-mini btn-danger"
                onClick={() => removeSaved(savedId)}
              >
                删除
              </button>
            )}
            <button className="btn-mini" onClick={resetPresets}>
              恢复示例
            </button>
          </div>

          <div className="form-grid">
            <label>场景名称
              <input
                value={scenario.name}
                onChange={(e) => setField('name', e.target.value)}
              />
            </label>
            <label>频段起点 MHz
              <input
                type="number"
                value={scenario.band_start}
                onChange={(e) => setField('band_start', Number(e.target.value))}
              />
            </label>
            <label>频段终点 MHz
              <input
                type="number"
                value={scenario.band_stop}
                onChange={(e) => setField('band_stop', Number(e.target.value))}
              />
            </label>
            <label>保护间隔 MHz
              <input
                type="number"
                min="0"
                step="0.5"
                value={scenario.guard_mhz}
                onChange={(e) => setField('guard_mhz', Number(e.target.value))}
              />
            </label>
            <label>异极化复用规则
              <select
                value={scenario.cross_pol_rule}
                onChange={(e) => setField('cross_pol_rule', e.target.value)}
              >
                <option value="deny">不允许复用（一律要间隔）</option>
                <option value="allow">允许复用（已知隔离足够）</option>
                <option value="unknown">隔离度未知（待评估）</option>
              </select>
            </label>
            <label>默认掩模
              <select
                value={scenario.default_mask_name ?? ''}
                onChange={(e) =>
                  setField('default_mask_name', e.target.value || null)}
              >
                <option value="">无（理想矩形）</option>
                {masks.map((m) => (
                  <option key={m.name} value={m.name}>{m.name}</option>
                ))}
              </select>
            </label>
            <label>杂散限值 dBm
              <input
                type="number"
                value={scenario.spurious_limit_dbm}
                onChange={(e) =>
                  setField('spurious_limit_dbm', Number(e.target.value))}
              />
            </label>
            <label>尾部保护裕度 dB
              <input
                type="number"
                min="0"
                value={scenario.tail_threshold_db}
                onChange={(e) =>
                  setField('tail_threshold_db', Number(e.target.value))}
              />
            </label>
            <label>底噪 dBm/MHz
              <input
                type="number"
                value={scenario.noise_floor_dbm}
                onChange={(e) =>
                  setField('noise_floor_dbm', Number(e.target.value))}
              />
            </label>
          </div>

          <div className="carrier-head">
            <h3>载波（{scenario.carriers.length}）</h3>
            <button
              className="btn"
              onClick={() =>
                setField('carriers', [
                  ...scenario.carriers,
                  newCarrier(scenario.carriers.length),
                ])}
            >
              ＋ 添加载波
            </button>
          </div>

          <CarrierTable
            carriers={scenario.carriers}
            masks={masks}
            highlightName={highlight}
            onPick={setHighlight}
            onChange={(cs) => setField('carriers', cs)}
            onRemove={(cs) => setField('carriers', cs)}
          />

          <div className="actions">
            <button className="btn btn-primary" onClick={save}>
              保存场景到{health?.storage === 'postgres' ? 'PostgreSQL' : '存储'}
            </button>
            <button className="btn" onClick={() => {
              setScenario(blankScenario())
              setSavedId(null)
            }}>
              清空新建
            </button>
          </div>
        </section>

        {/* 右栏：频谱图、功率、冲突、求解 */}
        <section className="panel right">
          <SpectrumPlot
            scenario={scenario}
            result={result}
            highlight={setHighlight}
          />

          <div className="summary-row">
            <div className="summary-card">
              <div className="summary-label">总功率（线性域 mW 求和后转 dB）</div>
              <div className="summary-value">
                {totalDbm != null ? totalDbm.toFixed(2) : '—'}
                <span className="unit"> dBm</span>
              </div>
              <div className="summary-sub">
                {totalMw != null ? totalMw.toFixed(1) : '—'} mW
              </div>
            </div>
            <div
              className={`summary-card ${
                result?.error_count ? 'card-error'
                  : result?.warning_count ? 'card-warn' : 'card-ok'}`}
            >
              <div className="summary-label">检查结果</div>
              <div className="summary-value">
                {result?.error_count ?? 0}
                <span className="unit"> 错误</span>
                {' / '}
                {result?.warning_count ?? 0}
                <span className="unit"> 待评估</span>
              </div>
              <div className="summary-sub">
                {loading ? '重新计算中…'
                  : result?.error_count
                    ? '存在必须处理的冲突'
                    : result?.warning_count
                      ? '异极化隔离度待人工评估'
                      : '全部通过'}
              </div>
            </div>
            <div className="summary-card assign-card">
              <div className="summary-label">OR-Tools 频率指派（CP-SAT）</div>
              <button
                className="btn btn-primary"
                onClick={runAssign}
                disabled={!scenario.carriers.length}
              >
                寻找满足间隔的频率位置
              </button>
              {solution && (
                <div className={`solution status-${solution.status}`}>
                  <strong>{solution.status}</strong>
                  <span>{solution.message}</span>
                  {(solution.status === 'OPTIMAL' ||
                    solution.status === 'FEASIBLE') && (
                    <button className="btn-mini btn-primary"
                      onClick={applySolution}>
                      应用到载波表
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>

          {error && <div className="error-banner">{error}</div>}

          <ConflictList conflicts={result?.conflicts} onLocate={setHighlight} />
        </section>
      </div>

      <footer className="foot">
        SciPy 掩模插值 · 功率 P=Σ10^(dBm/10) mW 再 10·log10 转 dB ·
        OR-Tools CP-SAT（kHz 整数模型，NoOverlap 间隔约束）
      </footer>
    </div>
  )
}
