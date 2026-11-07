import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client.js'
import { Badge, Card, Loading } from '../components/ui.jsx'
import { useDataset } from '../context/DatasetContext.jsx'
import { useApi } from '../hooks/useApi.js'
import { dt, label, money } from '../utils/format.js'

export default function ExceptionsPage() {
  const { dataset, version } = useDataset()
  const [params, setParams] = useSearchParams()
  const queue = params.get('queue') ?? ''
  const all = useApi(() => api.exceptions(dataset, {}), [dataset, version])
  const state = useApi(() => api.exceptions(dataset, { queue }), [dataset, version, queue])

  return (
    <>
      <div className="page-head">
        <h1>Exception queues</h1>
        <span className="muted">Every blocked invoice, routed to its owner with an SLA. Primary exception shown.</span>
      </div>
      <div className="chips">
        <button className={!queue ? 'chip on' : 'chip'} onClick={() => setParams({})}>All {all.data && `(${all.data.total})`}</button>
        {all.data && Object.entries(all.data.queues).map(([q, n]) => (
          <button key={q} className={queue === q ? 'chip on' : 'chip'} onClick={() => setParams({ queue: q })}>{label(q)} ({n})</button>
        ))}
      </div>
      <Loading state={state}>
        {(d) => (
          <Card title={`${d.total} open exceptions`}>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Exception</th><th>Invoice</th><th>Vendor</th><th className="n">Amount</th><th>Why</th><th>Owner</th><th>SLA due</th></tr></thead>
                <tbody>
                  {d.items.map((e) => (
                    <tr key={e.exception_id}>
                      <td><Badge value={e.exception_code} />{e.secondary_codes.length > 0 && <div className="small muted">+ {e.secondary_codes.map(label).join(', ')}</div>}</td>
                      <td><Link className="mono" to={`/invoices/${e.invoice_id}`}>{e.invoice_id}</Link></td>
                      <td>{e.vendor_name}</td>
                      <td className="n">{money(e.computed_total)}</td>
                      <td className="wrap">{e.detail}</td>
                      <td>{e.assigned_to?.name}<div className="small muted">{label(e.assigned_to?.role)}</div></td>
                      <td>{dt(e.sla_due_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </Loading>
    </>
  )
}
