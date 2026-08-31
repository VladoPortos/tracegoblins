import type { PositionedNode } from './layout'

const STATUS_GLYPH: Record<string, string> = { ok: '✓', changed: '~', failed: '✕', unreachable: '⚠', skipped: '–', never_run: '◌' }
const statusVar = (s: string) => `var(--${s === 'unreachable' ? 'failed' : s === 'never_run' ? 'skipped' : s})`

export function PathNodeCard({ node: n, selected, onSelect, onEnter, reduced, notTaken = false }: {
  node: PositionedNode; selected: boolean; reduced: boolean; notTaken?: boolean
  onSelect: (id: string) => void; onEnter: (t: { type: 'container' | 'loop'; id: string }, label?: string) => void
}) {
  const isContainer = n.type === 'role' || n.type === 'block' || n.type === 'include' || n.type === 'play'
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
    opacity: notTaken ? 0.42 : 1,
    filter: notTaken ? 'grayscale(0.7)' : 'none',
    boxShadow: selected ? '0 0 0 2px var(--flow), 0 8px 30px var(--flow-glow)'
      : isContainer ? '0 3px 14px rgba(0,0,0,.22), 6px 7px 0 0 var(--surface-2), 6px 7px 0 1px var(--border), 12px 14px 0 0 var(--surface-2), 12px 14px 0 1px var(--border)'
      : '0 3px 14px rgba(0,0,0,.22)',
    transition: 'opacity .25s, filter .25s, box-shadow .2s',
    animation: selected && !reduced && isTaskish ? 'haloPulse 2.4s ease-in-out infinite' : 'none',
  }
  const glyph = isContainer ? '▣' : isLoop ? '⟳' : isWhen ? '⎇' : isItem ? '»' : (STATUS_GLYPH[n.status] || '•')

  // Module family short-name on the card face (real resolved_action) — strip the collection
  // prefix so "ansible.builtin.apt" reads as "apt". Task/result nodes only; null when absent.
  const shortMod = isTaskish && n.action ? n.action.split('.').pop() : null
  const baseSub = n.host_count != null ? `${n.host_count} hosts` : n.sub
  const subText = shortMod ? (baseSub ? `${shortMod} · ${baseSub}` : shortMod) : baseSub

  return (
    <div data-testid={`node-${n.id}`} data-node-type={n.type} style={base}
      onClick={(e) => { e.stopPropagation(); onSelect(n.id) }}
      onDoubleClick={(e) => { if (n.enter_to) { e.stopPropagation(); onEnter(n.enter_to, n.label) } }}>
      <div className="row gap2">
        <span className="mono" style={{ fontSize: isContainer || isLoop || isWhen ? 18 : 13, color: accent }}>{glyph}</span>
        <span className="mono truncate" style={{ fontSize: 13, fontWeight: 600 }}>
          <span>{n.label}</span>
          {isLoop && <span aria-hidden="true"> ×{n.item_count ?? '?'}</span>}
        </span>
      </div>
      <div className="row gap2 dim mono" style={{ fontSize: 11 }}>
        <span className="truncate">{subText}</span>
        {isLoop && <span style={{ color: 'var(--failed)' }}>{n.fail_count ? `· ${n.fail_count} failed` : ''}</span>}
        {isTaskish && n.is_handler && (
          <span
            data-testid="handler-badge"
            title="handler — ran because it was notified"
            style={{
              marginLeft: 'auto', flex: '0 0 auto', color: 'var(--changed)',
              border: '1px solid var(--changed)', borderRadius: 5, padding: '0 5px',
              fontSize: 9.5, fontWeight: 600, letterSpacing: '.03em',
            }}
          >handler</span>
        )}
      </div>
      {isWhen && n.condition && <span className="mono" style={{ fontSize: 11, color: 'var(--included)' }}>{n.condition}</span>}
      {n.enter_to && (
        <button
          type="button"
          className="btn btn-ghost sm"
          aria-label={`Enter ${n.label}`}
          onClick={(e) => { e.stopPropagation(); onEnter(n.enter_to!, n.label) }}
          style={{ alignSelf: 'flex-start', fontSize: 10.5, color: 'var(--flow)' }}
        >
          {isLoop ? `Step into ${n.item_count} iterations` : `Enter ${n.child_count} tasks`} →
        </button>
      )}
    </div>
  )
}
