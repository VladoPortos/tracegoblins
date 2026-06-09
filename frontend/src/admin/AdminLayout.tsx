import type { ReactNode } from 'react'
import { useNavigate, useLocation } from 'react-router'
import { PageShell } from '../components/atoms/PageShell'

export function AdminLayout({ children, action }: { children: ReactNode; action?: ReactNode }) {
  const nav = useNavigate()
  const loc = useLocation()
  const tabs: [string, string][] = [
    ['/admin/users', 'Users'],
    ['/admin/teams', 'Teams'],
    ['/admin/awx', 'AWX Controllers'],
  ]
  return (
    <PageShell>
      <div className="row gap4" style={{ alignItems: 'flex-end', marginBottom: 20, flexWrap: 'wrap' }}>
        <div className="grow">
          <div className="eyebrow" style={{ marginBottom: 6 }}>Administration</div>
          <h1 className="h1">Manage your platform</h1>
        </div>
        {action}
      </div>
      <div className="seg" style={{ marginBottom: 20 }}>
        {tabs.map(([to, label]) => (
          <button key={to} aria-pressed={loc.pathname === to} onClick={() => nav(to)}>{label}</button>
        ))}
      </div>
      {children}
    </PageShell>
  )
}
