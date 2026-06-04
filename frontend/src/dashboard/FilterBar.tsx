import type { RunFacets } from '../api/runFilters'
import type { RunFilters } from '../api/runs'
import { Glyph } from '../components/atoms/Glyph'

interface FilterBarProps {
  facets: RunFacets
  filters: RunFilters
  onChange: (f: RunFilters) => void
}

const STATUS_ORDER = ['unreachable', 'failed', 'changed', 'ok']

export function FilterBar({ facets, filters, onChange }: FilterBarProps) {
  const set = <K extends keyof RunFilters>(k: K, v: RunFilters[K]) =>
    onChange({ ...filters, [k]: v })

  function toggleStatus(s: string) {
    const cur = filters.status ?? []
    const next = cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]
    set('status', next.length ? next : undefined)
  }

  function clear() {
    onChange({})
  }

  const hasFilters = Object.values(filters).some((v) =>
    v !== undefined && v !== '' && !(Array.isArray(v) && v.length === 0)
  )

  return (
    <div className="card" style={{ padding: '10px 14px' }}>
      <div className="row gap2 wrap" style={{ alignItems: 'center', gap: '8px 12px' }}>
        {/* Organization dropdown */}
        {facets.organizations.length > 0 && (
          <select
            className="input"
            style={{ width: 'auto', minWidth: 140, fontSize: 13 }}
            value={filters.organization ?? ''}
            onChange={(e) => set('organization', e.target.value ? parseInt(e.target.value, 10) : undefined)}
            aria-label="Organization"
          >
            <option value="">All organizations</option>
            {facets.organizations.map((o) => (
              <option key={o.id} value={o.id}>{o.name ?? String(o.id)}</option>
            ))}
          </select>
        )}

        {/* Template search */}
        <div style={{ position: 'relative' }}>
          <span style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-3)', display: 'grid', placeItems: 'center' }}>
            <Glyph name="search" size={13} />
          </span>
          <input
            className="input"
            style={{ paddingLeft: 28, width: 180, fontSize: 13 }}
            placeholder="Template…"
            value={filters.template ?? ''}
            onChange={(e) => set('template', e.target.value || undefined)}
            aria-label="Template search"
          />
        </div>

        {/* Status multi-toggle */}
        {facets.statuses.length > 0 && (
          <div className="row gap1" style={{ alignItems: 'center' }}>
            <span style={{ fontSize: 12, color: 'var(--text-3)', marginRight: 2 }}>Status</span>
            {STATUS_ORDER.filter((s) => facets.statuses.includes(s)).map((s) => {
              const active = (filters.status ?? []).includes(s)
              return (
                <button
                  key={s}
                  className={'btn btn-ghost sm ' + (active ? 'btn-primary' : '')}
                  style={{ fontSize: 12, padding: '2px 8px', minHeight: 26,
                           background: active ? `var(--${s === 'ok' ? 'ok' : s === 'changed' ? 'changed' : 'unreachable'})` : undefined,
                           color: active ? '#fff' : undefined,
                           borderColor: active ? 'transparent' : undefined }}
                  onClick={() => toggleStatus(s)}
                  aria-pressed={active}
                  aria-label={`Filter status ${s}`}
                >
                  {s}
                </button>
              )
            })}
          </div>
        )}

        {/* Launched-by (awx_user) */}
        {facets.users.length > 0 && (
          <select
            className="input"
            style={{ width: 'auto', minWidth: 130, fontSize: 13 }}
            value={filters.awx_user ?? ''}
            onChange={(e) => set('awx_user', e.target.value || undefined)}
            aria-label="Launched by"
          >
            <option value="">All users</option>
            {facets.users.map((u) => (
              <option key={u} value={u}>{u}</option>
            ))}
          </select>
        )}

        {/* Launch type */}
        {facets.launch_types.length > 0 && (
          <select
            className="input"
            style={{ width: 'auto', minWidth: 120, fontSize: 13 }}
            value={filters.launch_type ?? ''}
            onChange={(e) => set('launch_type', e.target.value || undefined)}
            aria-label="Launch type"
          >
            <option value="">All types</option>
            {facets.launch_types.map((lt) => (
              <option key={lt} value={lt}>{lt}</option>
            ))}
          </select>
        )}

        {/* Time range */}
        <div className="row gap1" style={{ alignItems: 'center' }}>
          <input
            className="input"
            type="date"
            style={{ width: 136, fontSize: 12 }}
            value={filters.launched_after?.slice(0, 10) ?? ''}
            onChange={(e) => set('launched_after', e.target.value ? e.target.value + 'T00:00:00Z' : undefined)}
            aria-label="Launched after"
            title="Launched after"
          />
          <span style={{ color: 'var(--text-3)', fontSize: 12 }}>–</span>
          <input
            className="input"
            type="date"
            style={{ width: 136, fontSize: 12 }}
            value={filters.launched_before?.slice(0, 10) ?? ''}
            onChange={(e) => set('launched_before', e.target.value ? e.target.value + 'T23:59:59Z' : undefined)}
            aria-label="Launched before"
            title="Launched before"
          />
        </div>

        {/* Clear */}
        {hasFilters && (
          <button className="btn btn-ghost sm" onClick={clear} aria-label="Clear filters" style={{ marginLeft: 'auto', fontSize: 12 }}>
            <Glyph name="close" size={13} /> Clear
          </button>
        )}
      </div>
    </div>
  )
}
