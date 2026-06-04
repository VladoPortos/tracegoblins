import { useState } from 'react'
import { Glyph } from '../components/atoms/Glyph'
import { Field } from '../components/atoms/Field'
import {
  TAG_VALUES, useRunAnnotations, useCreateAnnotation, useUpdateAnnotation, useDeleteAnnotation,
  type Annotation, type AnnotationLink,
} from '../api/annotations'

const tagCls: Record<string, string> = {
  'needs-fix': 'tag tag-needs-fix', 'known-issue': 'tag tag-known-issue',
  resolved: 'tag tag-resolved', note: 'tag tag-note',
}

// Belt-and-suspenders over the server allowlist: re-check the scheme client-side
// and render plain text (no anchor) if it isn't http/https/mailto.
function isSafeUrl(url: string): boolean {
  try {
    const scheme = new URL(url, window.location.origin).protocol.replace(':', '').toLowerCase()
    return scheme === 'http' || scheme === 'https' || scheme === 'mailto'
  } catch {
    return false
  }
}

function LinkRow({ link }: { link: AnnotationLink }) {
  const label = link.label || link.url
  if (!isSafeUrl(link.url)) {
    return <span className="chip" style={{ color: 'var(--text-3)' }}><Glyph name="link" size={11} />{label}</span>
  }
  return (
    <a className="chip" href={link.url} target="_blank" rel="noopener noreferrer nofollow" style={{ color: 'var(--accent)', textDecoration: 'none' }}>
      <Glyph name="link" size={11} />{label}
    </a>
  )
}

function AnnotationForm({
  runId, seq, existing, onDone,
}: { runId: string; seq: number; existing?: Annotation; onDone: () => void }) {
  const create = useCreateAnnotation(runId, seq)
  const update = useUpdateAnnotation(runId)
  const [note, setNote] = useState(existing?.note ?? '')
  const [tags, setTags] = useState<string[]>(existing?.tags ?? [])
  const [resolved, setResolved] = useState(existing?.resolved ?? false)
  const [links, setLinks] = useState<AnnotationLink[]>(existing?.links ?? [])
  const [label, setLabel] = useState('')
  const [url, setUrl] = useState('')
  const busy = create.isPending || update.isPending

  const toggleTag = (t: string) => setTags((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]))
  const addLink = () => { if (!url.trim()) return; setLinks((l) => [...l, { label: label.trim(), url: url.trim() }]); setLabel(''); setUrl('') }
  const removeLink = (i: number) => setLinks((l) => l.filter((_, idx) => idx !== i))

  const save = () => {
    if (existing) update.mutate({ aid: existing.id, patch: { note, tags, links, resolved } }, { onSuccess: onDone })
    else create.mutate({ note, tags, links }, { onSuccess: onDone })
  }

  return (
    <div className="col" style={{ gap: 10, padding: 12, border: '1px solid var(--border)', borderRadius: 'var(--r-md)', background: 'var(--surface-2)' }}>
      <textarea className="textarea" aria-label="Annotation note" placeholder="Describe what's wrong or what was done…"
        value={note} onChange={(e) => setNote(e.target.value)} style={{ minHeight: 60, fontSize: 12.5 }} />
      <div className="row gap1 wrap">
        {TAG_VALUES.map((t) => (
          <button key={t} type="button" aria-pressed={tags.includes(t)} className={tagCls[t]}
            onClick={() => toggleTag(t)} style={{ cursor: 'pointer', opacity: tags.includes(t) ? 1 : 0.45 }}>{t}</button>
        ))}
      </div>
      {links.length > 0 && (
        <div className="row gap1 wrap">
          {links.map((l, i) => (
            <span key={i} className="chip" style={{ gap: 6 }}>
              <Glyph name="link" size={11} />{l.label || l.url}
              <button type="button" className="btn icon" aria-label={`Remove link ${l.label || l.url}`} onClick={() => removeLink(i)} style={{ padding: 0, height: 14, width: 14 }}><Glyph name="close" size={11} /></button>
            </span>
          ))}
        </div>
      )}
      <div className="row gap2" style={{ alignItems: 'flex-end' }}>
        <div style={{ flex: '1 1 40%' }}><Field label="Link label" placeholder="docs" value={label} onChange={(e) => setLabel(e.target.value)} /></div>
        <div style={{ flex: '1 1 60%' }}><Field label="Link URL" placeholder="https://… or mailto:…" value={url} onChange={(e) => setUrl(e.target.value)} /></div>
        <button type="button" className="btn sm btn-ghost" onClick={addLink}><Glyph name="plus" size={13} />Add</button>
      </div>
      <label className="row gap2" style={{ fontSize: 12.5, cursor: 'pointer' }}>
        <input type="checkbox" checked={resolved} onChange={(e) => setResolved(e.target.checked)} />Mark resolved
      </label>
      <div className="row gap2" style={{ justifyContent: 'flex-end' }}>
        <button type="button" className="btn sm btn-ghost" onClick={onDone}>Cancel</button>
        <button type="button" className="btn sm btn-primary" disabled={busy} onClick={save}>
          <Glyph name="check" size={13} />Save annotation
        </button>
      </div>
    </div>
  )
}

