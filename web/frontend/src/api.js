// REST 封装。统一 /api 前缀、统一错误处理。
// 交互层：只负责跟后端说话，不含任何业务判断（判断在 Python 核心层）。

async function request(method, path, body) {
  const opts = { method, headers: {} }
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const resp = await fetch('/api' + path, opts)
  const text = await resp.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!resp.ok) {
    const detail = (data && data.detail) || resp.statusText || '请求失败'
    throw new Error(detail)
  }
  return data
}

export const api = {
  overview: () => request('GET', '/overview'),
  createGoal: (title, cadence) => request('POST', '/goals', { title, cadence }),
  patchGoal: (id, patch) => request('PATCH', `/goals/${id}`, patch),
  setPrimary: (id) => request('POST', `/goals/${id}/primary`),
  markDone: (id) => request('POST', `/goals/${id}/done`),
  archive: (id) => request('POST', `/goals/${id}/archive`),
}

// ISO → 本地 "MM-DD HH:mm"
export function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d)) return iso
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
