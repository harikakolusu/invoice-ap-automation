import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client.js'
import { Badge, Card, Field, Loading } from '../components/ui.jsx'
import { useDataset } from '../context/DatasetContext.jsx'
import { useApi } from '../hooks/useApi.js'
import { dt, label, money } from '../utils/format.js'

export default function InvoiceDetailPage() {
  const { invoiceId } = useParams()
  const { dataset, version } = useDataset()
  const state = useApi(() => api.invoice(dataset, invoiceId), [dataset, version, invoiceId])

  return (
    <Loading state={state}>
      {(d) => {
        const dec = d.decision
        const x = d.extracted
        return (
          <>
            <div className="page-head">
              <div>
                <Link to="/invoices" className="muted">← Invoices</Link>
                <h1 className="mono">{dec.invoice_id}</h1>
                <span className="muted">{dec.vendor_name} · {dec.vendor_invoice_number} · received {dt(dec.received_at)} via {label(dec.channel)}</span>
              </div>
              <div className="head-right">
                <div className="big">{money(dec.computed_total)}</div>
                <Badge value={dec.final_status} />
              </div>
            </div>

            <div className="grid3">
              <Card title="Decision">
                <Field k="Match status" v={<Badge value={dec.match_status} />} />
                <Field k="Primary exception" v={dec.primary_exception ? <Badge value={dec.primary_exception} /> : 'None'} />
                <Field k="All exceptions" v={dec.exception_codes ? dec.exception_codes.split(';').map(label).join(', ') : 'None'} />
                <Field k="Routed to" v={dec.route_queue ? `${label(dec.route_queue)} · ${dec.assigned_to?.name}` : '—'} />
                <Field k="Approval path" v={dec.approval_path || '—'} />
                {dec.duplicate_of_invoice_id && (
                  <Field k="Duplicate of" v={<Link className="mono" to={`/invoices/${dec.duplicate_of_invoice_id}`}>{dec.duplicate_of_invoice_id}</Link>} />
                )}
              </Card>
              <Card title="Extracted header">
                <Field k="Vendor tax ID" v={x.vendor_tax_id} />
                <Field k="Invoice date" v={x.invoice_date} />
                <Field k="PO number" v={x.po_number || 'none (non-PO)'} />
                <Field k="Terms" v={x.payment_terms} />
                <Field k="Subtotal / tax / stated total" v={`${money(x.subtotal)} / ${money(x.tax_amount)} / ${money(x.stated_total)}`} />
                <Field k="Layout · confidence" v={`${x.layout} · ${Number(x.confidence).toFixed(2)}`} />
              </Card>
              <Card title="Review against ground truth">
                {d.ground_truth ? (
                  <>
                    <p className="muted small">Answer key for review only; the pipeline never reads it.</p>
                    <Field k="Scenario" v={label(d.ground_truth.scenario)} />
                    <Check k="Primary exception" exp={d.ground_truth.expected_primary_exception} got={dec.primary_exception} />
                    <Check k="Match status" exp={d.ground_truth.expected_match_status} got={dec.match_status} />
                    <Check k="Final status" exp={d.ground_truth.expected_final_status} got={dec.final_status} />
                    {d.ground_truth.injected_detail && <Field k="Injected" v={d.ground_truth.injected_detail} />}
                  </>
                ) : <span className="muted">No label.</span>}
              </Card>
            </div>

            <Copilot dataset={dataset} invoiceId={dec.invoice_id} onHold={dec.final_status === 'ON_HOLD'} />

            {d.exceptions.length > 0 && (
              <Card title="Exceptions">
                <table>
                  <thead><tr><th>Code</th><th>Detail</th><th>Expected</th><th>Actual</th><th>Queue / owner</th><th>SLA due</th></tr></thead>
                  <tbody>
                    {d.exceptions.map((e) => (
                      <tr key={e.exception_id}>
                        <td><Badge value={e.exception_code} />{e.is_primary === 'true' && <span className="muted small"> primary</span>}</td>
                        <td>{e.detail}</td><td className="mono">{e.expected_value || '—'}</td><td className="mono">{e.actual_value || '—'}</td>
                        <td>{label(e.queue)} · {e.assigned_to?.name}</td><td>{dt(e.sla_due_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            )}

            <Card title="Invoice lines (extracted) and receipt allocation">
              <div className="table-wrap">
                <table>
                  <thead><tr><th>#</th><th>SKU</th><th>Description</th><th className="n">Qty</th><th className="n">Unit price</th><th>Tax</th><th className="n">Amount</th><th>Matched to receipt lines</th></tr></thead>
                  <tbody>
                    {d.lines.map((l) => (
                      <tr key={l.line_number}>
                        <td>{l.line_number}</td><td className="mono">{l.sku}</td><td>{l.description}</td>
                        <td className="n">{l.quantity}</td><td className="n">{money(l.unit_price)}</td><td>{l.tax_code}</td>
                        <td className="n">{money(l.line_amount)}</td>
                        <td className="mono small">{l.matches.map((m) => `${m.grn_line_id} × ${m.matched_qty}`).join(', ') || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            {d.purchase_order && (
              <Card title={`Purchase order ${d.purchase_order.po_id} · ${label(d.purchase_order.status)} · requester ${d.purchase_order.requester?.name}`}>
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>#</th><th>SKU</th><th>Description</th><th className="n">Ordered</th><th className="n">PO price</th><th>Tax</th></tr></thead>
                    <tbody>
                      {d.purchase_order.lines.map((l) => (
                        <tr key={l.po_line_id}><td>{l.line_number}</td><td className="mono">{l.sku}</td><td>{l.description}</td>
                          <td className="n">{l.quantity}</td><td className="n">{money(l.unit_price)}</td><td>{l.tax_code}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="muted small">Receipts: {d.purchase_order.receipts.map((g) => `${g.grn_id} (${g.receipt_date})`).join(', ') || 'none posted'}</p>
              </Card>
            )}

            <div className="grid2">
              <Card title="Audit trail">
                <ol className="timeline">
                  {d.events.map((e) => (
                    <li key={e.event_id}>
                      <b>{label(e.to_state)}</b> <span className="muted">{dt(e.event_ts)} · {e.actor}</span>
                      {e.detail && <div className="small muted">{e.detail}</div>}
                    </li>
                  ))}
                </ol>
                {d.approvals.map((a) => (
                  <Field key={a.approval_id} k={`Approval L${a.level}`} v={`${a.approver?.name ?? 'System'} · ${a.policy_rule} · ${dt(a.decided_at)}`} />
                ))}
                {d.payment && <Field k="Payment" v={`${d.payment.payment_id} · ${money(d.payment.amount)} · ${d.payment.method} · scheduled ${d.payment.scheduled_date}`} />}
              </Card>
              <Card title={`Raw document · ${d.document.document_id}`}>
                <pre className="doc">{d.document.text}</pre>
              </Card>
            </div>
          </>
        )
      }}
    </Loading>
  )
}

function Check({ k, exp, got }) {
  const ok = (exp || '') === (got || '')
  return <Field k={k} v={<span className={ok ? 'ok-text' : 'bad-text'}>{ok ? '✓' : '✗'} expected {label(exp) || 'none'}</span>} />
}

function Copilot({ dataset, invoiceId, onHold }) {
  const [state, setState] = useState({ busy: false, data: null, error: '' })
  const ask = async () => {
    setState({ busy: true, data: null, error: '' })
    try { setState({ busy: false, data: await api.copilot(dataset, invoiceId), error: '' }) }
    catch (e) { setState({ busy: false, data: null, error: e.message }) }
  }
  const r = state.data
  return (
    <Card title="AI exception copilot · Claude" actions={
      <button onClick={ask} disabled={state.busy}>{state.busy ? 'Asking Claude…' : onHold ? 'Explain & draft follow-up' : 'Explain decision'}</button>}>
      <p className="muted small">Advisory only: the deterministic controls made the decision; Claude explains it and drafts the next message. It never sees the answer key.</p>
      {state.error && <div className="alert">{state.error}</div>}
      {r && (
        <>
          <Field k="Summary" v={r.summary} />
          <Field k="Root cause" v={r.root_cause} />
          <Field k="Recommended action" v={r.recommended_action} />
          <Field k="Confidence" v={r.confidence} />
          {r.draft_message?.body && (
            <div className="draft">
              <div className="small muted">Draft to {r.draft_message.recipient}</div>
              <b>{r.draft_message.subject}</b>
              <pre>{r.draft_message.body}</pre>
            </div>
          )}
          <div className="small muted">{r.llm_usage?.model} · {r.llm_usage?.input_tokens} in / {r.llm_usage?.output_tokens} out tokens</div>
        </>
      )}
    </Card>
  )
}
