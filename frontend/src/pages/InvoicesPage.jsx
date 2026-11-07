import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client.js'
import { Badge, Card, Loading } from '../components/ui.jsx'
import { useDataset } from '../context/DatasetContext.jsx'
import { useApi } from '../hooks/useApi.js'
import { label, money } from '../utils/format.js'

const EXCEPTIONS = ['DUPLICATE_INVOICE', 'VENDOR_CLOSED', 'TOTAL_MISMATCH', 'DATE_BEFORE_PO', 'MISSING_RECEIPT',
  'TAX_MISMATCH', 'QTY_EXCEEDS_PO', 'QTY_EXCEEDS_RECEIPT', 'PRICE_VARIANCE']
const PAGE = 50

export default function InvoicesPage() {
  const { dataset, version } = useDataset()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const status = params.get('status') ?? ''
  const exception = params.get('exception') ?? ''
  const q = params.get('q') ?? ''
  const page = Number(params.get('page') ?? 0)
  const [search, setSearch] = useState(q)
  useEffect(() => setSearch(q), [q])

  const state = useApi(() => api.invoices(dataset, { status, exception, q, limit: PAGE, offset: page * PAGE }),
    [dataset, version, status, exception, q, page])

  const set = (k, v) => {
    const next = new URLSearchParams(params)
    v ? next.set(k, v) : next.delete(k)
    if (k !== 'page') next.delete('page')
    setParams(next)
  }

  return (
    <>
      <div className="page-head"><h1>Invoices</h1></div>
      <div className="filters">
        <select value={status} onChange={(e) => set('status', e.target.value)} aria-label="Status">
          <option value="">All statuses</option>
          <option value="PAYMENT_READY">Payment ready</option>
          <option value="ON_HOLD">On hold</option>
        </select>
        <select value={exception} onChange={(e) => set('exception', e.target.value)} aria-label="Exception">
          <option value="">All exceptions</option>
          {EXCEPTIONS.map((c) => <option key={c} value={c}>{label(c)}</option>)}
        </select>
        <form onSubmit={(e) => { e.preventDefault(); set('q', search.trim()) }}>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search invoice, PO, vendor, number…" />
        </form>
      </div>
      <Loading state={state}>
        {(d) => (
          <Card title={`${d.total.toLocaleString()} invoices · ${money(d.value_usd)}`}
            actions={<Pager page={page} total={d.total} onPage={(p) => set('page', p || '')} />}>
            <div className="table-wrap">
              <table className="clickable">
                <thead>
                  <tr><th>Invoice</th><th>Vendor</th><th>PO</th><th>Date</th><th className="n">Total</th>
                    <th>Match</th><th>Primary exception</th><th>Status</th><th>Owner / approval</th></tr>
                </thead>
                <tbody>
                  {d.items.map((r) => (
                    <tr key={r.invoice_id} onClick={() => navigate(`/invoices/${r.invoice_id}`)}>
                      <td><Link to={`/invoices/${r.invoice_id}`} className="mono">{r.invoice_id}</Link></td>
                      <td>{r.vendor_name}</td>
                      <td className="mono">{r.po_id || <span className="muted">non-PO</span>}</td>
                      <td>{r.invoice_date}</td>
                      <td className="n">{money(r.computed_total)}</td>
                      <td><Badge value={r.match_status} /></td>
                      <td>{r.primary_exception ? <Badge value={r.primary_exception} /> : <span className="muted">—</span>}</td>
                      <td><Badge value={r.final_status} /></td>
                      <td className="muted">{r.assigned_to ? `${r.assigned_to.name} (${label(r.route_queue)})` : r.approval_path}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {d.items.length === 0 && <div className="muted pad">No invoices match these filters.</div>}
          </Card>
        )}
      </Loading>
    </>
  )
}

function Pager({ page, total, onPage }) {
  const last = Math.max(0, Math.ceil(total / PAGE) - 1)
  return (
    <div className="pager">
      <button className="ghost" disabled={page <= 0} onClick={() => onPage(page - 1)}>Prev</button>
      <span className="muted">{page + 1} / {last + 1}</span>
      <button className="ghost" disabled={page >= last} onClick={() => onPage(page + 1)}>Next</button>
    </div>
  )
}
