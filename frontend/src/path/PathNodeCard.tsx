import type { PositionedNode } from './layout'

const STATUS_GLYPH: Record<string, string> = { ok: '✓', changed: '~', failed: '✕', unreachable: '⚠', skipped: '–' }
const statusVar = (s: string) => `var(--${s === 'unreachable' ? 'failed' : s})`

export function PathNodeCard({ node: n, selected, onSelect, onEnter, reduced }: {
  node: PositionedNode; selected: boolean; reduced: boolean
  onSelect: (id: string) => void; onEnter: (t: { type: 'container' | 'loop'; id: string }) => void
}) {
  const isContainer = n.type === 'role' || n.type === 'block' || n.type === 'include'
  const isLoop = n.type === 'loop', isWhen = n.type === 'when', isItem = n.type === 'item'
  const isTaskish = n.type === 'task' || n.type === 'result'
  const accent = isContainer || isWhen ? 'var(--included)' : isLoop ? 'var(--changed)' : isItem ? 'var(--dim)' : statusVar(n.status)
  const isFail = isTaskish && (n.status === 'failed' || n.status === 'unreachable')

  const base: React.CSSProperties = {
    position: 'absolute', left: 0, top: 0, transform: `translate(${n.x}px,${n.y}px)`,
    width: n.w, minHeight: n.h, boxSizing: 'border-box',
    background: isWhen ? 'var(--decision-bg)' : 'var(--surface-2)',
    border: `1px solid ${isFail ? 'var(--failed-line, var(--unreachable-line))' : 'var(--border)'}`,
    borderLeft: isWhen ? '1px solid var(--border)' : `3px solid ${accent}`,
    borderRadius: 13, padding: '11px 13px', display: 'flex', flexDirection: 'column', gap: 6,
    cursor: 'pointer', color: 'var(--text)',
    boxShadow: selected ? '0 0 0 2px var(--flow), 0 8px 30px var(--flow-glow)'
      : isContainer ? '0 3px 14px rgba(0,0,0,.22), 6px 7px 0 0 var(--surface-2), 6px 7px 0 1px var(--border), 12px 14px 0 0 var(--surface-2), 12px 14px 0 1px var(--border)'
      : '0 3px 14px rgba(0,0,0,.22)',
    animation: selected && !reduced && isTaskish ? 'haloPulse 2.4s ease-in-out infinite' : 'none',
  }
  const glyph = isContainer ? '▣' : isLoop ? '⟳' : isWhen ? '⎇' : isItem ? '»' : (STATUS_GLYPH[n.status] || '•')

  return (
    <div data-testid={`node-${n.id}`} data-node-type={n.type} style={base}
      onClick={(e) => { e.stopPropagation(); onSelect(n.id) }}
      onDoubleClick={(e) => { if (n.enter_to) { e.stopPropagation(); onEnter(n.enter_to) } }}>
      <div className="row gap2">
        <span className="mono" style={{ fontSize: isContainer || isLoop || isWhen ? 18 : 13, color: accent }}>{glyph}</span>
        <span className="mono truncate" style={{ fontSize: 13, fontWeight: 600 }}>{isLoop ? `${n.label} ×${n.item_count}` : n.label}</span>
      </div>
      <div className="row gap2 dim mono" style={{ fontSize: 11 }}>
        <span className="truncate">{n.host_count != null ? `${n.host_count} hosts` : n.sub}</span>
        {isLoop && <span style={{ color: 'var(--failed)' }}>{n.fail_count ? `· ${n.fail_count} failed` : ''}</span>}
      </div>
      {isWhen && n.condition && <span className="mono" style={{ fontSize: 11, color: 'var(--included)' }}>{n.condition}</span>}
      {n.enter_to && <span className="mono" style={{ fontSize: 10.5, color: 'var(--flow)' }}>{isLoop ? `step into ${n.item_count} iterations →` : `enter · ${n.child_count} tasks →`}</span>}
    </div>
  )
}
