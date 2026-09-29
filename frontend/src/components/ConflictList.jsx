const CODE_LABEL = {
  OVERLAP: '频段重叠',
  GUARD_SHORTAGE: '保护带不足',
  TAIL_LEAK: '掩模尾部越界',
  SPURIOUS_EDGE: '频段边缘杂散越限',
  BAND_OUTSIDE: '载波越出频段',
  PENDING_ISOLATION: '隔离度待评估',
  CROSSPOL_REUSE: '异极化复用放行',
  CONFIG_ERROR: '配置错误',
}

const SEV_STYLE = {
  error: 'sev-error',
  warning: 'sev-warning',
  info: 'sev-info',
}

export default function ConflictList({ conflicts, onLocate }) {
  if (!conflicts?.length) {
    return (
      <div className="all-clear">
        ✅ 未发现频带重叠、保护带不足或掩模尾部越界
      </div>
    )
  }
  const groups = { error: [], warning: [], info: [] }
  conflicts.forEach((c) => groups[c.severity]?.push(c))

  return (
    <div className="conflict-list">
      {Object.entries(groups).map(([sev, items]) =>
        items.map((c, i) => (
          <div
            key={`${sev}-${i}`}
            className={`conflict-card ${SEV_STYLE[sev]}`}
            onClick={() => c.carriers?.[0] && onLocate?.(c.carriers[0])}
          >
            <div className="conflict-head">
              <span className={`badge ${SEV_STYLE[sev]}`}>
                {sev === 'error' ? '错误' : sev === 'warning' ? '待评估' : '信息'}
              </span>
              <span className="conflict-code">
                {CODE_LABEL[c.code] || c.code}
              </span>
              {c.carriers?.length > 0 && (
                <span className="conflict-carriers">
                  {c.carriers.join(' ↔ ')}
                </span>
              )}
            </div>
            <div className="conflict-msg">{c.message}</div>
          </div>
        )),
      )}
    </div>
  )
}
