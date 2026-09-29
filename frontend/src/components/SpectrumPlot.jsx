import { useEffect, useRef } from 'react'
import Plotly from 'plotly.js-dist-min'

// 极化配色
const POL_COLOR = { H: '#2f6fed', V: '#e0702a', X: '#7a5cf0' }

function severityColor(code, severity) {
  if (severity === 'error') return '#d83b3b'
  if (severity === 'warning') return '#d99a1b'
  return '#3a8f5b'
}

// 为每载波构造一条顶部水平“频段条”（y 轴 2），冲突时条变红
function buildBandBars(scenario, result) {
  const badPairs = new Set()
  result?.conflicts
    ?.filter((c) => c.severity === 'error' || c.severity === 'warning')
    .forEach((c) => {
      if (c.carriers.length === 2) {
        badPairs.add(c.carriers.slice().sort().join('|'))
      }
    })
  const badSingle = new Set(
    result?.conflicts
      ?.filter((c) => c.carriers.length === 1)
      .map((c) => c.carriers[0]),
  )

  return scenario.carriers.map((c) => {
    const lo = c.fc - c.bandwidth / 2
    const hi = c.fc + c.bandwidth / 2
    const hasPairIssue = scenario.carriers.some(
      (o) =>
        o.name !== c.name &&
        badPairs.has([c.name, o.name].sort().join('|')),
    )
    const color =
      badSingle.has(c.name) || hasPairIssue
        ? '#d83b3b'
        : POL_COLOR[c.polarization] || POL_COLOR.X
    return {
      x: [lo, hi, hi, lo, lo],
      y: [0, 0, 1, 1, 0],
      mode: 'lines',
      line: { color, width: 2 },
      fill: 'toself',
      fillcolor: color + '22',
      name: c.name,
      hovertext: `${c.name}  fc=${c.fc} MHz  bw=${c.bandwidth} MHz  ` +
        `${c.power_dbm} dBm  极化${c.polarization}`,
      hoverinfo: 'text',
      xaxis: 'x',
      yaxis: 'y2',
      showlegend: true,
      meta: { carrier: c.name },
    }
  })
}

function buildMaskTraces(scenario, traces) {
  return scenario.carriers.map((c) => {
    const t = traces[c.name] || []
    return {
      x: t.map((p) => p.x),
      y: t.map((p) => p.y),
      mode: 'lines',
      type: 'scatter',
      name: `${c.name} 掩模尾部`,
      line: {
        color: POL_COLOR[c.polarization] || POL_COLOR.X,
        width: 1.5,
        dash: 'dot',
      },
      opacity: 0.85,
      hovertemplate: `${c.name}  %{x:.2f} MHz  %{y:.1f} dBm<extra></extra>`,
      meta: { carrier: c.name },
    }
  })
}

export default function SpectrumPlot({ scenario, result, highlight }) {
  const hostRef = useRef(null)
  const highlightRef = useRef(highlight)
  highlightRef.current = highlight

  useEffect(() => {
    const el = hostRef.current
    if (!el) return

    const bandShapes = [
      // 允许频段
      {
        type: 'rect',
        x0: scenario.band_start,
        x1: scenario.band_stop,
        y0: 0,
        y1: 1,
        yref: 'y2',
        line: { color: '#3a8f5b', width: 2, dash: 'dash' },
        fillcolor: '#3a8f5b08',
        layer: 'below',
      },
    ]

    const traces = [
      ...buildBandBars(scenario, result),
      ...buildMaskTraces(scenario, result?.traces),
    ]

    // 冲突定位标注：保护带不足在间隙中点画标记，尾部越界在入口处画竖线
    const annotations = []
    result?.conflicts?.forEach((cf) => {
      const color = severityColor(cf.code, cf.severity)
      if (cf.code === 'TAIL_LEAK' && cf.detail?.at_mhz != null) {
        bandShapes.push({
          type: 'line',
          x0: cf.detail.at_mhz,
          x1: cf.detail.at_mhz,
          y0: 0,
          y1: 1,
          yref: 'y2',
          line: { color, width: 2 },
        })
      }
      if ((cf.code === 'OVERLAP' || cf.code === 'GUARD_SHORTAGE') &&
          cf.carriers?.length === 2) {
        const cs = scenario.carriers.filter((c) => cf.carriers.includes(c.name))
        if (cs.length === 2) {
          const mids = cs.map((c) => c.fc)
          annotations.push({
            x: (mids[0] + mids[1]) / 2,
            y: 1.15,
            yref: 'y2',
            text: cf.code === 'OVERLAP' ? '重叠' : '保护带不足',
            showarrow: true,
            arrowhead: 2,
            arrowcolor: color,
            font: { color, size: 11 },
            bgcolor: '#fff8e8',
          })
        }
      }
    })

    const ymin = Math.min(
      scenario.noise_floor_dbm - 20,
      ...scenario.carriers.map((c) => c.power_dbm - 60),
    )

    const layout = {
      height: 460,
      margin: { l: 60, r: 20, t: 30, b: 50 },
      hovermode: 'closest',
      shapes: bandShapes,
      annotations,
      xaxis: {
        title: '频率 (MHz)',
        range: [
          scenario.band_start -
            Math.max(10, ...scenario.carriers.map((c) => c.bandwidth)),
          scenario.band_stop +
            Math.max(10, ...scenario.carriers.map((c) => c.bandwidth)),
        ],
      },
      yaxis: { title: '功率谱密度 (dBm/MHz)', range: [ymin, null] },
      yaxis2: {
        title: '频段',
        overlaying: 'y',
        range: [-0.4, 1.6],
        showticklabels: false,
        zeroline: false,
      },
      legend: { orientation: 'h', y: -0.22, font: { size: 10 } },
    }

    const config = {
      responsive: true,
      displaylogo: false,
      modeBarButtonsToRemove: ['lasso2d', 'select2d'],
    }

    Plotly.react(el, traces, layout, config)

    // 点击曲线/频段条 -> 高亮对应载波
    const onClick = (ev) => {
      const idx = ev.points?.[0]?.curveNumber
      if (idx == null) return
      const carrier = el.data[idx]?.meta?.carrier
      if (carrier) highlightRef.current?.(carrier)
    }
    el.on('plotly_click', onClick)
    return () => el.removeAllListeners('plotly_click')
  }, [scenario, result])

  return <div ref={hostRef} className="plot-host" />
}
