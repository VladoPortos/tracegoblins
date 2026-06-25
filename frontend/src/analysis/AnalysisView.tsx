import { useEffect, useMemo, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router'
import { useRun, useRunTasks, useDeleteRun } from '../api/runs'
import { Glyph } from '../components/atoms/Glyph'
import { Badge } from '../components/atoms/Badge'
import { HostBar } from '../components/atoms/HostBar'
import { EmptyState } from '../components/atoms/EmptyState'
import { FullScreenSpinner } from '../components/atoms/FullScreenSpinner'
import { StatusMap, type Filters, type JumpTo } from './StatusMap'
import { TaskDrawer } from '../drawer/TaskDrawer'
import { isErr } from '../components/atoms/status'
import { shortTime } from '../components/atoms/format'
import { ShareModal } from '../modals/ShareModal'
import { RunDiffModal } from './RunDiffModal'
import { useMe } from '../api/queries'
import { useDrawerWidth } from './useDrawerWidth'

export function AnalysisView() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const run = useRun(id)
  const tasksQ = useRunTasks(id)
  const del = useDeleteRun()
  const me = useMe()
  const [searchParams] = useSearchParams()
  const [shareOpen, setShareOpen] = useState(false)
  const [diffOpen, setDiffOpen] = useState(false)
  const [filters, setFilters] = useState<Filters>({ host: '', errorsOnly: false, hideSkipped: false, query: '' })
  const [selected, setSelected] = useState<number | null>(null)
  const [jumpTo, setJumpTo] = useState<JumpTo | null>(null)
  const set = (p: Partial<Filters>) => setFilters((f) => ({ ...f, ...p }))
  const { width: drawerWidth, set: setDrawerWidth } = useDrawerWidth()

  const startDrag = (e: ReactPointerEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const startW = drawerWidth
    const onMove = (ev: PointerEvent) => setDrawerWidth(startW + (startX - ev.clientX))
    const onUp = () => { window.removeEventListener('pointermove', onMove); window.removeEventListener('pointerup', onUp) }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  const tasks = tasksQ.data ?? []
  const hosts = useMemo(() => Array.from(new Set(tasks.flatMap((t) => Object.keys(t.hosts)))), [tasks])
  const firstErr = useMemo(() => tasks.find((t) => isErr(t.status)), [tasks])
  const selTask = useMemo(() => tasks.find((t) => t.seq === selected) ?? null, [tasks, selected])
  const goFirstFail = () => { if (firstErr) { setSelected(firstErr.seq); setJumpTo({ seq: firstErr.seq, nonce: Date.now() }) } }
  // Return to wherever the user came from (preserving the dashboard tab/source they were on);
  // fall back to the logs root for deep links / fresh tabs with no in-app history.
  const goBack = () => { if (window.history.length > 1) nav(-1); else nav('/') }

  // Reset per-run view state when navigating between runs while this view stays
  // mounted (e.g. the diff modal's baseline link). Runs BEFORE the ?task deep-link
  // effect below, so a ?task param on the new URL still applies after the reset.
  useEffect(() => {
    setSelected(null)
    setJumpTo(null)
    setDiffOpen(false)
    setShareOpen(false)
  }, [id])

  const taskParam = searchParams.get('task')
  useEffect(() => {
    if (taskParam == null || tasks.length === 0) return
    const seq = Number(taskParam)
    if (!Number.isNaN(seq) && tasks.some((t) => t.seq === seq)) {
      setSelected(seq)
      setJumpTo({ seq, nonce: Date.now() })
    }
  }, [taskParam, tasks])

  if (run.isPending || tasksQ.isPending) return <FullScreenSpinner />
  if (run.isError) return <EmptyState icon="alert" title="Run not found" sub="It may have been deleted or you don't have access." action={<button className="btn" onClick={() => nav('/')}>Back to logs</button>} />
  const d = run.data!
  const isOwner = !!me.data && d.owner_user_id === me.data.id
  const errCount = (d.counts.unreachable || 0) + (d.counts.failed || 0)

  return (
    <div className="col" style={{ height: '100%', minWidth: 0 }}>
      <div style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface)' }}>
        <div className="row gap3" style={{ padding: '12px 18px' }}>
          <button className="btn icon btn-ghost" onClick={goBack} aria-label="Back"><Glyph name="chevL" size={18} /></button>
          <Badge status={d.status} />
          <div className="col" style={{ gap: 1, minWidth: 0 }}>
            <div className="row gap2"><span className="h2" style={{ fontSize: 16 }}>{d.template_name || 'Run'}</span>{d.job_id && <span className="mono dim" style={{ fontSize: 13 }}>{'#' + d.job_id}</span>}</div>
            <div className="row gap2 mono" style={{ fontSize: 11, color: 'var(--text-3)' }}><Glyph name="clock" size={11} />{d.log_time ? shortTime(d.log_time) : 'uploaded ' + shortTime(d.created_at)}<span style={{ opacity: 0.4 }}>·</span>{d.task_count + ' tasks'}</div>
          </div>
          <div className="grow" />
          {firstErr && <button className="btn sm btn-danger" onClick={goFirstFail}><Glyph name="alert" size={14} />First failure</button>}
          {d.template_name && <button className="btn sm btn-ghost" onClick={() => setDiffOpen(true)}><Glyph name="layers" size={14} />Diff vs last green</button>}
          <button className="btn sm btn-ghost" onClick={() => nav(`/runs/${id}/path`)}><Glyph name="map" size={14} />Path view</button>
          {isOwner && <button className="btn btn-ghost" onClick={() => setShareOpen(true)}><Glyph name="share" size={15} />Share</button>}
          {isOwner && <button className="btn btn-danger" onClick={() => { if (confirm('Delete this run?')) del.mutate(id, { onSuccess: () => nav('/') }) }}><Glyph name="close" size={15} />Delete</button>}
        </div>
        <div className="row gap4" style={{ padding: '10px 18px', borderTop: '1px solid var(--border)', background: 'var(--surface-2)', flexWrap: 'wrap' }}>
          <div className="row gap3" style={{ flexWrap: 'wrap' }}>
            {d.recap.map((r) => (
              <div key={r.host} className="col" style={{ gap: 4, minWidth: 200 }}>
                <div className="row gap2"><span className="mono truncate" style={{ fontSize: 11.5, fontWeight: 500, color: (r.unreachable || r.failed) ? 'var(--unreachable)' : 'var(--text)' }}>{r.host}</span><div className="grow" /><span className="mono dim tnum" style={{ fontSize: 10.5 }}>{'ok ' + r.ok}</span></div>
                <HostBar recap={r as unknown as Record<string, number>} height={7} />
              </div>
            ))}
          </div>
          <div className="grow" />
          <div className="row gap1 wrap">{errCount > 0 && <Badge status="unreachable" count={errCount} />}{d.counts.changed > 0 && <Badge status="changed" count={d.counts.changed} />}{d.counts.ok > 0 && <Badge status="ok" count={d.counts.ok} />}{d.counts.skipped > 0 && <span className="chip">{d.counts.skipped + ' skipped'}</span>}</div>
        </div>
        <div className="row gap2" style={{ padding: '9px 18px', borderTop: '1px solid var(--border)', flexWrap: 'wrap' }}>
          <div className="row gap2" style={{ color: 'var(--text-2)' }}><Glyph name="map" size={15} style={{ color: 'var(--accent)' }} /><span className="h3" style={{ fontSize: 13 }}>Status map</span></div>
          <div className="grow" />
          <div className="row" style={{ position: 'relative', width: 'min(230px,40vw)' }}><span style={{ position: 'absolute', left: 10, color: 'var(--text-3)', display: 'grid', placeItems: 'center', height: '100%' }}><Glyph name="search" size={14} /></span><input className="input" placeholder="Filter tasks…" value={filters.query} onChange={(e) => set({ query: e.target.value })} style={{ paddingLeft: 32, height: 34 }} /></div>
          <select className="select" style={{ width: 150, height: 34 }} value={filters.host} onChange={(e) => set({ host: e.target.value })} aria-label="Filter by host"><option value="">All hosts</option>{hosts.map((h) => <option key={h} value={h}>{h}</option>)}</select>
          <button className={'btn sm' + (filters.errorsOnly ? ' btn-primary' : ' btn-ghost')} aria-pressed={filters.errorsOnly} onClick={() => set({ errorsOnly: !filters.errorsOnly })}><Glyph name="alert" size={14} />Errors only</button>
          <button className={'btn sm' + (filters.hideSkipped ? ' btn-primary' : ' btn-ghost')} aria-pressed={filters.hideSkipped} onClick={() => set({ hideSkipped: !filters.hideSkipped })}><Glyph name="filter" size={14} />Hide skipped</button>
        </div>
      </div>
      <div className="row" style={{ flex: '1 1 auto', minHeight: 0, alignItems: 'stretch' }}>
        <div className="grow" style={{ minWidth: 0, background: 'var(--surface)' }}>
          {filters.errorsOnly && errCount === 0
            ? <EmptyState icon="check" title="No failures in this run" sub="Every task is ok, changed, or skipped. Turn off Errors only to see the full run." />
            : <StatusMap tasks={tasks} filters={filters} selected={selected} onSelect={setSelected} jumpTo={jumpTo} />}
        </div>
        {selTask && (
          <>
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize details panel"
              onPointerDown={startDrag}
              style={{ width: 6, cursor: 'col-resize', flex: 'none', background: 'transparent' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--border-strong)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            />
            <TaskDrawer runId={id} lean={selTask} width={`${drawerWidth}px`} onClose={() => setSelected(null)} runOwnerId={d.owner_user_id ?? undefined} currentUserId={me.data?.id ?? ''} teams={me.data?.teams ?? []} isAdmin={me.data?.role === 'admin'} />
          </>
        )}
      </div>
      {isOwner && <ShareModal open={shareOpen} onOpenChange={setShareOpen} runId={id} teams={me.data?.teams ?? []} />}
      <RunDiffModal runId={id} open={diffOpen} onOpenChange={setDiffOpen}
        onJump={(seq) => {
          // Clear host/query filters so the jumped task's row is present in the map and the
          // scroll/highlight lands (errorsOnly/hideSkipped are status-based and let failures through).
          setFilters((f) => ({ ...f, host: '', query: '' }))
          setSelected(seq); setJumpTo({ seq, nonce: Date.now() }); setDiffOpen(false)
        }} />
    </div>
  )
}
