import { Link } from 'react-router'
import { Modal } from '../components/atoms/Modal'
import { Glyph } from '../components/atoms/Glyph'
import { errorMessage } from '../api/client'
import { useRunDiff, type DiffEntry, type RunDiffOut } from '../api/runs'
import { stCls } from '../components/atoms/status'
import { fmtDuration, shortTime } from '../components/atoms/format'

const rowStyle = { fontSize: 12, padding: '3px 2px', textAlign: 'left' as const }

function EntryRow({ entry, dot, onJump }: { entry: DiffEntry; dot: string; onJump?: (seq: number) => void }) {
  const label = (
    <>
      <span className={'dot-status ' + stCls(dot)} style={{ flex: 'none' }} />
      <span className="mono truncate" style={{ color: 'var(--text-2)' }}>
        {entry.play_name}<span style={{ opacity: 0.45 }}>{' › '}</span>
        <span style={{ color: 'var(--text)' }}>{entry.task_name}</span>
        <span style={{ opacity: 0.45 }}>{' @ '}</span>{entry.host}
      </span>
    </>
  )
  // before → after host status (e.g. "unreachable → failed"): surfaces the exact transition
  // and distinguishes failed vs unreachable within a section. '∅' = absent on that side.
  const transition = (
    <span className="mono dim" style={{ flex: 'none', fontSize: 11, whiteSpace: 'nowrap' }}>
      {entry.before ?? '∅'}<span style={{ opacity: 0.5 }}>{' → '}</span>{entry.after ?? '∅'}
    </span>
  )
  if (onJump && entry.seq != null) {
    const seq = entry.seq
    return (
      <button type="button" className="row gap2" onClick={() => onJump(seq)}
        style={{ ...rowStyle, background: 'none', border: 'none', cursor: 'pointer', width: '100%', minWidth: 0, font: 'inherit', color: 'inherit' }}>
        {label}
        <span className="grow" />
        {transition}
        <Glyph name="chevR" size={12} style={{ color: 'var(--text-3)', flexShrink: 0, marginLeft: 6 }} />
      </button>
    )
  }
  return <div className="row gap2" style={{ ...rowStyle, minWidth: 0 }}>{label}<span className="grow" />{transition}</div>
}

function Section({ title, entries, dot, onJump }: { title: string; entries: DiffEntry[]; dot: string; onJump?: (seq: number) => void }) {
  if (entries.length === 0) return null
  return (
    <div className="col" style={{ gap: 2 }}>
      <span className="eyebrow" style={{ marginBottom: 2 }}>{title}</span>
      {entries.map((e, i) => <EntryRow key={`${e.play_name}|${e.task_name}|${e.host}|${i}`} entry={e} dot={dot} onJump={onJump} />)}
    </div>
  )
}

function DurationChip({ delta }: { delta: number }) {
  const slower = delta > 0
  return (
    <span className={'badge ' + stCls(slower ? 'failed' : 'ok')} style={{ fontSize: 10.5 }}>
      {slower ? `+${fmtDuration(delta)} slower` : `−${fmtDuration(Math.abs(delta))} faster`}
    </span>
  )
}

function DiffBody({ d, onJump, onClose }: { d: RunDiffOut; onJump: (seq: number) => void; onClose: () => void }) {
  if (!d.baseline) {
    return (
      <p className="dim" style={{ fontSize: 13, margin: 0 }}>
        {d.reason === 'no_template'
          ? 'This run has no template name to match on.'
          : 'No earlier successful run of this template is visible to you.'}
      </p>
    )
  }
  const b = d.baseline
  const when = b.launched_at ?? b.log_time ?? b.created_at
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="row gap2" style={{ fontSize: 12.5, flexWrap: 'wrap' }}>
        <span className="dim">Baseline:</span>
        <Link to={'/runs/' + b.id} onClick={onClose} className="mono" style={{ color: 'var(--accent)', textDecoration: 'none' }}>
          {b.template_name || 'Run'}{b.job_id ? ` #${b.job_id}` : ''}
        </Link>
        <span className="mono dim" style={{ fontSize: 11.5 }}>{shortTime(when)}</span>
        {d.duration_delta_s != null && Math.abs(d.duration_delta_s) >= 1 && <DurationChip delta={d.duration_delta_s} />}
      </div>

      {d.newly_failing.length === 0 && d.still_failing.length === 0 && d.fixed.length === 0
        && d.hosts_newly_unreachable.length === 0 && d.slowest_changes.length === 0
        && d.added_count === 0 && d.removed_count === 0 && (
        <p className="dim" style={{ fontSize: 12.5, margin: 0 }}>No task-level changes vs the baseline.</p>
      )}

      <Section title="Newly failing" entries={d.newly_failing} dot="failed" onJump={onJump} />
      <Section title="Still failing" entries={d.still_failing} dot="changed" onJump={onJump} />
      <Section title="Fixed" entries={d.fixed} dot="ok" />

      {d.hosts_newly_unreachable.length > 0 && (
        <div className="col" style={{ gap: 6 }}>
          <span className="eyebrow">Hosts newly unreachable</span>
          <div className="row gap1" style={{ flexWrap: 'wrap' }}>
            {d.hosts_newly_unreachable.map((h) => <span key={h} className="chip mono" style={{ color: 'var(--unreachable)' }}>{h}</span>)}
          </div>
        </div>
      )}

      {d.slowest_changes.length > 0 && (
        <div className="col" style={{ gap: 2 }}>
          <span className="eyebrow" style={{ marginBottom: 2 }}>Biggest duration changes</span>
          {d.slowest_changes.map((c) => (
            <div key={c.seq} className="row gap2 mono" style={{ ...rowStyle, minWidth: 0 }}>
              <span className="truncate" style={{ color: 'var(--text)' }}>{c.task_name}</span>
              <span className="grow" />
              <span className="dim tnum" style={{ flex: 'none' }}>
                {fmtDuration(c.before_s)} → {fmtDuration(c.after_s)} ({c.delta_s > 0 ? '+' : '−'}{fmtDuration(Math.abs(c.delta_s))})
              </span>
            </div>
          ))}
        </div>
      )}

      {(d.added_count > 0 || d.removed_count > 0) && (
        <span className="dim" style={{ fontSize: 11.5 }}>
          {d.added_count} task-host {d.added_count === 1 ? 'row' : 'rows'} added · {d.removed_count} removed
        </span>
      )}
    </div>
  )
}

export function RunDiffModal({ runId, open, onOpenChange, onJump }: {
  runId: string; open: boolean; onOpenChange: (o: boolean) => void; onJump: (seq: number) => void
}) {
  const diff = useRunDiff(runId, open)
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="vs last green run" width={560}>
      {diff.isPending && (
        <div className="row" style={{ justifyContent: 'center', padding: 24, color: 'var(--text-3)' }}>
          <span className="spin"><Glyph name="spinner" size={20} /></span>
        </div>
      )}
      {diff.isError && <p className="dim" role="alert" style={{ fontSize: 13, margin: 0 }}>{errorMessage(diff.error, 'Could not compute the diff.')}</p>}
      {diff.data && <DiffBody d={diff.data} onJump={onJump} onClose={() => onOpenChange(false)} />}
      <div className="row" style={{ justifyContent: 'flex-end', marginTop: 16 }}>
        <button className="btn" onClick={() => onOpenChange(false)}>Close</button>
      </div>
    </Modal>
  )
}
