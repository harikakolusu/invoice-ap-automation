import { api } from '../api/client.js'
import { Badge, Card, Loading } from '../components/ui.jsx'
import { useDataset } from '../context/DatasetContext.jsx'
import { useApi } from '../hooks/useApi.js'
import { label } from '../utils/format.js'

export default function ValidationPage() {
  const { dataset, version } = useDataset()
  const state = useApi(() => api.validation(dataset), [dataset, version])

  return (
    <Loading state={state}>
      {(v) => {
        const groups = {}
        v.checks.forEach((c) => (groups[c.category] ??= []).push(c))
        return (
          <>
            <div className="page-head">
              <h1>Data validation</h1>
              <span className="muted"><Badge value={v.status} /> {v.checks_run} checks, {v.checks_failed} failed. Labelled anomalies are allowed; anything else fails.</span>
            </div>
            {Object.entries(groups).map(([cat, checks]) => (
              <Card key={cat} title={`${label(cat)} (${checks.length})`}>
                <table>
                  <thead><tr><th>Check</th><th>Status</th><th className="n">Violations</th><th className="n">Labelled anomalies</th><th>Note</th></tr></thead>
                  <tbody>
                    {checks.map((c) => (
                      <tr key={c.check}>
                        <td>{c.check}</td><td><Badge value={c.status} /></td>
                        <td className="n">{c.violations}</td><td className="n">{c.labelled_anomalies_allowed || ''}</td>
                        <td className="muted small wrap">{c.note || c.sample.join(', ')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            ))}
          </>
        )
      }}
    </Loading>
  )
}
