// Small presentational building blocks shared by the pages.
import { label } from '../utils/format.js'

const TONE = {
  PAYMENT_READY: 'ok', PASS: 'ok', MATCHED: 'ok', APPROVED: 'ok', SCHEDULED: 'ok',
  MATCHED_WITHIN_TOLERANCE: 'info', NON_PO: 'info', AUTO: 'info', L1: 'info', 'L1>L2': 'info',
  ON_HOLD: 'warn', OPEN: 'warn', FAIL: 'bad',
}

export function Badge({ value, tone }) {
  if (!value) return <span className="muted">—</span>
  const t = tone ?? TONE[value] ?? 'bad'
  return <span className={`badge ${t}`}>{label(value)}</span>
}

export function Card({ title, children, actions }) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-head">
          <h3>{title}</h3>
          {actions}
        </header>
      )}
      {children}
    </section>
  )
}

export function Kpi({ label: k, value, hint }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{k}</div>
      <div className="kpi-value">{value}</div>
      {hint && <div className="kpi-hint">{hint}</div>}
    </div>
  )
}

export function Bar({ value, max }) {
  const w = max ? Math.min(100, (value / max) * 100) : 0
  return <div className="bar"><span style={{ width: `${w}%` }} /></div>
}

export function Loading({ state, children }) {
  if (state.error) return <div className="alert">Could not load data: {state.error.message}</div>
  if (state.loading && !state.data) return <div className="muted pad">Loading…</div>
  return children(state.data)
}

export function Field({ k, v }) {
  return (
    <div className="field">
      <div className="field-k">{k}</div>
      <div className="field-v">{v ?? '—'}</div>
    </div>
  )
}
