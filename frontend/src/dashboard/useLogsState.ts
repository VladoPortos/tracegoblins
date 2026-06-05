import { useCallback, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router'
import type { RunFilters } from '../api/runs'

export type Tab = 'mine' | 'shared' | 'team'
export type View = 'cards' | 'table'
export type SortKey = 'when' | 'job_id' | 'hosts' | 'duration' | 'status'
export type SortDir = 'asc' | 'desc'

export const TABS: Tab[] = ['mine', 'shared', 'team']
export const VIEWS: View[] = ['cards', 'table']
export const SORT_KEYS: SortKey[] = ['when', 'job_id', 'hosts', 'duration', 'status']
const DIRS: SortDir[] = ['asc', 'desc']

export interface LogsState {
  tab: Tab
  view: View
  sort: SortKey
  dir: SortDir
  src: string // 'all' | 'uploads' | controllerId
  q: string
  filters: RunFilters // rich filters (team scope only)
}

const LS_KEY = 'tg:logs'

/** Every URL param this view owns — used for bare-load detection + localStorage mirroring. */
export const LOGS_PARAM_KEYS = [
  'tab', 'view', 'sort', 'dir', 'src', 'q',
  'template', 'status', 'org', 'awx_user', 'launch_type', 'after', 'before',
] as const

const oneOf = <T extends string>(v: string | null, allowed: T[], dflt: T): T =>
  (allowed as string[]).includes(v ?? '') ? (v as T) : dflt

export function parseLogsParams(p: URLSearchParams): LogsState {
  const filters: RunFilters = {}
  const template = p.get('template'); if (template) filters.template = template
  const statusCsv = p.get('status')
  if (statusCsv) { const s = statusCsv.split(',').filter(Boolean); if (s.length) filters.status = s }
  const org = p.get('org'); if (org && /^\d+$/.test(org)) filters.organization = parseInt(org, 10)
  const au = p.get('awx_user'); if (au) filters.awx_user = au
  const lt = p.get('launch_type'); if (lt) filters.launch_type = lt
  const after = p.get('after'); if (after) filters.launched_after = after
  const before = p.get('before'); if (before) filters.launched_before = before
  return {
    tab: oneOf(p.get('tab'), TABS, 'mine'),
    view: oneOf(p.get('view'), VIEWS, 'cards'),
    sort: oneOf(p.get('sort'), SORT_KEYS, 'when'),
    dir: oneOf(p.get('dir'), DIRS, 'desc'),
    src: p.get('src') || 'all',
    q: p.get('q') || '',
    filters,
  }
}

export function serializeLogsParams(s: LogsState): URLSearchParams {
  const p = new URLSearchParams()
  if (s.tab !== 'mine') p.set('tab', s.tab)
  if (s.view !== 'cards') p.set('view', s.view)
  if (s.sort !== 'when') p.set('sort', s.sort)
  if (s.dir !== 'desc') p.set('dir', s.dir)
  if (s.src && s.src !== 'all') p.set('src', s.src)
  if (s.q) p.set('q', s.q)
  const f = s.filters
  if (f.template) p.set('template', f.template)
  if (f.status && f.status.length) p.set('status', f.status.join(','))
  if (f.organization != null) p.set('org', String(f.organization))
  if (f.awx_user) p.set('awx_user', f.awx_user)
  if (f.launch_type) p.set('launch_type', f.launch_type)
  if (f.launched_after) p.set('after', f.launched_after)
  if (f.launched_before) p.set('before', f.launched_before)
  return p
}

/** URL-backed Logs view state. Callable by any Logs component; consistent via shared params. */
export function useLogsState() {
  const [params, setParams] = useSearchParams()
  const state = parseLogsParams(params)

  const update = useCallback((partial: Partial<LogsState>, opts?: { replace?: boolean }) => {
    const cur = parseLogsParams(new URLSearchParams(window.location.search))
    const next = serializeLogsParams({ ...cur, ...partial })
    setParams(next, { replace: opts?.replace ?? false })
  }, [setParams])

  return {
    ...state,
    setTab: (tab: Tab) => update({ tab }),
    setView: (view: View) => update({ view }),
    setSrc: (src: string) => update({ src }),
    setQ: (q: string) => update({ q }, { replace: true }),
    setFilters: (filters: RunFilters) => update({ filters }, { replace: true }),
    setSort: (key: SortKey) =>
      update({ sort: key, dir: state.sort === key && state.dir === 'desc' ? 'asc' : 'desc' }),
  }
}

/** Call ONCE (in Dashboard): restore on bare load, then mirror URL -> localStorage. */
export function useLogsPersistence() {
  const [params, setParams] = useSearchParams()
  const restored = useRef(false)

  // Restore once: only when the URL carries none of our params (a bare "/" load).
  useEffect(() => {
    if (restored.current) return
    restored.current = true
    const hasAny = LOGS_PARAM_KEYS.some((k) => params.has(k))
    if (hasAny) return
    try {
      const raw = localStorage.getItem(LS_KEY)
      if (!raw) return
      const saved = new URLSearchParams(JSON.parse(raw) as Record<string, string>)
      if ([...saved.keys()].length) setParams(saved, { replace: true })
    } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Mirror our params (and only ours) to localStorage on every change.
  useEffect(() => {
    try {
      const obj: Record<string, string> = {}
      for (const k of LOGS_PARAM_KEYS) { const v = params.get(k); if (v != null) obj[k] = v }
      localStorage.setItem(LS_KEY, JSON.stringify(obj))
    } catch { /* ignore */ }
  }, [params])
}
