import type { ReactNode } from 'react'
import { Glyph } from './Glyph'
export function EmptyState({ icon = 'inbox', title, sub, action }: { icon?: string; title: string; sub?: string; action?: ReactNode }) {
  return (
    <div className="col" style={{ alignItems: 'center', justifyContent: 'center', gap: 10, padding: '56px 24px', textAlign: 'center' }}>
      <div style={{ width: 46, height: 46, borderRadius: 12, display: 'grid', placeItems: 'center', background: 'var(--surface-2)', color: 'var(--text-3)', border: '1px solid var(--border)' }}>
        <Glyph name={icon} size={22} />
      </div>
      <div className="h2">{title}</div>
      {sub && <div className="muted" style={{ fontSize: 13, maxWidth: 360 }}>{sub}</div>}
      {action}
    </div>
  )
}
