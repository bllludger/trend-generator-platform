import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { MainLayout } from '@/components/layout/MainLayout'
import { LoginPage } from '@/pages/LoginPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { UsersPage } from '@/pages/UsersPage'
import { JobsPage } from '@/pages/JobsPage'
import { PacksPage } from '@/pages/PacksPage'
import { PaymentsPage } from '@/pages/PaymentsPage'
import { BankTransferPage } from '@/pages/BankTransferPage'
import { SecurityPage } from '@/pages/SecurityPage'
import { AuditPage } from '@/pages/AuditPage'
import { TelemetryPage } from '@/pages/TelemetryPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { MasterPromptPage } from '@/pages/MasterPromptPage'
import { TelegramMessagesPage } from '@/pages/TelegramMessagesPage'
import { BroadcastPage } from '@/pages/BroadcastPage'
import { CleanupPage } from '@/pages/CleanupPage'
import { CopyStylePage } from '@/pages/CopyStylePage'
import { TrendsPage } from '@/pages/TrendsPage'
import PromptPlaygroundPage from '@/pages/PromptPlaygroundPage'
import ReferralsPage from '@/pages/ReferralsPage'

function ProtectedLayout() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }
  return <MainLayout />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<ProtectedLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="users" element={<UsersPage />} />
          <Route path="jobs" element={<JobsPage />} />
          <Route path="packs" element={<PacksPage />} />
          <Route path="payments" element={<PaymentsPage />} />
          <Route path="bank-transfer" element={<BankTransferPage />} />
          <Route path="security" element={<SecurityPage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="telemetry" element={<TelemetryPage />} />
          <Route path="trends" element={<TrendsPage />} />
          <Route path="prompt-playground" element={<PromptPlaygroundPage />} />
          <Route path="copy-style" element={<CopyStylePage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="master-prompt" element={<MasterPromptPage />} />
          <Route path="transfer-policy" element={<Navigate to="/master-prompt" replace />} />
          <Route path="telegram-messages" element={<TelegramMessagesPage />} />
          <Route path="broadcast" element={<BroadcastPage />} />
          <Route path="referrals" element={<ReferralsPage />} />
          <Route path="cleanup" element={<CleanupPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
