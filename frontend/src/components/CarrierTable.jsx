export default function CarrierTable({
  carriers,
  masks,
  onChange,
  onRemove,
  highlightName,
  onPick,
}) {
  const update = (i, field, value) => onChange(
    carriers.map((c, j) => (j === i ? { ...c, [field]: value } : c)),
  )

  return (
    <div className="table-wrap">
      <table className="carrier-table">
        <thead>
          <tr>
            <th>名称</th>
            <th>中心频率 (MHz)</th>
            <th>带宽 (MHz)</th>
            <th>功率 (dBm)</th>
            <th>极化</th>
            <th>掩模</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {carriers.map((c, i) => (
            <tr
              key={i}
              className={highlightName === c.name ? 'row-hot' : ''}
              onClick={() => onPick?.(c.name)}
            >
              <td>
                <input
                  value={c.name}
                  onChange={(e) => update(i, 'name', e.target.value)}
                />
              </td>
              <td>
                <input
                  type="number"
                  step="0.1"
                  value={c.fc}
                  onChange={(e) => update(i, 'fc', Number(e.target.value))}
                />
              </td>
              <td>
                <input
                  type="number"
                  step="0.5"
                  min="0"
                  value={c.bandwidth}
                  onChange={(e) =>
                    update(i, 'bandwidth', Number(e.target.value))}
                />
              </td>
              <td>
                <input
                  type="number"
                  step="0.5"
                  value={c.power_dbm}
                  onChange={(e) =>
                    update(i, 'power_dbm', Number(e.target.value))}
                />
              </td>
              <td>
                <select
                  value={c.polarization}
                  onChange={(e) => update(i, 'polarization', e.target.value)}
                >
                  <option value="H">H 水平</option>
                  <option value="V">V 垂直</option>
                  <option value="X">X 未指定</option>
                </select>
              </td>
              <td>
                <select
                  value={c.mask_name ?? ''}
                  onChange={(e) =>
                    update(i, 'mask_name', e.target.value || null)}
                >
                  <option value="">（场景默认）</option>
                  {masks.map((m) => (
                    <option key={m.name} value={m.name}>{m.name}</option>
                  ))}
                </select>
              </td>
              <td>
                <button
                  className="btn-mini btn-danger"
                  onClick={() =>
                    onRemove(carriers.filter((_, j) => j !== i))}
                >
                  删除
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
