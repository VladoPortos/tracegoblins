import { useState, useEffect, useRef } from 'react'
import { useInfiniteRuns, type RunFilters } from '../api/runs'
import { useRunFilters } from '../api/runFilters'
import { useSyncController, useControllers } from '../api/controllers'
import { JobCard } from './JobCard'
import { FilterBar } from './FilterBar'
import { Glyph } from '../components/atoms/Glyph'
import { EmptyState } from '../components/atoms/EmptyState'
import { FullScreenSpinner } from '../components/atoms/FullScreenSpinner'
import { LastSyncChip } from '../components/atoms/LastSyncChip'
import { SourceChips, useSourceSelection } from './SourceChips'
import type { RunCard } from '../api/client'

const EMPTY: Record<'mine' | 'shared' | 'team', { icon: string; title: string; sub: string }> = {
  mine: { icon: 'inbox', title: 'No logs yet', sub: 'Upload or paste an AWX/Ansible job log to get started.' },
  shared: { icon: 'inbox', title: 'Nothing shared with you yet', sub: 'Runs others share with you — directly or via a team — show up here.' },
  team: { icon: 'users', title: 'No team logs yet', sub: 'Runs uploaded to one of your teams (or shared with a team) appear here.' },
}

function Grid({ items }: { items: RunCard[] }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(330px, 1fr))', gap: 16 }}>
      {items.map((r) => <JobCard key={r.id} run={r} />)}
    </div>
  )
}

