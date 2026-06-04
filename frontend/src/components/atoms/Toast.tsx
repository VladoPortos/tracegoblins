import { useEffect } from 'react'
export function Toast({ message, onDone }: { message: string | null; onDone: () => void }) {
  useEffect(() => { if (message) { const t = setTimeout(onDone, 2600); return () => clearTimeout(t) } }, [message, onDone])
  if (!message) return null
  return (
    <div style={{ position: 'fixed', bottom: 22, left: '50%', transform: 'translateX(-50%)', zIndex: 90,
                  background: 'var(--text)', color: 'var(--bg)', padding: '10px 16px', borderRadius: 10,
                  boxShadow: 'var(--shadow-3)', fontSize: 13, fontWeight: 500 }}>{message}</div>
  )
}
