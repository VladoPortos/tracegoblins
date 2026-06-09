import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { PageShell } from '../components/atoms/PageShell'
import { EmptyState } from '../components/atoms/EmptyState'
import { stCls } from '../components/atoms/status'
import { fmtDuration } from '../components/atoms/format'
import { errorMessage } from '../api/client'
import { useTemplateStats, type TemplateStat } from '../api/analytics'

const LS_KEY = 'tg:analytics.days'
const WINDOWS = [7, 30, 90] as const

function loadDays(): number {
  try {
    const v = parseInt(localStorage.getItem(LS_KEY) ?? '', 10)
    return (WINDOWS as readonly number[]).includes(v) ? v : 30
  } catch { return 30 }
}

// Template gets the flexible space; the metric columns stay fixed-ish.
const GRID = 'minmax(0,1fr) minmax(150px,auto) 76px 56px 96px 70px 96px 86px'

const cellRight: React.CSSProperties = { textAlign: 'right', justifySelf: 'end' }

function Sparkline({ s }: { s: TemplateStat }) {
  return (
    <span className="row" style={{ gap: 5, flexWrap: 'nowrap' }}>
      {s.recent.map((status, i) => (
        <Link key={s.recent_ids[i] ?? i} to={'/runs/' + s.recent_ids[i]} title={status} style={{ display: 'inline-flex' }}>
          <span className={'dot-status ' + stCls(status)} />
        </Link>
      ))}
    </span>
  )
}

function StatRow({ s }: { s: TemplateStat }) {
  const pct = Math.round(s.success_rate * 100)
  const flaky = s.flaky_score >= 0.3 && s.runs >= 5
  return (
    <div
      style={{
        display: 'grid', gridTemplateColumns: GRID, gap: 12, alignItems: 'center',
        padding: '10px 16px', borderTop: '1px solid var(--border)', fontSize: 13,
      }}
    >
      <Link
        to={'/runs/' + s.last_run_id}
        className="truncate"
        title={s.template_name}
        style={{ color: 'inherit', textDecoration: 'none', fontWeight: 500, minWidth: 0 }}
      >
        {s.template_name}
      </Link>
      <Sparkline s={s} />
      <span className="mono tnum" style={{ ...cellRight, color: s.success_rate < 0.5 ? 'var(--unreachable)' : undefined }}>
        {pct}%
      </span>
      <span className="mono tnum dim" style={cellRight}>{s.runs}</span>
      <span>
        {s.current_streak > 1
          ? <span className={'badge ' + stCls(s.streak_kind === 'fail' ? 'failed' : 'ok')}><span className="dot" />{s.current_streak}× {s.streak_kind}</span>
          : <span className="dim">—</span>}
      </span>
      <span>
        {flaky
          ? <span className="badge st-changed" title={`score ${s.flaky_score.toFixed(2)}`}><span className="dot" />flaky</span>
          : <span className="dim">—</span>}
      </span>
      <span className="mono tnum dim" style={cellRight}>{fmtDuration(s.avg_duration_s)}</span>
      <span className="mono tnum dim" style={cellRight} title="Mean time from first failure to next pass">
        {fmtDuration(s.time_to_recovery_s)}
      </span>
    </div>
  )
}

export function AnalyticsView() {
  const [days, setDays] = useState<number>(loadDays)
  useEffect(() => {
    try { localStorage.setItem(LS_KEY, String(days)) } catch { /* ignore */ }
  }, [days])

  const stats = useTemplateStats(days)
  const items = stats.data?.items ?? []
  const sparkMax = items.reduce((n, s) => Math.max(n, s.recent.length), 0)

  return (
    <PageShell>
      <div className="row gap2" style={{ alignItems: 'flex-start', marginBottom: 22 }}>
        <div className="col" style={{ gap: 4 }}>
          <div className="eyebrow">Analytics</div>
          <h1 className="h1">Analytics</h1>
          <p className="muted" style={{ fontSize: 13.5, margin: 0 }}>Per-template failure trends</p>
        </div>
        <div className="grow" />
        <div className="seg" role="group" aria-label="Time window">
          {WINDOWS.map((d) => (
            <button key={d} aria-pressed={days === d} onClick={() => setDays(d)}>{d} days</button>
          ))}
        </div>
      </div>

      {stats.isPending ? (
        <div className="card"><EmptyState icon="spinner" title="Loading…" /></div>
      ) : stats.isError ? (
        <div className="card"><p className="dim" role="alert" style={{ fontSize: 13, margin: 0 }}>{errorMessage(stats.error, 'Could not load analytics.')}</p></div>
      ) : items.length === 0 ? (
        <div className="card"><p className="dim" style={{ fontSize: 13, margin: 0 }}>No runs in this window.</p></div>
      ) : (
        <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
          <div style={{ minWidth: 860 }}>
            <div
              style={{
                display: 'grid', gridTemplateColumns: GRID, gap: 12, alignItems: 'center',
                padding: '9px 16px', fontSize: 12, fontWeight: 600, color: 'var(--text-3)', whiteSpace: 'nowrap',
              }}
            >
              <span>Template</span>
              <span>{sparkMax > 0 ? `Last ${sparkMax}` : 'Recent'}</span>
              <span style={cellRight}>Success %</span>
              <span style={cellRight}>Runs</span>
              <span>Streak</span>
              <span>Flaky</span>
              <span style={cellRight}>Avg duration</span>
              <span style={cellRight}>Recovery</span>
            </div>
            {items.map((s) => <StatRow key={s.template_name} s={s} />)}
          </div>
        </div>
      )}
    </PageShell>
  )
}
