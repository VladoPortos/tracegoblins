import type { ReactNode } from 'react'
import { useNavigate, useLocation } from 'react-router'
import { Glyph } from '../components/atoms/Glyph'
export function SettingsLayout({ children }: { children: ReactNode }) {
  const nav = useNavigate()
  const loc = useLocation()

  const tabs: [string, string, string][] = [
    ['/settings', 'Profile', 'users'],
    ['/settings/appearance', 'Appearance', 'sun'],
    ['/settings/security', 'Security', 'shield'],
  ]
  return (
    <div className="col scroll" style={{ height: '100%' }}>
      <div style={{ maxWidth: 820, width: '100%', margin: '0 auto', padding: '28px clamp(20px,4vw,40px) 60px' }}>
        <button className="btn btn-ghost sm" onClick={() => nav('/')} style={{ marginBottom: 14 }}><Glyph name="chevL" size={15} />Back to logs</button>
        <h1 className="h1" style={{ marginBottom: 4 }}>Settings</h1>
        <p className="muted" style={{ fontSize: 13.5, marginBottom: 22 }}>Manage your profile and appearance.</p>
        <div className="row gap4" style={{ alignItems: 'flex-start' }}>
          <div className="col" style={{ gap: 2, width: 184, flex: 'none' }}>
            {tabs.map(([to, label, ic]) => (
              <button key={to} onClick={() => nav(to)} className={'btn ' + (loc.pathname === to ? 'btn-primary' : 'btn-ghost')} style={{ justifyContent: 'flex-start' }}>
                <Glyph name={ic} size={15} />{label}
              </button>
            ))}
          </div>
          <div className="grow card" style={{ padding: 20 }}>{children}</div>
        </div>
      </div>
    </div>
  )
}
