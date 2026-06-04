import { useMemo, useRef, useState, useEffect } from 'react'
import type { TaskLean } from '../api/client'
import { STATUS, isErr, stCls } from '../components/atoms/status'
import { HostBar } from '../components/atoms/HostBar'

const roleLabel = (r: string | null) => (r ? r.replace(/^dxc\.xaas\./, '') : 'play tasks')

// Compact per-task duration from job_events: sub-minute -> "1.2s" / "3s", else "2m 5s".
function fmtDur(seconds: number): string {
  if (seconds < 60) {
    const r = Math.round(seconds * 10) / 10
    return (Number.isInteger(r) ? String(r) : r.toFixed(1)) + 's'
  }
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return s > 0 ? `${m}m ${s}s` : `${m}m`
}
export interface Filters { host: string; errorsOnly: boolean; hideSkipped: boolean; query: string }
export interface JumpTo { seq: number; nonce: number }

function passFilter(t: TaskLean, f: Filters): boolean {
  if (f.host && !(f.host in t.hosts)) return false
  if (f.errorsOnly && !isErr(t.status)) return false
  if (f.hideSkipped && t.status === 'skipped') return false
  if (f.query) { const q = f.query.toLowerCase(); if (!((t.name + ' ' + (t.role || '')).toLowerCase().includes(q))) return false }
  return true
}
function statsOf(tasks: TaskLean[]) {
  const c: Record<string, number> = { ok: 0, changed: 0, skipped: 0, unreachable: 0, failed: 0, included: 0 }
  tasks.forEach((t) => { c[t.status] = (c[t.status] || 0) + 1 }); return c
}
type Item = { type: 'task'; task: TaskLean } | { type: 'skip'; tasks: TaskLean[]; count: number }
function collapseSkipped(tasks: TaskLean[], f: Filters): Item[] {
  const items: Item[] = []; let run: TaskLean[] = []
  const flush = () => {
    if (run.length >= 3) items.push({ type: 'skip', tasks: run.slice(), count: run.length })
    else run.forEach((t) => items.push({ type: 'task', task: t })); run = []
  }
  tasks.forEach((t) => { if (t.status === 'skipped' && !f.errorsOnly) run.push(t); else { flush(); items.push({ type: 'task', task: t }) } })
  flush(); return items
}
interface Group { key: string; role: string | null; tasks: TaskLean[]; items: Item[]; stats: Record<string, number> }
interface PlayVM { name: string; pi: number; groups: Group[]; stats: Record<string, number>; rawCount: number; shown: number }

function buildPlays(tasks: TaskLean[], f: Filters): PlayVM[] {
  const plays: { name: string; tasks: TaskLean[] }[] = []
  let curPlay: { name: string; tasks: TaskLean[] } | null = null
  for (const t of tasks) {
    if (!curPlay || curPlay.name !== t.play_name) { curPlay = { name: t.play_name, tasks: [] }; plays.push(curPlay) }
    curPlay.tasks.push(t)
  }
  return plays.map((play, pi) => {
    const shownTasks = play.tasks.filter((t) => passFilter(t, f))
    const groups: Group[] = []; let cur: Group | null = null
    shownTasks.forEach((t) => {
      const key = t.role || '·main'
      if (!cur || cur.key !== key) { cur = { key, role: t.role, tasks: [], items: [], stats: {} }; groups.push(cur) }
      cur.tasks.push(t)
    })
    groups.forEach((g) => { g.items = collapseSkipped(g.tasks, f); g.stats = statsOf(g.tasks) })
    return { name: play.name, pi, groups, stats: statsOf(shownTasks), rawCount: play.tasks.length, shown: shownTasks.length }
  })
}

type Hover = { seq: number; name: string; status: string; role: string | null; y: number }

