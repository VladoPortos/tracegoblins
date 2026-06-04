import { useEffect, useState } from 'react'
import { Modal } from '../components/atoms/Modal'
import { Glyph } from '../components/atoms/Glyph'
import { Field } from '../components/atoms/Field'
import { ApiError, type TeamBrief } from '../api/client'
import {
  useKbSuggest, usePromoteKb, KB_STATUS_VALUES,
  type KbLink, type KbStatus, type KbPromote,
} from '../api/kb'

const GLOBAL = '__global__'

export function PromoteKbModal({
  open, onOpenChange, runId, seq, teams, isAdmin,
}: { open: boolean; onOpenChange: (o: boolean) => void; runId: string; seq: number; teams: TeamBrief[]; isAdmin: boolean }) {
  const suggest = useKbSuggest(runId, seq, open)
  const promote = usePromoteKb()

  const [title, setTitle] = useState('')
  const [status, setStatus] = useState<KbStatus>('needs-fix')
  const [teamSel, setTeamSel] = useState<string>(teams[0]?.id ?? (isAdmin ? GLOBAL : ''))
  const [description, setDescription] = useState('')
  const [isProblem, setIsProblem] = useState('')
  const [whereItLives, setWhereItLives] = useState('')
  const [links, setLinks] = useState<KbLink[]>([])
  const [error, setError] = useState<string | null>(null)

  // Reset transient fields + default the team selector each time the modal opens.
  useEffect(() => {
    if (!open) return
    setTitle(''); setStatus('needs-fix'); setDescription(''); setIsProblem('')
    setWhereItLives(''); setLinks([]); setError(null)
    setTeamSel(teams[0]?.id ?? (isAdmin ? GLOBAL : ''))
  }, [open, teams, isAdmin])

  // "Add link" appends a new editable row; each row's label/url bind directly into
  // the links array so the values are committed as the user types (no separate save).
  const addLink = () => setLinks((l) => [...l, { label: '', url: '' }])
  const setLinkField = (i: number, field: 'label' | 'url', value: string) =>
    setLinks((l) => l.map((lk, idx) => (idx === i ? { ...lk, [field]: value } : lk)))
  const removeLink = (i: number) => setLinks((l) => l.filter((_, idx) => idx !== i))

  const submit = () => {
    setError(null)
    const team_id = teamSel === GLOBAL ? null : teamSel
    const cleanLinks = links
      .map((l) => ({ label: l.label.trim(), url: l.url.trim() }))
      .filter((l) => l.url)
    const body: KbPromote = {
      run_id: runId, task_seq: seq, team_id, title: title.trim(), status,
      description: description.trim() || null, is_problem: isProblem.trim() || null,
      where_it_lives: whereItLives.trim() || null, links: cleanLinks,
    }
    promote.mutate(body, {
      onSuccess: () => onOpenChange(false),
      onError: (e) => setError(
        e instanceof ApiError && e.status === 409
          ? 'A knowledge-base entry already exists for this signature in that scope.'
          : e instanceof ApiError && typeof e.detail === 'string'
            ? e.detail
            : 'Could not promote this error.',
      ),
    })
  }

  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Promote to KB" width={560}>
      {error && <div className="tag tag-needs-fix" role="alert" style={{ marginBottom: 12 }}>{error}</div>}
      <div className="col" style={{ gap: 12 }}>
        <div>
          <label className="field-label">Signature</label>
          <code className="mono" style={{ display: 'block', fontSize: 11.5, color: 'var(--accent)', wordBreak: 'break-all' }}>
            {suggest.data?.signature_key ?? (suggest.isPending ? 'extracting…' : 'unknown')}
          </code>
          {suggest.data?.representative_text && (
            <div className="dim mono" style={{ fontSize: 11, marginTop: 4, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{suggest.data.representative_text}</div>
          )}
        </div>

        <Field label="Title" placeholder="Short, searchable name for this issue" value={title} onChange={(e) => setTitle(e.target.value)} />

        <div className="row gap2">
          <div style={{ flex: '1 1 50%' }}>
            <label className="field-label" htmlFor="kb-promote-status">Status</label>
            <select id="kb-promote-status" className="input" value={status} onChange={(e) => setStatus(e.target.value as KbStatus)}>
              {KB_STATUS_VALUES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div style={{ flex: '1 1 50%' }}>
            <label className="field-label" htmlFor="kb-promote-team">Scope</label>
            <select id="kb-promote-team" className="input" value={teamSel} onChange={(e) => setTeamSel(e.target.value)} aria-label="Scope">
              {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              {isAdmin && <option value={GLOBAL}>Global (all teams)</option>}
            </select>
          </div>
        </div>

        <div>
          <label className="field-label" htmlFor="kb-promote-where">Where it usually lives</label>
          <textarea id="kb-promote-where" className="textarea" placeholder="Which role/play/host this usually hits…"
            value={whereItLives} onChange={(e) => setWhereItLives(e.target.value)} style={{ minHeight: 48, fontSize: 12.5 }} />
        </div>
        <div>
          <label className="field-label" htmlFor="kb-promote-problem">Is this actually a problem?</label>
          <textarea id="kb-promote-problem" className="textarea" placeholder="When this matters vs. when it's benign…"
            value={isProblem} onChange={(e) => setIsProblem(e.target.value)} style={{ minHeight: 48, fontSize: 12.5 }} />
        </div>
        <div>
          <label className="field-label" htmlFor="kb-promote-desc">Description / fix</label>
          <textarea id="kb-promote-desc" className="textarea" placeholder="What to do about it…"
            value={description} onChange={(e) => setDescription(e.target.value)} style={{ minHeight: 60, fontSize: 12.5 }} />
        </div>

        <div className="col" style={{ gap: 8 }}>
          <label className="field-label">Fix links</label>
          {links.map((l, i) => (
            <div key={i} className="row gap2" style={{ alignItems: 'flex-end' }}>
              <div style={{ flex: '1 1 40%' }}><Field label="Link label" placeholder="runbook" value={l.label} onChange={(e) => setLinkField(i, 'label', e.target.value)} /></div>
              <div style={{ flex: '1 1 60%' }}><Field label="Link URL" placeholder="https://… or mailto:…" value={l.url} onChange={(e) => setLinkField(i, 'url', e.target.value)} /></div>
              <button type="button" className="btn icon sm btn-ghost" aria-label={`Remove link ${i + 1}`} onClick={() => removeLink(i)}><Glyph name="close" size={13} /></button>
            </div>
          ))}
          <button type="button" className="btn sm btn-ghost" aria-label="Add link" onClick={addLink} style={{ alignSelf: 'flex-start' }}><Glyph name="plus" size={13} />Add link</button>
        </div>
      </div>

      <div className="row" style={{ justifyContent: 'flex-end', gap: 8, marginTop: 18 }}>
        <button className="btn btn-ghost" onClick={() => onOpenChange(false)}>Cancel</button>
        <button className="btn btn-primary" disabled={promote.isPending || !title.trim()} onClick={submit}>
          <Glyph name="sparkle" size={14} />Promote to KB
        </button>
      </div>
    </Modal>
  )
}
