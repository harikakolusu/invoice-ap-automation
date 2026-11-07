import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import DashboardPage from './pages/DashboardPage.jsx'
import InvoicesPage from './pages/InvoicesPage.jsx'
import InvoiceDetailPage from './pages/InvoiceDetailPage.jsx'
import ExceptionsPage from './pages/ExceptionsPage.jsx'
import ValidationPage from './pages/ValidationPage.jsx'
import IntakePage from './pages/IntakePage.jsx'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="invoices" element={<InvoicesPage />} />
        <Route path="invoices/:invoiceId" element={<InvoiceDetailPage />} />
        <Route path="exceptions" element={<ExceptionsPage />} />
        <Route path="validation" element={<ValidationPage />} />
        <Route path="intake" element={<IntakePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
