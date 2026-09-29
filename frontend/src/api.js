// 后端 REST 封装。开发环境经 Vite 代理到 uvicorn:8000，
// 生产构建由 FastAPI 静态托管（同源）。

async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail || detail
    } catch {
      /* 忽略非 JSON 错误体 */
    }
    throw new Error(`${res.status} ${detail}`)
  }
  return res.json()
}

export const api = {
  health: () => request('/api/health'),
  listScenarios: () => request('/api/scenarios'),
  getScenario: (id) => request(`/api/scenarios/${id}`),
  createScenario: (s) =>
    request('/api/scenarios', { method: 'POST', body: JSON.stringify(s) }),
  deleteScenario: (id) =>
    request(`/api/scenarios/${id}`, { method: 'DELETE' }),
  analyze: (s) =>
    request('/api/analyze', { method: 'POST', body: JSON.stringify(s) }),
  analyzeSaved: (id) =>
    request(`/api/scenarios/${id}/analyze`, { method: 'POST' }),
  assign: (scenario, fixed = {}) =>
    request('/api/assign', {
      method: 'POST',
      body: JSON.stringify({ scenario, fixed }),
    }),
  listMasks: () => request('/api/masks'),
  resetPresets: () => request('/api/reset_presets', { method: 'POST' }),
}
