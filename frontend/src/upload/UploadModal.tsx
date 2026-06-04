import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Modal } from '../components/atoms/Modal'
import { Field } from '../components/atoms/Field'
import { Glyph } from '../components/atoms/Glyph'
import { ApiError, type TeamBrief } from '../api/client'
import { useUploadRun } from '../api/runs'

export function UploadModal({ open, onOpenChange, teams = [] }: { open: boolean; onOpenChange: (o: boolean) => void; teams?: TeamBrief[] }) {
  const nav = useNavigate()
  const upload = useUploadRun()
  const [mode, setMode] = useState<'paste' | 'file'>('paste')
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [template, setTemplate] = useState('')
  const [target, setTarget] = useState('') // '' = Personal; otherwise a team id
  const [error, setError] = useState<string | null>(null)

  const submit = () => {
    setError(null)
    const teamId = target || undefined
    const payload = mode === 'file'
      ? { file: file!, template: template || undefined, team_id: teamId }
      : { text, template: template || undefined, team_id: teamId }
    upload.mutate(payload, {
      onSuccess: (r) => { onOpenChange(false); nav('/runs/' + r.id) },
      onError: (e) => setError(e instanceof ApiError && typeof e.detail === 'string' ? e.detail : 'Upload failed.'),
    })
  }
  const canSubmit = mode === 'file' ? !!file : text.trim().length > 0

  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Upload a run log" width={560}>
      <div className="seg" style={{ marginBottom: 14 }}>
        <button aria-pressed={mode === 'paste'} onClick={() => setMode('paste')}><Glyph name="copy" size={14} />Paste</button>
        <button aria-pressed={mode === 'file'} onClick={() => setMode('file')}><Glyph name="upload" size={14} />Upload file</button>
      </div>
      {error && <div className="tag tag-needs-fix" role="alert" style={{ marginBottom: 12 }}>{error}</div>}
      {mode === 'paste'
        ? <textarea className="textarea mono" placeholder="Paste the AWX/Ansible stdout log…" value={text} onChange={(e) => setText(e.target.value)} style={{ minHeight: 220, fontSize: 12 }} />
        : <input type="file" accept=".txt,.log,text/plain" aria-label="Log file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="input" />}
      <div style={{ marginTop: 12 }}><Field label="Template name (optional)" placeholder="e.g. Day2Actions" value={template} onChange={(e) => setTemplate(e.target.value)} /></div>
      <div style={{ marginTop: 12 }}>
        <label className="field-label" htmlFor="upload-save-to">Save to</label>
        <select id="upload-save-to" className="select" aria-label="Save to" value={target} onChange={(e) => setTarget(e.target.value)} style={{ width: '100%' }}>
          <option value="">Personal (only you)</option>
          {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>
      <div className="row gap2" style={{ justifyContent: 'flex-end', marginTop: 16 }}>
        <button className="btn btn-ghost" onClick={() => onOpenChange(false)}>Cancel</button>
        <button className="btn btn-primary" disabled={!canSubmit || upload.isPending} onClick={submit}><Glyph name="upload" size={15} />{upload.isPending ? 'Parsing…' : 'Upload & analyze'}</button>
      </div>
    </Modal>
  )
}
