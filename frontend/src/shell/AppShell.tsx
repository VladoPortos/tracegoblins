import { Outlet } from 'react-router'
import { TopBar } from './TopBar'
import { useMe } from '../api/queries'
import { FullScreenSpinner } from '../components/atoms/FullScreenSpinner'

export function AppShell() {
  const me = useMe()
  if (me.isPending) return <FullScreenSpinner />
  if (!me.data) return null // ProtectedRoute will redirect
  return (
    <div className="col" style={{ height: '100%' }}>
      <TopBar me={me.data} />
      <div className="grow" style={{ minHeight: 0 }}><Outlet /></div>
    </div>
  )
}
