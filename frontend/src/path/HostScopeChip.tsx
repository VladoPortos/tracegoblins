import { useState, useRef, useEffect, useMemo } from 'react'
import type { HostRecap } from '../api/client'
import { STATUS } from '../components/atoms/status'
import { StatusDot } from '../components/atoms/StatusDot'

// HostScopeId is now a plain string: 'all' is the sentinel; individual host names are the ids.
export type HostScopeId = string

// Show the filter box + scroll the menu only once the fleet is large enough to need it.
const FILTER_THRESHOLD = 8

// Worst outcome a host saw this run — drives the status dot. unreachable > failed > changed > ok;
// a host with only skips falls back to 'skipped'.
function worstStatus(r: HostRecap): string {
  if (r.unreachable > 0) return 'unreachable'
  if (r.failed > 0) return 'failed'
  if (r.changed > 0) return 'changed'
  if (r.ok > 0) return 'ok'
  return 'skipped'
}

interface HostOption { id: HostScopeId; label: string; status: string | null; tag: string }

export function HostScopeChip({ recap, value, onPick }: { recap: HostRecap[]; value: HostScopeId; onPick: (id: HostScopeId) => void }) {
  const [open, setOpen] = useState(false)
  const [needle, setNeedle] = useState('')
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

  // Reset the filter each time the menu opens so a stale needle never hides hosts.
  useEffect(() => { if (!open) setNeedle('') }, [open])

  const hostOptions: HostOption[] = useMemo(
    () => recap.map(r => {
      const st = worstStatus(r)
      return { id: r.host, label: r.host, status: st, tag: STATUS[st as keyof typeof STATUS]?.label ?? st }
    }),
    [recap],
  )

  const label = value === 'all' ? 'All hosts' : value
  const showFilter = hostOptions.length > FILTER_THRESHOLD
  const filtered = needle
    ? hostOptions.filter(h => h.label.toLowerCase().includes(needle.toLowerCase()))
    : hostOptions
  const allOption: HostOption = { id: 'all', label: 'All hosts', status: null, tag: 'aggregate' }

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}>
      <button
        type="button"
        data-testid="host-scope-chip"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        aria-controls="host-scope-options"
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
          minWidth: 244,
          background: 'var(--panel, var(--surface))',
          border: '1px solid var(--border)',
          borderRadius: 10,
          boxShadow: '0 16px 44px rgba(0,0,0,0.45)',
          padding: 5, zIndex: 30,
          display: 'flex', flexDirection: 'column',
        }}>
          {showFilter && (
            <input
              data-testid="host-scope-filter"
              autoFocus
              value={needle}
              onChange={e => setNeedle(e.target.value)}
              placeholder={`Filter ${hostOptions.length} hosts…`}
              style={{
                margin: '2px 2px 6px', padding: '7px 9px', borderRadius: 7,
                border: '1px solid var(--border)', background: 'var(--canvas, var(--surface))',
                color: 'var(--text)', fontFamily: "'IBM Plex Mono', monospace", fontSize: 12,
              }}
            />
          )}
          <div
            id="host-scope-options"
            role="listbox"
            aria-label="Host scope"
            style={{ maxHeight: 320, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}
          >
            {/* 'All hosts' aggregate stays pinned and is never filtered out */}
            {[allOption, ...filtered].map(h => (
              <button
                type="button"
                role="option"
                aria-selected={value === h.id}
                key={h.id}
                data-testid={`host-option-${h.id}`}
                onClick={() => { onPick(h.id); setOpen(false) }}
                onKeyDown={(e) => {
                  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
                  e.preventDefault()
                  const options = Array.from(
                    e.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="option"]') ?? [],
                  )
                  const index = options.indexOf(e.currentTarget)
                  const direction = e.key === 'ArrowDown' ? 1 : -1
                  options[(index + direction + options.length) % options.length]?.focus()
                }}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  width: '100%', textAlign: 'left', font: 'inherit',
                  padding: '8px 10px', borderRadius: 7, cursor: 'pointer',
                  color: 'var(--text)',
                  background: value === h.id ? 'var(--flow-soft, rgba(99,179,237,.12))' : 'transparent',
                  border: `1px solid ${value === h.id ? 'var(--flow-line, var(--flow))' : 'transparent'}`,
                }}
              >
                {h.status && <StatusDot status={h.status} size={8} />}
                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontFeatureSettings: '"zero"' }}>{h.label}</span>
                <span className={h.status ? 'st-' + h.status : undefined}
                      style={{ fontSize: 11, color: h.status ? 'var(--c)' : 'var(--dim)', marginLeft: 'auto' }}>{h.tag}</span>
              </button>
            ))}
            {showFilter && filtered.length === 0 && (
              <div style={{ padding: '8px 10px', fontSize: 11, color: 'var(--dim)', fontFamily: "'IBM Plex Mono', monospace" }}>
                no hosts match “{needle}”
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
