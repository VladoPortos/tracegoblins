import { useState } from 'react'
import { Glyph } from '../components/atoms/Glyph'
import { KbStatusBadge } from '../components/atoms/KbStatusBadge'
import { EmptyState } from '../components/atoms/EmptyState'
import { KbLinkRow } from '../components/atoms/KbLinkRow'
import { useMe } from '../api/queries'
import {
  useKbSignatures, useUpdateKbSignature, useDeleteKbSignature, usePromoteKbGlobal,
  KB_STATUS_VALUES, type KbSignatureOut, type KbStatus, type KbLink,
} from '../api/kb'

type Scope = 'all' | 'team' | 'global'

const runWord = (n: number) => (n === 1 ? 'run' : 'runs')

function DetailView({ sig, isAdmin, myTeamIds, onClose }: {
  sig: KbSignatureOut; isAdmin: boolean; myTeamIds: Set<string>; onClose: () => void
}) {
  const update = useUpdateKbSignature()
  const del = useDeleteKbSignature()
  const promoteGlobal = usePromoteKbGlobal()
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(sig.title)
  const [status, setStatus] = useState<KbStatus>(sig.status)
  const [description, setDescription] = useState(sig.description ?? '')
  const [isProblem, setIsProblem] = useState(sig.is_problem ?? '')
  const [whereItLives, setWhereItLives] = useState(sig.where_it_lives ?? '')

  const isGlobal = sig.team_id === null
  const canEdit = isGlobal ? isAdmin : (sig.team_id !== null && myTeamIds.has(sig.team_id))
  const canPromoteGlobal = isAdmin && !isGlobal

  const links: KbLink[] = sig.links
  const n = sig.occurrence_count

  const save = () => {
    update.mutate({
      id: sig.id,
      patch: {
        title: title.trim(), status, description: description.trim() || null,
        is_problem: isProblem.trim() || null, where_it_lives: whereItLives.trim() || null,
      },
    }, { onSuccess: () => setEditing(false) })
  }

  return (
    <div className="card" style={{ padding: 18 }}>
      <div className="row gap2" style={{ marginBottom: 12 }}>
        <button className="btn icon sm btn-ghost" aria-label="Back to list" onClick={onClose}><Glyph name="chevL" size={16} /></button>
        <KbStatusBadge status={sig.status} />
        <span className="chip">{isGlobal ? 'Global' : 'Team'}</span>
        <div className="grow" />
        <span className="chip mono" style={{ fontSize: 10.5 }}>seen in {n} {runWord(n)}</span>
      </div>

      {editing ? (
        <div className="col" style={{ gap: 10 }}>
          <div>
            <label className="field-label" htmlFor="kb-edit-title">Title</label>
            <input id="kb-edit-title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div>
            <label className="field-label" htmlFor="kb-edit-status">Status</label>
            <select id="kb-edit-status" className="input" value={status} onChange={(e) => setStatus(e.target.value as KbStatus)}>
              {KB_STATUS_VALUES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="field-label" htmlFor="kb-edit-where">Where it usually lives</label>
            <textarea id="kb-edit-where" className="textarea" value={whereItLives} onChange={(e) => setWhereItLives(e.target.value)} style={{ minHeight: 48, fontSize: 12.5 }} />
          </div>
          <div>
            <label className="field-label" htmlFor="kb-edit-problem">Is this actually a problem?</label>
            <textarea id="kb-edit-problem" className="textarea" value={isProblem} onChange={(e) => setIsProblem(e.target.value)} style={{ minHeight: 48, fontSize: 12.5 }} />
          </div>
          <div>
            <label className="field-label" htmlFor="kb-edit-desc">Description / fix</label>
            <textarea id="kb-edit-desc" className="textarea" value={description} onChange={(e) => setDescription(e.target.value)} style={{ minHeight: 60, fontSize: 12.5 }} />
          </div>
          <div className="row gap2" style={{ justifyContent: 'flex-end' }}>
            <button className="btn sm btn-ghost" onClick={() => setEditing(false)}>Cancel</button>
            <button className="btn sm btn-primary" disabled={update.isPending || !title.trim()} onClick={save}><Glyph name="check" size={13} />Save</button>
          </div>
        </div>
      ) : (
        <div className="col" style={{ gap: 12 }}>
          <div className="h2" style={{ fontSize: 16 }}>{sig.title}</div>
          <code className="mono" style={{ fontSize: 11.5, color: 'var(--accent)', wordBreak: 'break-all' }}>{sig.signature_key}</code>
          {sig.category && <div className="row gap2" style={{ fontSize: 12 }}><span className="eyebrow">Category</span><span className="chip">{sig.category}</span></div>}
          {sig.where_it_lives && <div className="col" style={{ gap: 4 }}><span className="eyebrow">Where it usually lives</span><span style={{ fontSize: 12.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--text-2)' }}>{sig.where_it_lives}</span></div>}
          {sig.is_problem && <div className="col" style={{ gap: 4 }}><span className="eyebrow">Is this actually a problem?</span><span style={{ fontSize: 12.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--text-2)' }}>{sig.is_problem}</span></div>}
          {sig.description && <div className="col" style={{ gap: 4 }}><span className="eyebrow">Description / fix</span><span style={{ fontSize: 12.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--text-2)' }}>{sig.description}</span></div>}
          <div className="col" style={{ gap: 4 }}>
            <span className="eyebrow">Representative error</span>
            <pre className="mono" style={{ margin: 0, padding: '10px 12px', fontSize: 11, lineHeight: 1.55, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--text-2)', background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)' }}>{sig.representative_text}</pre>
          </div>
          {links.length > 0 && <div className="row gap1 wrap">{links.map((l, i) => <KbLinkRow key={i} link={l} />)}</div>}
          <div className="hr" />
          <div className="row gap2">
            {canEdit && <button className="btn sm btn-ghost" onClick={() => setEditing(true)}><Glyph name="settings" size={13} />Edit</button>}
            {canPromoteGlobal && <button className="btn sm btn-ghost" onClick={() => promoteGlobal.mutate(sig.id)} disabled={promoteGlobal.isPending}><Glyph name="layers" size={13} />Promote to global</button>}
            <div className="grow" />
            {canEdit && <button className="btn sm btn-danger" onClick={() => { if (confirm('Delete this KB entry?')) del.mutate(sig.id, { onSuccess: onClose }) }}><Glyph name="trash" size={13} />Delete</button>}
          </div>
        </div>
      )}
    </div>
  )
}

export function KbBrowse() {
  const me = useMe()
  const isAdmin = me.data?.role === 'admin'
  const myTeamIds = new Set((me.data?.teams ?? []).map((t) => t.id))

  const [scope, setScope] = useState<Scope>('all')
  const [status, setStatus] = useState<string>('')
  const [q, setQ] = useState('')
  const [openId, setOpenId] = useState<string | null>(null)

  const list = useKbSignatures(scope, status || undefined, q || undefined)
  const items = list.data ?? []
  const openSig = items.find((s) => s.id === openId) ?? null

  return (
    <div className="col scroll" style={{ height: '100%' }}>
      <div style={{ maxWidth: 'var(--maxw)', width: '100%', margin: '0 auto', padding: '28px clamp(20px,4vw,40px) 64px' }}>
        <div className="eyebrow" style={{ marginBottom: 6 }}>Knowledge base</div>
        <h1 className="h1">Knowledge base</h1>
        <p className="muted" style={{ fontSize: 13.5, marginTop: 4, marginBottom: 22 }}>Recurring errors and their documented fixes.</p>

        {openSig ? (
          <DetailView sig={openSig} isAdmin={isAdmin ?? false} myTeamIds={myTeamIds} onClose={() => setOpenId(null)} />
        ) : (
          <>
            <div className="row gap2 wrap" style={{ marginBottom: 16 }}>
              <div className="row" style={{ position: 'relative', width: 'min(320px,60vw)' }}>
                <span style={{ position: 'absolute', left: 10, color: 'var(--text-3)', display: 'grid', placeItems: 'center', height: '100%' }}><Glyph name="search" size={14} /></span>
                <input className="input" placeholder="Search title or error…" value={q} onChange={(e) => setQ(e.target.value)} style={{ paddingLeft: 32, height: 34 }} aria-label="Search knowledge base" />
              </div>
              <select className="select" style={{ height: 34 }} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
                <option value="">All statuses</option>
                {KB_STATUS_VALUES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <div className="row gap1">
                {(['all', 'team', 'global'] as Scope[]).map((sc) => (
                  <button key={sc} className={'btn sm' + (scope === sc ? ' btn-primary' : ' btn-ghost')} aria-pressed={scope === sc} onClick={() => setScope(sc)}>{sc}</button>
                ))}
              </div>
            </div>

            {list.isPending ? (
              <div className="card"><EmptyState icon="spinner" title="Loading…" /></div>
            ) : items.length === 0 ? (
              <div className="card"><EmptyState icon="sparkle" title="Nothing documented yet" sub="Promote a failing task from a run drawer to start the knowledge base." /></div>
            ) : (
              <div className="col" style={{ gap: 8 }}>
                {items.map((s) => {
                  const n = s.occurrence_count
                  return (
                    <button key={s.id} type="button" className="card" onClick={() => setOpenId(s.id)}
                      style={{ padding: '12px 14px', textAlign: 'left', cursor: 'pointer', width: '100%' }}>
                      <div className="row gap2">
                        <KbStatusBadge status={s.status} />
                        <span className="h3" style={{ fontSize: 13.5 }}>{s.title}</span>
                        {s.team_id === null && <span className="chip">Global</span>}
                        <div className="grow" />
                        <span className="chip mono" style={{ fontSize: 10.5 }}>seen in {n} {runWord(n)}</span>
                        <Glyph name="chevR" size={15} style={{ color: 'var(--text-3)' }} />
                      </div>
                      <div className="mono dim" style={{ fontSize: 11, marginTop: 4, wordBreak: 'break-all' }}>{s.signature_key}</div>
                    </button>
                  )
                })}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
