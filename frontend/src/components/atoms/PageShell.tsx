import type { ReactNode } from 'react'

// Shared scrollable page wrapper: centered max-width column with the standard
// page padding. `narrow` is the 820px settings variant.
export function PageShell({ children, narrow = false }: { children: ReactNode; narrow?: boolean }) {
  return (
    <div className="col scroll" style={{ height: '100%' }}>
      <div style={{
        maxWidth: narrow ? 820 : 'var(--maxw)', width: '100%', margin: '0 auto',
        padding: narrow ? '28px clamp(20px,4vw,40px) 60px' : '28px clamp(20px,4vw,40px) 64px',
      }}>
        {children}
      </div>
    </div>
  )
}
