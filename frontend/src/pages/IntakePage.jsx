import { useState } from 'react'
import { api } from '../api/client.js'
import { Card, Field } from '../components/ui.jsx'
import { useDataset } from '../context/DatasetContext.jsx'
import { money } from '../utils/format.js'

export default function IntakePage() {
  const { dataset } = useDataset()
  const [text, setText] = useState('')
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [useLlm, setUseLlm] = useState(true)

  const loadSample = async (params) => {
    setErr('')
    try {
      setText((await api.sample(dataset, params)).text)
      setRes(null)
    } catch (e) { setErr(e.message) }
  }

  const run = async () => {
    setBusy(true); setErr('')
    try { setRes(await api.extract(dataset, text, useLlm)) } catch (e) { setErr(e.message); setRes(null) }
    setBusy(false)
  }

  return (
    <>
      <div className="page-head">
        <h1>Intake preview</h1>
        <span className="muted">Paste a raw invoice. Rules read the known layouts (PDF text, email, EDI); Claude reads anything else, like a free-form letter. Fields are pre-checked against master data. Nothing is saved.</span>
      </div>
      <div className="grid2">
        <Card title="Document" actions={
          <div className="row">
            <button className="ghost" onClick={() => loadSample({ status: 'PAYMENT_READY' })}>Sample: clean</button>
            <button className="ghost" onClick={() => loadSample({ status: 'ON_HOLD' })}>Sample: exception</button>
            <button className="ghost" onClick={() => loadSample({ style: 'unstructured' })}>Sample: free-form letter</button>
          </div>}>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={22} spellCheck={false}
            placeholder="Paste invoice text here…" aria-label="Invoice document text" />
          <div className="row">
            <button onClick={run} disabled={busy || text.trim().length < 10}>{busy ? 'Extracting…' : 'Extract fields'}</button>
            <label className="toggle"><input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} /> Claude fallback when rules can't read it</label>
            {err && <span className="bad-text">{err}</span>}
          </div>
        </Card>
        <Card title="Result">
          {!res ? <span className="muted">Run extraction to see fields and checks.</span> : (
            <>
              <ul className="checks">
                {res.checks.map((c) => <li key={c.check} className={c.ok ? 'ok-text' : 'bad-text'}>{c.ok ? '✓' : '✗'} {c.check}</li>)}
              </ul>
              <Field k="Extracted by" v={res.extracted.extraction_method === 'LLM' ? 'Claude (LLM fallback)' : 'Rules'} />
              {res.extracted.llm_error && <Field k="LLM note" v={res.extracted.llm_error} />}
              <Field k="Layout · confidence" v={`${res.extracted.layout} · ${Number(res.extracted.confidence).toFixed(2)}`} />
              <Field k="Vendor" v={res.vendor ? `${res.vendor.vendor_name} (${res.vendor.vendor_id}, ${res.vendor.status})` : `unknown tax ID ${res.extracted.vendor_tax_id ?? ''}`} />
              <Field k="Invoice number · date" v={`${res.extracted.vendor_invoice_number ?? '—'} · ${res.extracted.invoice_date ?? '—'}`} />
              <Field k="PO" v={res.extracted.po_number ?? 'none (non-PO)'} />
              <Field k="Stated total" v={money(res.extracted.stated_total)} />
              <Field k="Recomputed from lines" v={`${money(res.computed.subtotal)} + ${money(res.computed.tax_amount)} tax = ${money(res.computed.total)}`} />
              <table>
                <thead><tr><th>SKU</th><th className="n">Qty</th><th className="n">Price</th><th>Tax</th><th className="n">Amount</th></tr></thead>
                <tbody>
                  {res.lines.map((l) => (
                    <tr key={l.line_number}><td className="mono">{l.sku}</td><td className="n">{l.quantity}</td>
                      <td className="n">{money(l.unit_price)}</td><td>{l.tax_code}</td><td className="n">{money(l.line_amount)}</td></tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </Card>
      </div>
    </>
  )
}
