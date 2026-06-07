import { Link } from 'react-router'
import { Glyph } from '../components/atoms/Glyph'
import { KbStatusBadge } from '../components/atoms/KbStatusBadge'
import { KbLinkRow } from '../components/atoms/KbLinkRow'
import { useTaskKbSuggestion } from '../api/kb'
import { runWord } from '../components/atoms/format'

export function KbSuggestion({ runId, seq, onPromote }: { runId: string; seq: number; onPromote: () => void }) {
  const q = useTaskKbSuggestion(runId, seq, true)

  if (q.isPending) {
    return <div className="dim" style={{ fontSize: 11.5 }}>Checking the knowledge base…</div>
  }

  const sug = q.data ?? null
  if (!sug) {
    return (
      <div className="col" style={{ gap: 8, padding: 14, borderRadius: 10, border: '1px dashed var(--border-strong)', textAlign: 'center' }}>
        <span className="dim" style={{ fontSize: 11.5 }}>No matching entry in the knowledge base yet.</span>
        <button className="btn sm btn-primary" onClick={onPromote} style={{ alignSelf: 'center' }}>
          <Glyph name="sparkle" size={13} />Promote to KB
        </button>
      </div>
    )
  }

  const s = sug.signature
  const n = s.occurrence_count
  return (
    <div className="col" style={{ gap: 9, padding: 13, borderRadius: 10, border: '1px solid var(--border)', background: 'var(--surface-2)' }}>
      <div className="row gap2">
        <Glyph name="sparkle" size={14} style={{ color: 'var(--accent)' }} />
        <span className="eyebrow" style={{ color: 'var(--accent)' }}>Known issue</span>
        <div className="grow" />
        <KbStatusBadge status={s.status} />
      </div>
      <div className="h3" style={{ fontSize: 13.5, lineHeight: 1.35 }}>{s.title}</div>
      {s.where_it_lives && (
        <div className="row gap2" style={{ fontSize: 12, color: 'var(--text-2)' }}>
          <Glyph name="map" size={12} style={{ color: 'var(--text-3)' }} />
          <span style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{s.where_it_lives}</span>
        </div>
      )}
      {s.links.length > 0 && (
        <div className="row gap1 wrap">{s.links.map((l, i) => <KbLinkRow key={i} link={l} />)}</div>
      )}
      <div className="row gap2" style={{ fontSize: 11.5 }}>
        <Link className="chip" to="/kb" style={{ color: 'var(--accent)', textDecoration: 'none' }}>
          <Glyph name="sparkle" size={11} />{sug.exact ? 'exact match' : `fuzzy match · ${Math.round(sug.score * 100)}% match`} · also seen in {n} {runWord(n)}
        </Link>
      </div>
    </div>
  )
}
