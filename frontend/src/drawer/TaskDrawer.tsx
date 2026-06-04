import { useState } from 'react'
import type { TaskLean, TeamBrief } from '../api/client'
import { useTask } from '../api/runs'
import { Glyph } from '../components/atoms/Glyph'
import { Badge } from '../components/atoms/Badge'
import { StatusDot } from '../components/atoms/StatusDot'
import { isErr } from '../components/atoms/status'
import { AnnotationsBlock } from './AnnotationsBlock'
import { DiscussionBlock } from './DiscussionBlock'
import { KbSuggestion } from './KbSuggestion'
import { PromoteKbModal } from '../modals/PromoteKbModal'
import { OutputViewer } from './OutputViewer'

const roleLabel = (r: string | null) => (r ? r.replace(/^dxc\.xaas\./, '') : 'play tasks')
function prettyJson(raw: string) { try { return JSON.stringify(JSON.parse(raw), null, 2) } catch { return raw } }

function JsonBlock({ raw }: { raw: string }) {
  const [open, setOpen] = useState(false)
  const [modal, setModal] = useState(false)
  const txt = prettyJson(raw); const lines = txt.split('\n'); const big = lines.length > 10
  const shown = open || !big ? txt : lines.slice(0, 8).join('\n')
  const copy = async () => { try { await navigator.clipboard.writeText(txt) } catch { /* blocked */ } }
  return (
    <div className="col" style={{ gap: 6 }}>
      <div className="row gap2" style={{ alignItems: 'center' }}>
        <span className="eyebrow">Task output</span>
        <span className="dim mono" style={{ fontSize: 10.5 }}>{lines.length + ' lines'}</span>
        <div className="grow" />
        <button className="btn icon sm btn-ghost" onClick={copy} aria-label="Copy output" title="Copy"><Glyph name="copy" size={14} /></button>
        <button className="btn icon sm btn-ghost" onClick={() => setModal(true)} aria-label="Expand output" title="Expand"><Glyph name="expand" size={14} /></button>
      </div>
      <div style={{ position: 'relative', background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', overflow: 'hidden' }}>
        <pre className="mono" style={{ margin: 0, padding: '10px 12px', fontSize: 11.5, lineHeight: 1.55, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--text-2)', maxHeight: open ? 420 : 'none', overflow: 'auto' }}>{shown}</pre>
        {big && !open && <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: 48, background: 'linear-gradient(transparent, var(--surface-2))' }} />}
      </div>
      {big && <button className="btn sm btn-ghost" onClick={() => setOpen((o) => !o)} style={{ alignSelf: 'flex-start' }}><Glyph name={open ? 'chevD' : 'chevR'} size={13} />{open ? 'Collapse output' : `Expand full output (${lines.length} lines)`}</button>}
      <OutputViewer open={modal} onOpenChange={setModal} title="Task output" value={txt} />
    </div>
  )
}
function ErrorBlock({ raw }: { raw: string }) {
  let msg = raw; try { const o = JSON.parse(raw); msg = o.msg || raw } catch { /* keep raw */ }
  msg = msg.replace(/\\r/g, '').replace(/\\n/g, '\n')
  return (
    <div className="col" style={{ gap: 6 }}>
      <div className="row gap2"><Glyph name="alert" size={14} style={{ color: 'var(--unreachable)' }} /><span className="eyebrow" style={{ color: 'var(--unreachable)' }}>Failure detail</span></div>
      <pre className="mono st-unreachable" style={{ margin: 0, padding: '11px 13px', fontSize: 11.5, lineHeight: 1.55, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--c)', background: 'var(--cb)', border: '1px solid var(--cl)', borderRadius: 'var(--r-md)' }}>{msg}</pre>
    </div>
  )
}

export function TaskDrawer({ runId, lean, width, onClose, runOwnerId = '', currentUserId = '', teams = [], isAdmin = false }: { runId: string; lean: TaskLean; width: string; onClose: () => void; runOwnerId?: string; currentUserId?: string; teams?: TeamBrief[]; isAdmin?: boolean }) {
  const full = useTask(runId, lean.seq)
  const t = full.data ?? lean
  const [promoteOpen, setPromoteOpen] = useState(false)
  return (
    <div style={{ width, flex: 'none', borderLeft: '1px solid var(--border)', background: 'var(--surface)', display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border)' }}>
        <div className="row gap2" style={{ marginBottom: 10 }}>
          <span className="mono dim tnum" style={{ fontSize: 11 }}>{'#' + t.seq}</span>
          <div className="grow" /><Badge status={t.status} />
          <button className="btn icon sm btn-ghost" onClick={onClose} aria-label="Close"><Glyph name="close" size={16} /></button>
        </div>
        <div className="h2" style={{ fontSize: 15, lineHeight: 1.35, marginBottom: 8 }}>{t.name}</div>
        <div className="row gap1 wrap" style={{ fontSize: 11 }}>
          <span className="chip"><Glyph name="layers" size={11} />{t.play_name || 'play'}</span>
          {t.role && <span className="chip mono" style={{ color: 'var(--accent)' }}>{roleLabel(t.role)}</span>}
          {t.items_count > 0 && <span className="chip">{t.items_count + ' loop items'}</span>}
          {t.line_no != null && <span className="chip mono">{'line ' + t.line_no}</span>}
        </div>
      </div>
      <div className="scroll grow" style={{ padding: 16 }}>
        <div className="col" style={{ gap: 18 }}>
          {Object.keys(t.hosts).length > 0 && (
            <div className="col" style={{ gap: 7 }}>
              <span className="eyebrow">Hosts</span>
              {Object.entries(t.hosts).map(([h, s]) => (
                <div key={h} className="row gap2"><StatusDot status={s} size={8} /><span className="mono truncate grow" style={{ fontSize: 12.5 }}>{h}</span><Badge status={s} /></div>
              ))}
            </div>
          )}
          {full.data?.error && <ErrorBlock raw={full.data.error} />}
          {full.data?.output && <JsonBlock raw={full.data.output} />}
          {full.data?.included_path && <div className="col" style={{ gap: 5 }}><span className="eyebrow">Includes file</span><code className="mono" style={{ fontSize: 11.5, color: 'var(--accent)', wordBreak: 'break-all' }}>{full.data.included_path}</code></div>}
          <div className="hr" />
          <AnnotationsBlock runId={runId} seq={lean.seq} currentUserId={currentUserId} runOwnerId={runOwnerId} />
          <div className="hr" />
          <DiscussionBlock runId={runId} seq={lean.seq} currentUserId={currentUserId} runOwnerId={runOwnerId} />
          {isErr(lean.status) && <KbSuggestion runId={runId} seq={lean.seq} onPromote={() => setPromoteOpen(true)} />}
        </div>
      </div>
      {isErr(lean.status) && (
        <PromoteKbModal open={promoteOpen} onOpenChange={setPromoteOpen} runId={runId} seq={lean.seq} teams={teams} isAdmin={isAdmin} />
      )}
    </div>
  )
}