export function StatusMap({ tasks, filters, selected, onSelect, jumpTo }:
  { tasks: TaskLean[]; filters: Filters; selected: number | null; onSelect: (seq: number) => void; jumpTo: JumpTo | null }) {
  const plays = useMemo(() => buildPlays(tasks, filters), [tasks, filters])
  const scrollRef = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<Hover | null>(null)

  const playGroups = useMemo(() => plays.map((p) => ({ pi: p.pi, name: p.name,
    tasks: p.groups.flatMap((g) => g.items.flatMap((it) => it.type === 'task' ? [{ ...it.task, _role: g.role }] : it.tasks.map((t) => ({ ...t, _role: g.role })))) })), [plays])

  const scrollToSeq = (seq: number) => { const el = document.getElementById('smrow-' + seq); if (el && scrollRef.current) scrollRef.current.scrollTo({ top: el.offsetTop - 120, behavior: 'smooth' }) }
  const jump = (seq: number) => { onSelect(seq); scrollToSeq(seq) }
  useEffect(() => { if (jumpTo) scrollToSeq(jumpTo.seq) }, [jumpTo?.nonce])

  const Row = ({ task, depth }: { task: TaskLean; depth: number }) => {
    const sel = selected === task.seq; const err = isErr(task.status)
    const hs = Object.entries(task.hosts)
    return (
      <div id={'smrow-' + task.seq} onClick={() => onSelect(task.seq)} className="row gap2"
        style={{ padding: '5px 10px', paddingLeft: 12 + depth * 14, cursor: 'pointer', borderRadius: 7,
          background: sel ? 'var(--accent-weak)' : 'transparent', boxShadow: sel ? 'inset 2px 0 0 var(--accent)' : 'none' }}
        onMouseEnter={(e) => { if (!sel) e.currentTarget.style.background = 'var(--surface-2)' }}
        onMouseLeave={(e) => { if (!sel) e.currentTarget.style.background = 'transparent' }}>
        <span className="mono dim tnum" style={{ fontSize: 10.5, width: 30, textAlign: 'right', flex: 'none' }}>{task.seq}</span>
        <span className="truncate" style={{ fontSize: 12.5, width: '42%', color: task.status === 'skipped' ? 'var(--text-3)' : 'var(--text)', fontWeight: err ? 600 : 400 }}>{task.name}</span>
        {task.duration_s != null && (
          <span className="mono dim tnum" title="Task duration (job_events)"
            style={{ fontSize: 10.5, flex: 'none', minWidth: 38, textAlign: 'right' }}>
            {fmtDur(task.duration_s)}
          </span>
        )}
        <div className="row gap1 grow" style={{ justifyContent: 'flex-end' }}>
          {hs.length ? hs.map(([h, s]) => (
            <div key={h} title={h + ': ' + s} className={stCls(s) + (isErr(s) ? ' errpulse-cell' : '')}
              style={{ height: 14, minWidth: hs.length > 2 ? 14 : 46, flex: hs.length > 2 ? 'none' : '0 1 70px', borderRadius: 4,
                background: 'var(--cb)', border: '1px solid var(--cl)', display: 'flex', alignItems: 'center', gap: 5, padding: '0 6px', overflow: 'hidden',
                animation: isErr(s) ? 'errpulse-cell 1.7s ease-in-out infinite' : 'none' }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--c)', flex: 'none' }} />
              {hs.length <= 2 && <span className="mono truncate" style={{ fontSize: 9.5, color: 'var(--c)' }}>{h}</span>}
            </div>
          )) : <span className="dim mono" style={{ fontSize: 10 }}>no host</span>}
        </div>
      </div>
    )
  }

  return (
    <div className="row" style={{ height: '100%', gap: 0, alignItems: 'stretch', position: 'relative' }}>
      <div style={{ width: 46, flex: 'none', borderRight: '1px solid var(--border)', padding: '8px 0', overflow: 'auto', background: 'var(--surface-2)' }} onMouseLeave={() => setHover(null)}>
        <div className="eyebrow" style={{ fontSize: 8, textAlign: 'center', marginBottom: 6 }}>Map</div>
        {playGroups.map((pg, pi) => (
          <div key={pg.pi} className="col" style={{ alignItems: 'center' }}>
            {pi > 0 && <div style={{ width: '60%', height: 1, background: 'var(--border-strong)', margin: '6px 0' }} />}
            <div className="mono dim" style={{ fontSize: 8, marginBottom: 3, letterSpacing: '.04em' }}>{'P' + (pg.pi + 1)}</div>
            <div className="col" style={{ width: 26, gap: 0, borderRadius: 3, overflow: 'hidden' }}>
              {pg.tasks.map((t) => (
                <button key={t.seq} onClick={() => jump(t.seq)} aria-label={t.name}
                  onMouseEnter={(e) => setHover({ seq: t.seq, name: t.name, status: t.status, role: (t as TaskLean & { _role: string | null })._role, y: e.clientY })}
                  className={stCls(t.status) + (isErr(t.status) ? ' errpulse' : '')}
                  style={{ width: '100%', display: 'block', height: isErr(t.status) ? 5 : 3, background: 'var(--c)',
                    opacity: t.status === 'skipped' ? 0.42 : 1, border: 'none', cursor: 'pointer', padding: 0,
                    outline: selected === t.seq ? '2px solid var(--accent)' : (hover && hover.seq === t.seq ? '1px solid var(--text)' : 'none'),
                    outlineOffset: -1, position: 'relative', zIndex: (isErr(t.status) || selected === t.seq) ? 1 : 0,
                    animation: isErr(t.status) ? 'errpulse 1.6s ease-in-out infinite' : 'none' }} />
              ))}
            </div>
          </div>
        ))}
      </div>
      {hover && (
        <div style={{ position: 'fixed', left: 54, top: Math.max(66, Math.min(hover.y - 16, (typeof innerHeight !== 'undefined' ? innerHeight : 700) - 72)),
          zIndex: 60, pointerEvents: 'none', background: 'var(--surface)', border: '1px solid var(--border-strong)', borderRadius: 9, boxShadow: 'var(--shadow-2)', padding: '8px 11px', maxWidth: 320 }}>
          <div className="row gap2" style={{ marginBottom: 3 }}>
            <span className={'badge ' + stCls(hover.status)} style={{ fontSize: 9.5 }}>{STATUS[hover.status as keyof typeof STATUS]?.label ?? hover.status}</span>
            <span className="mono dim" style={{ fontSize: 10 }}>{'#' + hover.seq}</span>
            {hover.role && <span className="mono" style={{ fontSize: 9.5, color: 'var(--accent)' }}>{roleLabel(hover.role)}</span>}
          </div>
          <div style={{ fontSize: 12.5, fontWeight: 500, lineHeight: 1.4 }}>{hover.name}</div>
        </div>
      )}
      <div ref={scrollRef} className="grow scroll" style={{ padding: '8px 8px 60px' }}>
        {plays.map((play) => (
          <div key={play.pi} className="col" style={{ gap: 1, marginBottom: 6 }}>
            <div className="row gap2" style={{ padding: '8px 10px', position: 'sticky', top: 0, background: 'var(--surface)', zIndex: 2, borderBottom: '1px solid var(--border)' }}>
              <span className="eyebrow" style={{ fontSize: 9 }}>Play</span>
              <span className="h3" style={{ fontSize: 13 }}>{play.name}</span>
              <div className="grow" />
              <div style={{ width: 160 }}><HostBar recap={play.stats} height={8} /></div>
            </div>
            {play.groups.map((g, gi) => (
              <div key={gi} className="col" style={{ gap: 1 }}>
                {g.role && <div className="row gap2" style={{ padding: '4px 10px' }}><span className="mono" style={{ fontSize: 10.5, fontWeight: 600, color: 'var(--accent)', textTransform: 'uppercase' }}>{roleLabel(g.role)}</span></div>}
                {g.items.map((it, ii) => it.type === 'skip'
                  ? <div key={'s' + ii} className="row gap2" style={{ padding: '4px 10px 4px 14px', color: 'var(--text-3)', fontSize: 11.5, fontStyle: 'italic' }}><span className="dot-status st-skipped" style={{ width: 6, height: 6 }} />{it.count + ' skipped'}</div>
                  : <Row key={it.task.seq} task={it.task} depth={g.role ? 1 : 0} />)}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
