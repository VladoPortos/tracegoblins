import { useNavigate } from 'react-router'
import type { RunCard } from '../api/client'
import type { SortKey, SortDir } from './useLogsState'
import { Badge } from '../components/atoms/Badge'
import { stCls } from '../components/atoms/status'
import { shortTime } from '../components/atoms/format'

function fmtDuration(s: number | null | undefined): string {
  if (s == null) return '—'
  if (s < 60) return `${Math.round(s)}s`
  const m = Math.floor(s / 60)
  const r = Math.round(s % 60)
  return r > 0 ? `${m}m ${r}s` : `${m}m`
}

interface Col { key: string; label: string; sort?: SortKey; align?: 'right' }

function columns(scope: string): Col[] {
  const cols: Col[] = [
    { key: 'status', label: 'Status', sort: 'status' },
    { key: 'job', label: 'Job' },
    { key: 'id', label: '#ID', sort: 'job_id' },
    { key: 'source', label: 'Source' },
    { key: 'hosts', label: 'Hosts', sort: 'hosts', align: 'right' },
    { key: 'issues', label: 'Issues' },
    { key: 'duration', label: 'Duration', sort: 'duration', align: 'right' },
    { key: 'when', label: 'When', sort: 'when' },
  ]
  if (scope === 'team') cols.push({ key: 'team', label: 'Team' })
  return cols
}

const th: React.CSSProperties = {
  padding: '9px 12px', fontSize: 12, color: 'var(--text-3)', fontWeight: 600,
  borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap', userSelect: 'none',
}
const td: React.CSSProperties = {
  padding: '8px 12px', fontSize: 13, borderBottom: '1px solid var(--border)',
  whiteSpace: 'nowrap',
}

export function RunsTable({ items, scope, sort, dir, onSort }: {
  items: RunCard[]; scope: string; sort: SortKey; dir: SortDir; onSort: (k: SortKey) => void
}) {
  const nav = useNavigate()
  const cols = columns(scope)
  return (
    <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            {cols.map((c) => {
              const active = c.sort && sort === c.sort
              return (
                <th
                  key={c.key}
                  role="columnheader"
                  aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : undefined}
                  onClick={c.sort ? () => onSort(c.sort!) : undefined}
                  style={{ ...th, textAlign: c.align === 'right' ? 'right' : 'left', cursor: c.sort ? 'pointer' : 'default' }}
                >
                  {c.label}
                  {active && <span style={{ marginLeft: 4 }}>{dir === 'asc' ? '▲' : '▼'}</span>}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {items.map((r) => {
            const isAwx = !!r.controller_id
            const when = r.launched_at || r.log_time || r.created_at
            const clean = r.counts.failed === 0 && r.counts.unreachable === 0 && r.counts.changed === 0
            return (
              <tr
                key={r.id}
                onClick={() => nav('/runs/' + r.id)}
                style={{ cursor: 'pointer' }}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)' }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
              >
                <td className={stCls(r.status)} style={{ ...td, borderLeft: '3px solid var(--c)' }}>
                  <Badge status={r.status} />
                </td>
                <td style={{ ...td, maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {r.template_name || 'Run'}
                </td>
                <td className="mono dim" style={{ ...td }}>{r.job_id ? '#' + r.job_id : '—'}</td>
                <td style={{ ...td }}>{isAwx ? (r.controller_name || 'AWX') : 'Uploaded'}</td>
                <td className="mono tnum" style={{ ...td, textAlign: 'right' }}>{r.host_count}</td>
                <td style={{ ...td }}>
                  {clean ? <span className="dim">ok</span> : (
                    <span className="row gap1" style={{ flexWrap: 'wrap' }}>
                      {r.counts.failed > 0 && <Badge status="failed" count={r.counts.failed} withLabel={false} />}
                      {r.counts.unreachable > 0 && <Badge status="unreachable" count={r.counts.unreachable} withLabel={false} />}
                      {r.counts.changed > 0 && <Badge status="changed" count={r.counts.changed} withLabel={false} />}
                    </span>
                  )}
                </td>
                <td className="mono tnum dim" style={{ ...td, textAlign: 'right' }}>{fmtDuration(r.elapsed)}</td>
                <td className="mono dim" style={{ ...td }} title={when ?? undefined}>{shortTime(when)}</td>
                {scope === 'team' && <td style={{ ...td }}>{r.team_name || '—'}</td>}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
