import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { Badge, Bar, Card, Kpi, Loading } from '../components/ui.jsx'
import { useDataset } from '../context/DatasetContext.jsx'
import { useApi } from '../hooks/useApi.js'
import { label, money, num, pct } from '../utils/format.js'

export default function DashboardPage() {
  const { dataset, version } = useDataset()
  const state = useApi(() => api.summary(dataset), [dataset, version])

  return (
    <Loading state={state}>
      {(s) => {
        const k = s.kpis
        const queueMax = Math.max(...Object.values(k.queue_workload).map((q) => q.invoices), 1)
        return (
          <>
            <div className="page-head">
              <h1>Dashboard</h1>
              <span className="muted">seed {s.plan.seed} · scale {s.plan.scale} · validation <Badge value={s.validation.status} /> ({s.validation.checks_run} checks)</span>
            </div>

            <div className="kpis">
              <Kpi label="Invoices processed" value={num(k.invoices_processed)} />
              <Kpi label="Payment-ready" value={num(k.payment_ready)} hint={`${pct(k.payment_ready_rate)} · ${money(k.value_payment_ready_usd)}`} />
              <Kpi label="On hold" value={num(k.on_hold)} hint={money(k.value_on_hold_usd)} />
              <Kpi label="Touchless (auto-approved)" value={pct(k.touchless_rate_auto_approved)} />
              <Kpi label="Unsafe releases" value={s.payment_safety.unsafe_releases_blocked_but_payment_ready} hint="blocked but payment-ready" />
              <Kpi label="Median hours to pay-ready" value={k.cycle_time_hours_to_payment_ready.median} hint={`p95 ${k.cycle_time_hours_to_payment_ready.p95} h`} />
            </div>

            <Card title="Acceptance criteria">
              <table>
                <thead><tr><th>Criterion</th><th>Status</th><th>Evidence</th></tr></thead>
                <tbody>
                  {s.acceptance.map((a) => (
                    <tr key={a.criterion}><td>{a.criterion}</td><td><Badge value={a.status} /></td><td className="muted">{a.evidence}</td></tr>
                  ))}
                </tbody>
              </table>
            </Card>

            <div className="grid2">
              <Card title="Open exceptions by queue">
                <table>
                  <thead><tr><th>Queue</th><th className="n">Invoices</th><th className="n">Value</th><th /></tr></thead>
                  <tbody>
                    {Object.entries(k.queue_workload).map(([q, v]) => (
                      <tr key={q}>
                        <td><Link to={`/exceptions?queue=${q}`}>{label(q)}</Link></td>
                        <td className="n">{v.invoices}</td><td className="n">{money(v.value_usd)}</td>
                        <td><Bar value={v.invoices} max={queueMax} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
              <Card title="Issue mix: target vs generated">
                <table>
                  <thead><tr><th>Issue type</th><th className="n">Target</th><th className="n">Actual</th><th /></tr></thead>
                  <tbody>
                    {Object.entries(k.issue_mix_target).map(([t, v]) => (
                      <tr key={t}>
                        <td>{label(t)}</td><td className="n">{pct(v, 0)}</td><td className="n">{pct(k.issue_mix_actual[t])}</td>
                        <td><Bar value={k.issue_mix_actual[t]} max={0.7} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            </div>

            <div className="grid2">
              <Card title="Exception detection vs ground truth">
                <table>
                  <thead><tr><th>Primary exception</th><th className="n">Precision</th><th className="n">Recall</th><th className="n">F1</th><th className="n">Support</th></tr></thead>
                  <tbody>
                    {Object.entries(s.decisions.per_exception).map(([c, m]) => (
                      <tr key={c}>
                        <td>{c === 'NONE' ? 'None (clean)' : <Link to={`/invoices?exception=${c}`}>{label(c)}</Link>}</td>
                        <td className="n">{m.precision.toFixed(3)}</td><td className="n">{m.recall.toFixed(3)}</td>
                        <td className="n">{m.f1.toFixed(3)}</td><td className="n">{m.support}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
              <Card title="Decision quality">
                <table>
                  <tbody>
                    <tr><td>Match status accuracy</td><td className="n">{pct(s.decisions.match_status_accuracy, 2)}</td></tr>
                    <tr><td>Route queue accuracy</td><td className="n">{pct(s.decisions.route_queue_accuracy, 2)}</td></tr>
                    <tr><td>Approval path accuracy</td><td className="n">{pct(s.decisions.approval_path_accuracy, 2)}</td></tr>
                    <tr><td>Duplicate pair accuracy</td><td className="n">{pct(s.duplicates.correct_pair_rate, 2)}</td></tr>
                    <tr><td>Extraction exact match</td><td className="n">{pct(s.extraction.document_exact_match_rate, 2)}</td></tr>
                    {Object.entries(s.extraction.exact_match_by_layout).map(([l, v]) => (
                      <tr key={l}><td className="muted">· {l} documents ({v.documents})</td><td className="n">{pct(v.exact_match_rate, 2)}</td></tr>
                    ))}
                    {Object.entries(k.approval_path_mix).map(([p, n]) => (
                      <tr key={p}><td className="muted">Approval path {p}</td><td className="n">{n}</td></tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            </div>
          </>
        )
      }}
    </Loading>
  )
}