export function RunsList({ scope = 'mine', onUpload }: { scope?: 'mine' | 'shared' | 'team'; onUpload?: () => void }) {
  const [filters, setFilters] = useState<RunFilters>({})
  const runs = useInfiniteRuns(scope, filters)
  const facetsQuery = useRunFilters(scope === 'team' ? 'team' : scope === 'shared' ? 'shared' : 'mine')
  const syncCtl = useSyncController()
  // Only the team grouped view needs controller metadata (sync chips / names). On
  // mine/shared this query is unused, so skip it to avoid a wasted request + 1.5s poll.
  const controllersQuery = useControllers({ enabled: scope === 'team' })
  const [q, setQ] = useState('')
  const [src] = useSourceSelection()

  const sentinelRef = useRef<HTMLDivElement | null>(null)
  const all = (runs.data?.pages ?? []).flatMap((p) => p.items)
  const total = runs.data?.pages?.[0]?.total ?? 0

  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const io = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting && runs.hasNextPage && !runs.isFetchingNextPage) {
        void runs.fetchNextPage()
      }
    }, { rootMargin: '400px' })
    io.observe(el)
    return () => io.disconnect()
  }, [runs.hasNextPage, runs.isFetchingNextPage, all.length])

  if (runs.isPending) return <FullScreenSpinner />

  if (runs.isError)
    return (
      <div className="card">
        <EmptyState icon="alert" title="Couldn't load runs" sub="Something went wrong fetching your runs. Try again." />
      </div>
    )
  const empty = EMPTY[scope]
  const facets = facetsQuery.data ?? { organizations: [], templates: [], controllers: [], statuses: [], launch_types: [], users: [] }

  // Client-side text search (on top of server-side filters) for quick local narrowing
  const items = all.filter((r) => !q.trim() ||
    ((r.template_name || '') + ' ' + (r.job_id || '') + ' ' + (r.team_name || '') + ' ' + r.recap.map((x) => x.host).join(' ')).toLowerCase().includes(q.toLowerCase()))

  // Source chip scoping — narrows to a specific controller or uploads-only
  const scoped = scope === 'team' && src !== 'all'
    ? items.filter((r) => src === 'uploads' ? !r.controller_id : r.controller_id === src)
    : items

  // Team scope: group by controller first (AWX runs), then by team for uploads
  const showGrouped = scope === 'team'

  if (items.length === 0 && !showGrouped)
    return (
      <div className="card">
        <EmptyState icon={empty.icon} title={empty.title} sub={empty.sub}
          action={scope === 'mine' && onUpload ? <button className="btn btn-primary" onClick={onUpload} style={{ marginTop: 6 }}><Glyph name="upload" size={15} />Upload log</button> : undefined} />
      </div>
    )

  // For team scope, partition into AWX runs (have controller_id) and non-AWX
  const awxItems = showGrouped ? items.filter((r) => r.controller_id) : []
  const nonAwxItems = showGrouped ? items.filter((r) => !r.controller_id) : items

  // Group AWX items per controller
  const controllerGroups = showGrouped
    ? Object.values(awxItems.reduce<Record<string, { id: string; name: string | null; rows: RunCard[] }>>((acc, r) => {
        const key = r.controller_id!
        ;(acc[key] ??= { id: key, name: r.controller_name ?? key, rows: [] }).rows.push(r)
        return acc
      }, {})).sort((a, b) => (a.name ?? '').localeCompare(b.name ?? ''))
    : []

  // Group non-AWX team items by team
  const teamGroups = showGrouped
    ? Object.values(nonAwxItems.reduce<Record<string, { name: string; rows: RunCard[] }>>((acc, r) => {
        const key = r.team_id ?? '_'
        ;(acc[key] ??= { name: r.team_name ?? 'Other', rows: [] }).rows.push(r)
        return acc
      }, {})).sort((a, b) => a.name.localeCompare(b.name))
    : null

  const controllerMap = Object.fromEntries((controllersQuery.data ?? []).map((c) => [c.id, c]))

  return (
    <div className="col" style={{ gap: 16 }}>
      {/* Source selector chips — team scope only */}
      {scope === 'team' && <SourceChips />}

      {/* Filter bar — team scope only, when facets are available */}
      {scope === 'team' && (
        <FilterBar facets={facets} filters={filters} onChange={setFilters} />
      )}

      {/* Local text search */}
      <div className="row" style={{ position: 'relative', width: 'min(280px, 100%)' }}>
        <span style={{ position: 'absolute', left: 11, color: 'var(--text-3)', display: 'grid', placeItems: 'center', height: '100%' }}>
          <Glyph name="search" size={15} />
        </span>
        <input className="input" placeholder="Search runs, hosts, IDs…" value={q} onChange={(e) => setQ(e.target.value)} style={{ paddingLeft: 34 }} />
      </div>

      {/* Team scope with a specific source selected — flat grid, no grouping */}
      {showGrouped && src !== 'all' && (
        scoped.length === 0
          ? (
            <div className="card">
              <EmptyState icon={empty.icon} title="No matching runs" sub="Try a different source or adjust filters." />
            </div>
          )
          : <Grid items={scoped} />
      )}

      {/* Team scope 'all' — existing grouped view */}
      {showGrouped && src === 'all' && (
        <>
          {items.length === 0 && (
            <div className="card">
              <EmptyState icon={empty.icon} title="No matching runs" sub="Try adjusting the filters above." />
            </div>
          )}

          {/* Per-controller AWX groups */}
          {controllerGroups.map((g) => {
            const ctl = controllerMap[g.id]
            return (
              <div key={g.id} className="col" style={{ gap: 12 }}>
                <div className="row gap2" style={{ color: 'var(--text-2)', alignItems: 'center', flexWrap: 'wrap', gap: '6px 12px' }}>
                  <Glyph name="server" size={15} style={{ color: 'var(--accent)' }} />
                  <span className="h3" style={{ fontSize: 13 }}>{g.name ?? g.id}</span>
                  <span className="chip mono" style={{ fontSize: 10.5 }}>{g.rows.length}</span>
                  {ctl && (
                    <>
                      <LastSyncChip status={ctl.last_sync_status} at={ctl.last_sync_at} error={ctl.last_sync_error} />
                      <button
                        className="btn btn-ghost sm"
                        onClick={() => void syncCtl.mutateAsync(g.id)}
                        disabled={syncCtl.isPending || ctl.last_sync_status === 'running'}
                        aria-label={`Sync now ${g.name ?? g.id}`}
                        title="Sync now"
                        style={{ fontSize: 12 }}
                      >
                        <Glyph name="spinner" size={13} />
                        Sync now
                      </button>
                    </>
                  )}
                </div>
                <Grid items={g.rows} />
              </div>
            )
          })}

          {/* Non-AWX team groups (uploads / shared) */}
          {teamGroups && teamGroups.map((g) => (
            <div key={g.name} className="col" style={{ gap: 12 }}>
              <div className="row gap2" style={{ color: 'var(--text-2)' }}>
                <Glyph name="users" size={15} style={{ color: 'var(--accent)' }} />
                <span className="h3" style={{ fontSize: 13 }}>{g.name}</span>
                <span className="chip mono" style={{ fontSize: 10.5 }}>{g.rows.length}</span>
              </div>
              <Grid items={g.rows} />
            </div>
          ))}
        </>
      )}

      {/* Non-team scopes — flat grid */}
      {!showGrouped && <Grid items={scoped} />}

      {total > all.length && <div ref={sentinelRef} style={{ height: 1 }} />}
      <div className="muted" style={{ fontSize: 12, textAlign: 'center', padding: '8px 0' }}>
        {runs.isFetchingNextPage ? 'Loading more…' : `Showing ${all.length} of ${total}`}
      </div>
    </div>
  )
}
