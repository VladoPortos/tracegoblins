import type { ReactNode } from 'react'
import { Glyph } from '../components/atoms/Glyph'
export function AuthLayout({ eyebrow, title, sub, children }: { eyebrow: string; title: string; sub?: string; children: ReactNode }) {
  return (
    <div className="col" style={{ height: '100%', overflow: 'auto' }}>
      <div style={{ maxWidth: 400, width: '100%', margin: 'auto', padding: '40px 28px' }}>
        <div className="row gap2" style={{ marginBottom: 24 }}>
          <span style={{ color: 'var(--accent)' }}><Glyph name="logo" size={26} /></span>
          <span style={{ fontWeight: 700, fontSize: 18, letterSpacing: '-.01em' }}>Tracegoblins</span>
        </div>
        <div className="eyebrow" style={{ marginBottom: 10 }}>{eyebrow}</div>
        <h1 className="h1" style={{ fontSize: 26, marginBottom: 8 }}>{title}</h1>
        {sub && <p className="muted" style={{ fontSize: 14, marginBottom: 24 }}>{sub}</p>}
        {children}
      </div>
    </div>
  )
}
