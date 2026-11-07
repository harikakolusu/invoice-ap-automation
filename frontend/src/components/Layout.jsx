import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from '../api/client.js'
import { useDataset } from '../context/DatasetContext.jsx'

const NAV = [
  ['/', 'Dashboard'],
  ['/invoices', 'Invoices'],
  ['/exceptions', 'Exception queues'],
  ['/intake', 'Intake preview (AI)'],
  ['/validation', 'Data validation'],
]

export default function Layout() {
  const { datasets, dataset, setDataset, refresh, error } = useDataset()
  const [run, setRun] = useState({ busy: false, msg: '' })
  const [llm, setLlm] = useState(null)
  useEffect(() => { api.llmStatus().then(setLlm).catch(() => setLlm(null)) }, [])

  const rerun = async () => {
    setRun({ busy: true, msg: 'Regenerating and reprocessing…' })
    try {
      const r = await api.run(dataset)
      setRun({ busy: false, msg: `Done: validation ${r.validation}, acceptance ${r.acceptance.filter((a) => a === 'PASS').length}/${r.acceptance.length}` })
      refresh()
    } catch (e) {
      setRun({ busy: false, msg: e.message })
    }
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">AP Automation<small>invoice → payment</small></div>
        <nav>
          {NAV.map(([to, name]) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>
              {name}
            </NavLink>
          ))}
        </nav>
        {llm && (
          <div className="ai-status" title={llm.hint ?? ''}>
            <span className={`dot ${llm.available ? 'on' : ''}`} />
            AI: Claude <span className="mono">{llm.model}</span>
            <small>{llm.available ? 'connected' : 'not configured (rules only)'}</small>
          </div>
        )}
        <div className="side-foot">
          <label htmlFor="ds">Dataset</label>
          <select id="ds" value={dataset ?? ''} onChange={(e) => setDataset(e.target.value)}>
            {datasets.map((d) => (
              <option key={d.name} value={d.name}>{d.name} · {d.invoices.toLocaleString()} invoices</option>
            ))}
          </select>
          <button onClick={rerun} disabled={!dataset || run.busy}>{run.busy ? 'Running…' : 'Re-run pipeline'}</button>
          {run.msg && <div className="side-msg">{run.msg}</div>}
        </div>
      </aside>
      <main className="content">
        {error && <div className="alert">Backend not reachable ({error.message}). Start it with <code>python -m ap_automation serve</code>.</div>}
        {dataset ? <Outlet /> : !error && <div className="muted pad">Loading datasets…</div>}
      </main>
    </div>
  )
}
