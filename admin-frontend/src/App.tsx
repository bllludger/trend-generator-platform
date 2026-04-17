import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { MainLayout } from '@/components/layout/MainLayout'
import { PaymentsLayout } from '@/components/layout/PaymentsLayout'
import { LoginPage } from '@/pages/LoginPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { UsersPage } from '@/pages/UsersPage'
import { UserDetailPage } from '@/pages/UserDetailPage'
import { JobsPage } from '@/pages/JobsPage'
import { PacksPage } from '@/pages/PacksPage'
import { PaymentsPage } from '@/pages/PaymentsPage'
import { BankTransferPage } from '@/pages/BankTransferPage'
import { SecurityPage } from '@/pages/SecurityPage'
import { AuditPage } from '@/pages/AuditPage'
import { TelemetryPage } from '@/pages/TelemetryPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { MasterPromptPage } from '@/pages/MasterPromptPage'
import { PreviewPolicyPage } from '@/pages/PreviewPolicyPage'
import { TelegramMessagesPage } from '@/pages/TelegramMessagesPage'
import { BroadcastPage } from '@/pages/BroadcastPage'
import { CleanupPage } from '@/pages/CleanupPage'
import { CopyStylePage } from '@/pages/CopyStylePage'
import { TrendsPage } from '@/pages/TrendsPage'
import { TrendsAnalyticsPage } from '@/pages/TrendsAnalyticsPage'
import { TrendPosterPage } from '@/pages/TrendPosterPage'
import PromptPlaygroundPage from '@/pages/PromptPlaygroundPage'
import ReferralsPage from '@/pages/ReferralsPage'
import TrafficPage from '@/pages/TrafficPage'
import PhotoMergePage from '@/pages/PhotoMergePage'
import FaceIdPage from '@/pages/FaceIdPage'

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
          <Route path="users/:id" element={<UserDetailPage />} />
          <Route path="jobs" element={<JobsPage />} />
          <Route path="payments" element={<PaymentsLayout />}>
            <Route index element={<PaymentsPage />} />
            <Route path="packs" element={<PacksPage />} />
            <Route path="bank-transfer" element={<BankTransferPage />} />
          </Route>
          <Route path="packs" element={<Navigate to="/payments/packs" replace />} />
          <Route path="bank-transfer" element={<Navigate to="/payments/bank-transfer" replace />} />
          <Route path="security" element={<SecurityPage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="telemetry" element={<TelemetryPage />} />
          <Route path="trends" element={<TrendsPage />} />
          <Route path="trends-analytics" element={<TrendsAnalyticsPage />} />
          <Route path="trend-poster" element={<TrendPosterPage />} />
          <Route path="prompt-playground" element={<PromptPlaygroundPage />} />
          <Route path="copy-style" element={<CopyStylePage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="master-prompt" element={<MasterPromptPage />} />
          <Route path="preview-policy" element={<PreviewPolicyPage />} />
          <Route path="transfer-policy" element={<Navigate to="/master-prompt" replace />} />
          <Route path="telegram-messages" element={<TelegramMessagesPage />} />
          <Route path="broadcast" element={<BroadcastPage />} />
          <Route path="referrals" element={<ReferralsPage />} />
          <Route path="traffic" element={<TrafficPage />} />
          <Route path="cleanup" element={<CleanupPage />} />
          <Route path="photo-merge" element={<PhotoMergePage />} />
          <Route path="face-id" element={<FaceIdPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
