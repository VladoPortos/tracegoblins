import { useNavigate } from 'react-router'
import type { RunCard } from '../api/client'
import { Glyph } from '../components/atoms/Glyph'
import { Badge } from '../components/atoms/Badge'
import { HostBar } from '../components/atoms/HostBar'
import { stCls } from '../components/atoms/status'
import { fmtDuration, shortTime } from '../components/atoms/format'

export function JobCard({ run }: { run: RunCard }) {
  const nav = useNavigate()
  const isAwx = !!run.controller_id

  // Duration from elapsed field if present on the card; otherwise not shown.
  // The plan notes job_events give real durations — surfaced here when available.
  const elapsed = run.elapsed ?? null
  // "When" prefers the AWX launch time, then finish/log time — matching the table view
  // and the server's default sort (coalesce(launched_at, log_time, created_at)).
  const when = run.launched_at || run.log_time

  return (
    <button className="card" onClick={() => nav('/runs/' + run.id)}
      style={{ textAlign: 'left', cursor: 'pointer', padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
      onMouseEnter={(e) => { e.currentTarget.style.boxShadow = 'var(--shadow-2)'; e.currentTarget.style.borderColor = 'var(--border-strong)' }}
      onMouseLeave={(e) => { e.currentTarget.style.boxShadow = 'var(--shadow-1)'; e.currentTarget.style.borderColor = 'var(--border)' }}>
      <div className={stCls(run.status)} style={{ height: 3, background: 'var(--c)' }} />
      <div style={{ padding: '15px 16px 14px' }}>
        <div className="row gap2" style={{ marginBottom: 10 }}>
          <div className="grow col" style={{ gap: 3 }}>
            <div className="row gap2">
              <span className="h2" style={{ fontSize: 15 }}>{run.template_name || 'Run'}</span>
              {run.job_id && <span className="mono dim" style={{ fontSize: 12 }}>{'#' + run.job_id}</span>}
              {run.team_name && <span className="chip" style={{ fontSize: 10.5 }}><Glyph name="users" size={11} />{run.team_name}</span>}
              {!isAwx && (
                <span className="chip" style={{ fontSize: 10.5 }}><Glyph name="upload" size={10} />Uploaded</span>
              )}
              {isAwx && run.awx_organization_name && (
                <span className="chip" style={{ fontSize: 10.5 }}>{run.awx_organization_name}</span>
              )}
            </div>
            <div className="row gap2 mono" style={{ fontSize: 11.5, color: 'var(--text-3)' }}>
              <Glyph name="clock" size={12} />
              {when ? shortTime(when) : 'uploaded ' + shortTime(run.created_at)}
              {elapsed != null && (
                <>
                  <span style={{ opacity: 0.4 }}>·</span>
                  <span title="Duration">{fmtDuration(elapsed)}</span>
                </>
              )}
              <span style={{ opacity: 0.4 }}>·</span>
              <Glyph name="host" size={12} />
              {run.host_count + ' host' + (run.host_count !== 1 ? 's' : '')}
            </div>
            {/* AWX-only metadata row */}
            {isAwx && (run.awx_launch_type || run.controller_name) && (
              <div className="row gap1 wrap" style={{ marginTop: 1 }}>
                {run.awx_launch_type && (
                  <span className="chip mono" style={{ fontSize: 10 }}>{run.awx_launch_type}</span>
                )}
                {run.controller_name && (
                  <span className="chip" style={{ fontSize: 10 }}>
                    <Glyph name="server" size={10} />
                    {run.controller_name}
                  </span>
                )}
              </div>
            )}
          </div>
          <Badge status={run.status} />
        </div>
        <div className="col" style={{ gap: 7, marginBottom: 12 }}>
          {run.recap.map((r) => (
            <div key={r.host} className="row gap2">
              <div className="mono truncate" style={{ fontSize: 11.5, width: '40%', color: (r.unreachable || r.failed) ? 'var(--unreachable)' : 'var(--text-2)' }}>{r.host}</div>
              <div className="grow"><HostBar recap={r as unknown as Record<string, number>} height={7} /></div>
              <div className="mono tnum dim" style={{ fontSize: 11, width: 34, textAlign: 'right' }}>{r.ok + r.changed + r.skipped + r.unreachable}</div>
            </div>
          ))}
        </div>
        <div className="row gap1 wrap">
          {(['changed', 'unreachable'] as const).map((k) => run.counts[k] > 0 ? <Badge key={k} status={k} count={run.counts[k]} /> : null)}
          {run.counts.skipped > 0 && <span className="chip">{run.counts.skipped + ' skipped'}</span>}
          {run.task_count > 0 && <span className="chip mono" style={{ fontSize: 11 }}>{run.task_count + ' tasks'}</span>}
        </div>
      </div>
    </button>
  )
}
