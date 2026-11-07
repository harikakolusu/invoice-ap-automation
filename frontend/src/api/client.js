// Thin wrapper over the FastAPI backend (/api is proxied to :8000 in dev, same origin in prod).
async function request(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : `${res.status} ${res.statusText}`)
  }
  return res.json()
}

const qs = (params = {}) => {
  const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== '' && v != null))
  const s = new URLSearchParams(clean).toString()
  return s ? `?${s}` : ''
}

export const api = {
  datasets: () => request('/datasets'),
  summary: (ds) => request(`/datasets/${ds}/summary`),
  validation: (ds) => request(`/datasets/${ds}/validation`),
  invoices: (ds, params) => request(`/datasets/${ds}/invoices${qs(params)}`),
  invoice: (ds, id) => request(`/datasets/${ds}/invoices/${encodeURIComponent(id)}`),
  exceptions: (ds, params) => request(`/datasets/${ds}/exceptions${qs(params)}`),
  extract: (ds, text, useLlm = false) => request(`/datasets/${ds}/intake/extract`, { method: 'POST', body: JSON.stringify({ text, use_llm: useLlm }) }),
  sample: (ds, params) => request(`/datasets/${ds}/intake/sample${qs(params)}`),
  llmStatus: () => request('/llm/status'),
  copilot: (ds, id) => request(`/datasets/${ds}/invoices/${encodeURIComponent(id)}/copilot`, { method: 'POST' }),
  run: (ds) => request(`/datasets/${ds}/run`, { method: 'POST' }),
}
