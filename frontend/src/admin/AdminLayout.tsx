import type { ReactNode } from 'react'
import { useNavigate, useLocation } from 'react-router'

export function AdminLayout({ children, action }: { children: ReactNode; action?: ReactNode }) {
  const nav = useNavigate()
  const loc = useLocation()
  const tabs: [string, string][] = [
    ['/admin/users', 'Users'],
    ['/admin/teams', 'Teams'],
    ['/admin/awx', 'AWX Controllers'],
  ]
  return (
    <div className="col scroll" style={{ height: '100%' }}>
      <div style={{ maxWidth: 'var(--maxw)', width: '100%', margin: '0 auto', padding: '28px clamp(20px,4vw,40px) 64px' }}>
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
      </div>
    </div>
  )
}