export function AnnotationsBlock({
  runId, seq, currentUserId, runOwnerId,
}: { runId: string; seq: number; currentUserId: string; runOwnerId: string }) {
  const all = useRunAnnotations(runId)
  const del = useDeleteAnnotation(runId)
  const [adding, setAdding] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const items = (all.data ?? []).filter((a) => a.task_seq === seq)

  return (
    <div className="col" style={{ gap: 10 }}>
      <div className="row gap2">
        <span className="eyebrow">Annotations</span>
        <span className="chip mono" style={{ fontSize: 10.5 }}>{items.length}</span>
        <div className="grow" />
        {!adding && <button className="btn sm btn-ghost" onClick={() => { setAdding(true); setEditId(null) }}><Glyph name="plus" size={13} />Add annotation</button>}
      </div>
      {adding && <AnnotationForm runId={runId} seq={seq} onDone={() => setAdding(false)} />}
      {items.map((a) => (
        editId === a.id
          ? <AnnotationForm key={a.id} runId={runId} seq={seq} existing={a} onDone={() => setEditId(null)} />
          : (
            <div key={a.id} className="col" style={{ gap: 7, padding: 12, border: '1px solid var(--border)', borderRadius: 'var(--r-md)' }}>
              <div className="row gap2">
                <span style={{ fontSize: 12.5, fontWeight: 600 }}>{a.author_name}</span>
                {a.resolved && <span className="tag tag-resolved"><Glyph name="check" size={11} />resolved</span>}
                <div className="grow" />
                {a.author_user_id === currentUserId && <button className="btn icon sm btn-ghost" aria-label="Edit annotation" onClick={() => { setEditId(a.id); setAdding(false) }}><Glyph name="settings" size={13} /></button>}
                {(a.author_user_id === currentUserId || runOwnerId === currentUserId) && (
                  <button className="btn icon sm btn-ghost" aria-label="Delete annotation"
                    onClick={() => { if (confirm('Delete this annotation?')) del.mutate(a.id) }}><Glyph name="trash" size={13} /></button>
                )}
              </div>
              {a.note && <div style={{ fontSize: 12.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--text-2)' }}>{a.note}</div>}
              {a.tags.length > 0 && <div className="row gap1 wrap">{a.tags.map((t) => <span key={t} className={tagCls[t] ?? 'tag tag-note'}>{t}</span>)}</div>}
              {a.links.length > 0 && <div className="row gap1 wrap">{a.links.map((l, i) => <LinkRow key={i} link={l} />)}</div>}
            </div>
          )
      ))}
      {items.length === 0 && !adding && <span className="dim" style={{ fontSize: 12 }}>No annotations on this task yet.</span>}
    </div>
  )
}
