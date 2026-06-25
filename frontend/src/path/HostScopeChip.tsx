import { useState, useRef, useEffect } from 'react'

// HostScopeId is now a plain string: 'all' is the sentinel; individual host names are the ids.
export type HostScopeId = string

export function HostScopeChip({ hosts, value, onPick }: { hosts: string[]; value: HostScopeId; onPick: (id: HostScopeId) => void }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement | null>(null)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const label = value === 'all' ? 'All hosts' : value

  const allOption = { id: 'all', label: 'All hosts', tag: 'aggregate' }
  const hostOptions = hosts.map(h => ({ id: h, label: h, tag: 'host' }))
  const options = [allOption, ...hostOptions]

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}>
      <button
        data-testid="host-scope-chip"
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          height: 32, padding: '0 11px', borderRadius: 8,
          background: 'var(--surface-2, var(--node-2, var(--surface)))',
          border: '1px solid var(--border)',
          color: 'var(--text)',
          fontFamily: "'IBM Plex Sans', sans-serif",
          fontSize: 12, cursor: 'pointer',
        }}
      >
        <span style={{ color: 'var(--dim)' }}>Hosts:</span>
        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontWeight: 500, fontFeatureSettings: '"zero"' }}>{label}</span>
        <span style={{ color: 'var(--dim)', fontSize: 9 }}>▾</span>
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: 38, right: 0,
          minWidth: 230,
          background: 'var(--panel, var(--surface))',
          border: '1px solid var(--border)',
          borderRadius: 10,
          boxShadow: '0 16px 44px rgba(0,0,0,0.45)',
          padding: 5, zIndex: 30,
        }}>
          {options.map(h => (
            <div
              key={h.id}
              onClick={() => { onPick(h.id); setOpen(false) }}
              style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '8px 10px', borderRadius: 7, cursor: 'pointer',
                color: 'var(--text)',
                background: value === h.id ? 'var(--flow-soft, rgba(99,179,237,.12))' : 'transparent',
                border: `1px solid ${value === h.id ? 'var(--flow-line, var(--flow))' : 'transparent'}`,
              }}
            >
              <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontFeatureSettings: '"zero"' }}>{h.label}</span>
              <span style={{ fontSize: 11, color: 'var(--dim)', marginLeft: 'auto' }}>{h.tag}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
