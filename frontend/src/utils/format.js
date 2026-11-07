const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

export const money = (v) => (v === '' || v == null ? '—' : usd.format(Number(v)))
export const pct = (v, digits = 1) => (v == null ? '—' : `${(Number(v) * 100).toFixed(digits)}%`)
export const num = (v) => (v == null ? '—' : Number(v).toLocaleString('en-US'))
export const label = (s) => (s
  ? s.replaceAll('_', ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase())
    .replace(/\b(ap|po|edi|non po)\b/gi, (m) => m.toUpperCase().replace(' ', '-'))
  : '—')
export const dt = (s) => (s ? s.replace('T', ' ').slice(0, 16) : '—')
