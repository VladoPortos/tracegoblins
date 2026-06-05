import { useEffect, useRef } from 'react'
import { useInfiniteRuns, type RunFilters } from '../api/runs'
import { useRunFilters } from '../api/runFilters'
import { useSyncController, useControllers, type Controller } from '../api/controllers'
import { JobCard } from './JobCard'
import { RunsTable } from './RunsTable'
import { FilterBar } from './FilterBar'
import { Glyph } from '../components/atoms/Glyph'
import { EmptyState } from '../components/atoms/EmptyState'
import { FullScreenSpinner } from '../components/atoms/FullScreenSpinner'
import { LastSyncChip } from '../components/atoms/LastSyncChip'
import { SourceChips } from './SourceChips'
import { useLogsState } from './useLogsState'
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

function GroupedTeamCards({ items, controllers, onSync, syncing }: {
  items: RunCard[]
  controllers: Controller[]
  onSync: (id: string) => void
  syncing: boolean
}) {
  const awxItems = items.filter((r) => r.controller_id)
  const nonAwx = items.filter((r) => !r.controller_id)
  const controllerGroups = Object.values(awxItems.reduce<Record<string, { id: string; name: string | null; rows: RunCard[] }>>((acc, r) => {
    const key = r.controller_id!
    ;(acc[key] ??= { id: key, name: r.controller_name ?? key, rows: [] }).rows.push(r)
    return acc
  }, {})).sort((a, b) => (a.name ?? '').localeCompare(b.name ?? ''))
  const teamGroups = Object.values(nonAwx.reduce<Record<string, { name: string; rows: RunCard[] }>>((acc, r) => {
    const key = r.team_id ?? '_'
    ;(acc[key] ??= { name: r.team_name ?? 'Other', rows: [] }).rows.push(r)
    return acc
  }, {})).sort((a, b) => a.name.localeCompare(b.name))
  const cmap = Object.fromEntries(controllers.map((c) => [c.id, c]))
  return (
    <>
      {controllerGroups.map((g) => {
        const ctl = cmap[g.id]
        return (
          <div key={g.id} className="col" style={{ gap: 12 }}>
            <div className="row gap2" style={{ color: 'var(--text-2)', alignItems: 'center', flexWrap: 'wrap', gap: '6px 12px' }}>
              <Glyph name="server" size={15} style={{ color: 'var(--accent)' }} />
              <span className="h3" style={{ fontSize: 13 }}>{g.name ?? g.id}</span>
              <span className="chip mono" style={{ fontSize: 10.5 }}>{g.rows.length}</span>
              {ctl && (
                <>
                  <LastSyncChip status={ctl.last_sync_status} at={ctl.last_sync_at} error={ctl.last_sync_error} />
                  <button className="btn btn-ghost sm" onClick={() => onSync(g.id)}
                    disabled={syncing || ctl.last_sync_status === 'running'} title="Sync now" aria-label={`Sync now ${g.name ?? g.id}`} style={{ fontSize: 12 }}>
                    <Glyph name="spinner" size={13} />Sync now
                  </button>
                </>
              )}
            </div>
            <Grid items={g.rows} />
          </div>
        )
      })}
      {teamGroups.map((g) => (
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
  )
}

export function RunsList({ scope = 'mine', onUpload }: { scope?: 'mine' | 'shared' | 'team'; onUpload?: () => void }) {
  const { view, setView, sort, dir, setSort, src, q, setQ, filters, setFilters } = useLogsState()

  // Rich filters + source chips are team-scope only; never let a stored team filter narrow
  // mine/shared (which have no filter bar to reveal or clear it).
  const richFilters: RunFilters = scope === 'team' ? filters : {}
  const effSrc = scope === 'team' ? src : 'all'
  const effFilters: RunFilters = scope === 'team' && effSrc !== 'all'
    ? (effSrc === 'uploads' ? { ...richFilters, source: 'upload' } : { ...richFilters, controller: effSrc })
    : richFilters

  const runs = useInfiniteRuns(scope, effFilters, sort, dir)
  const facetsQuery = useRunFilters(scope === 'team' ? 'team' : scope === 'shared' ? 'shared' : 'mine')
  const syncCtl = useSyncController()
  const controllersQuery = useControllers({ enabled: scope === 'team' })

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

  // Client-side quick narrowing on top of server-side filters.
  const items = all.filter((r) => !q.trim() ||
    ((r.template_name || '') + ' ' + (r.job_id || '') + ' ' + (r.team_name || '') + ' ' + r.recap.map((x) => x.host).join(' ')).toLowerCase().includes(q.toLowerCase()))

  const header = (
    <div className="col" style={{ gap: 12 }}>
      {scope === 'team' && <SourceChips />}
      {scope === 'team' && <FilterBar facets={facets} filters={filters} onChange={setFilters} />}
      <div className="row gap2" style={{ alignItems: 'center', flexWrap: 'wrap' }}>
        <div className="row gap2" data-testid="runs-count" style={{ alignItems: 'baseline' }}>
          <span style={{ fontSize: 20, fontWeight: 700, letterSpacing: '-.01em' }}>{total.toLocaleString()}</span>
          <span className="muted" style={{ fontSize: 13 }}>
            {total === 1 ? 'run' : 'runs'}{q.trim() ? ` · ${items.length} shown` : ''}
          </span>
        </div>
        <div className="grow" />
        <div className="row" style={{ position: 'relative', width: 'min(260px, 100%)' }}>
          <span style={{ position: 'absolute', left: 11, color: 'var(--text-3)', display: 'grid', placeItems: 'center', height: '100%' }}>
            <Glyph name="search" size={15} />
          </span>
          <input className="input" placeholder="Search runs, hosts, IDs…" value={q} onChange={(e) => setQ(e.target.value)} style={{ paddingLeft: 34 }} />
        </div>
        <div className="seg" role="group" aria-label="View mode">
          <button aria-pressed={view === 'cards'} onClick={() => setView('cards')} title="Card view"><Glyph name="grid" size={14} />Cards</button>
          <button aria-pressed={view === 'table'} onClick={() => setView('table')} title="Table view"><Glyph name="rows" size={14} />Table</button>
        </div>
      </div>
    </div>
  )

  if (items.length === 0) {
    const narrowed = !!q.trim() || (scope === 'team' && (effSrc !== 'all' || Object.keys(richFilters).length > 0))
    return (
      <div className="col" style={{ gap: 16 }}>
        {header}
        <div className="card">
          {narrowed
            ? <EmptyState icon="search" title="No matching runs" sub="Try adjusting the filters or search." />
            : <EmptyState icon={empty.icon} title={empty.title} sub={empty.sub}
                action={scope === 'mine' && onUpload ? <button className="btn btn-primary" onClick={onUpload} style={{ marginTop: 6 }}><Glyph name="upload" size={15} />Upload log</button> : undefined} />}
        </div>
      </div>
    )
  }

  const body = view === 'table'
    ? <RunsTable items={items} scope={scope} sort={sort} dir={dir} onSort={setSort} />
    : (scope === 'team' && effSrc === 'all'
        ? <GroupedTeamCards items={items} controllers={controllersQuery.data ?? []} onSync={(id) => void syncCtl.mutateAsync(id)} syncing={syncCtl.isPending} />
        : <Grid items={items} />)

  return (
    <div className="col" style={{ gap: 16 }}>
      {header}
      {body}
      {total > all.length && <div ref={sentinelRef} style={{ height: 1 }} />}
      <div className="muted" style={{ fontSize: 12, textAlign: 'center', padding: '8px 0' }}>
        {runs.isFetchingNextPage ? 'Loading more…' : `Showing ${all.length} of ${total}`}
      </div>
    </div>
  )
}
