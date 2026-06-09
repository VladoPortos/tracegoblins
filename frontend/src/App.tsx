import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router'
import { useMe, useSetupStatus } from './api/queries'
import { AppShell } from './shell/AppShell'
import { LoginPage } from './auth/LoginPage'
import { SetupWizard } from './auth/SetupWizard'
import { InviteAccept } from './auth/InviteAccept'
import { ChangePassword } from './auth/ChangePassword'
import { MfaSetupRequired } from './auth/MfaSetupRequired'
import { Dashboard } from './dashboard/Dashboard'
import { AnalyticsView } from './analytics/AnalyticsView'
import { AnalysisView } from './analysis/AnalysisView'
import { KbBrowse } from './kb/KbBrowse'
import { ProfileSettings } from './settings/ProfileSettings'
import { AppearanceSettings } from './settings/AppearanceSettings'
import { SecuritySettings } from './settings/SecuritySettings'
import { AdminUsers } from './admin/AdminUsers'
import { AdminTeams } from './admin/AdminTeams'
import { AwxControllers } from './settings/AwxControllers'
import { FullScreenSpinner } from './components/atoms/FullScreenSpinner'

function AdminRoute() {
  const me = useMe()
  if (me.isPending) return null
  if (me.data?.role !== 'admin') return <Navigate to="/" replace />
  return <Outlet />
}

function ProtectedRoute() {
  const me = useMe()
  const setup = useSetupStatus()
  const loc = useLocation()
  if (me.isPending || setup.isPending) return <FullScreenSpinner />
  if (setup.data?.needs_setup) return <Navigate to="/setup" replace />
  if (!me.data) return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  if (me.data.must_change_password) return <Navigate to="/change-password" replace />
  if (me.data.mfa_setup_required && loc.pathname !== '/security/setup') return <Navigate to="/security/setup" replace />
  return <Outlet />
}

function PublicOnly() {
  const me = useMe()
  const setup = useSetupStatus()
  if (me.isPending || setup.isPending) return <FullScreenSpinner />
  if (setup.data?.needs_setup) return <Navigate to="/setup" replace />
  if (me.data) return <Navigate to="/" replace />
  return <Outlet />
}

export function App() {
  return (
    <Routes>
      <Route element={<PublicOnly />}>
        <Route path="/login" element={<LoginPage />} />
      </Route>
      <Route path="/setup" element={<SetupWizard />} />
      <Route path="/invite/:token" element={<InviteAccept />} />
      <Route path="/change-password" element={<ChangePassword />} />
      <Route path="/security/setup" element={<MfaSetupRequired />} />

      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route index element={<Dashboard />} />
          <Route path="analytics" element={<AnalyticsView />} />
          <Route path="runs/:id" element={<AnalysisView />} />
          <Route path="kb" element={<KbBrowse />} />
          <Route path="settings" element={<ProfileSettings />} />
          <Route path="settings/appearance" element={<AppearanceSettings />} />
          <Route path="settings/security" element={<SecuritySettings />} />
          <Route element={<AdminRoute />}>
            <Route path="admin/awx" element={<AwxControllers />} />
            <Route path="admin/users" element={<AdminUsers />} />
            <Route path="admin/teams" element={<AdminTeams />} />
          </Route>
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
