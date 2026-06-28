import { useRunInputs } from '../api/path'

interface InputsPanelProps {
  runId: string
}

function KvRow({ k, v, alt }: { k: string; v: string; alt: boolean }) {
  return (
    <div
      style={{
        display: 'flex', justifyContent: 'space-between', gap: 14,
        padding: '7px 11px',
        background: alt ? 'var(--surface-2)' : 'transparent',
      }}
    >
      <span className="mono" style={{ fontSize: 12, color: 'var(--dim)', fontFeatureSettings: "'zero'", flexShrink: 0 }}>{k}</span>
      <span className="mono" style={{ fontSize: 12, color: 'var(--text)', fontFeatureSettings: "'zero'", textAlign: 'right', wordBreak: 'break-all' }}>{v}</span>
    </div>
  )
}

function KvSection({ label, rows }: { label: string; rows: [string, string][] }) {
  if (!rows.length) return null
  return (
    <div>
      <div className="eyebrow" style={{ marginBottom: 7 }}>{label}</div>
      <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
        {rows.map(([k, v], i) => <KvRow key={k} k={k} v={v} alt={i % 2 === 1} />)}
      </div>
    </div>
  )
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'baseline' }}>
      <span style={{ fontSize: 11, color: 'var(--dim)', minWidth: 90 }}>{label}</span>
      <span className="mono" style={{ fontSize: 12, color: 'var(--text)', fontFeatureSettings: "'zero'" }}>{value}</span>
    </div>
  )
}

export function InputsPanel({ runId }: InputsPanelProps) {
  const { data, isPending } = useRunInputs(runId)

  return (
    <div
      data-testid="inputs-panel"
      style={{
        position: 'absolute', top: 42, right: 0,
        width: 340,
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: '0 0 0 10px',
        boxShadow: '-8px 8px 32px rgba(0,0,0,.32)',
        zIndex: 30,
        display: 'flex', flexDirection: 'column',
      }}
    >
      {/* Panel header */}
      <div style={{
        padding: '11px 14px 10px',
        borderBottom: '1px solid var(--border)',
        fontSize: 12, fontWeight: 600, color: 'var(--text)',
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <span style={{ fontSize: 14 }}>⤷</span>
        Run Inputs
        <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--dim)', marginLeft: 'auto' }}>
          given these values, the run took this path
        </span>
      </div>

      {isPending ? (
        <div style={{ padding: '16px 14px', color: 'var(--dim)', fontSize: 12 }}>Loading…</div>
      ) : data ? (
        <div className="scroll" style={{ padding: '14px', maxHeight: 420, display: 'flex', flexDirection: 'column', gap: 14 }}>

          {/* extra_vars */}
          <KvSection
            label="Extra vars"
            rows={Object.entries(data.extra_vars).map(([k, v]) => [k, typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v)])}
          />

          {/* survey */}
          {data.survey && Object.keys(data.survey).length > 0 && (
            <KvSection
              label="Survey"
              rows={Object.entries(data.survey).map(([k, v]) => [k, typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v)])}
            />
          )}

          {/* limit / scm_revision / project */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div className="eyebrow" style={{ marginBottom: 3 }}>Run context</div>
            {data.limit && <MetaRow label="limit" value={data.limit} />}
            {data.scm_revision && <MetaRow label="scm_revision" value={data.scm_revision} />}
            {data.project_name && <MetaRow label="project" value={data.project_name} />}
          </div>

        </div>
      ) : (
        <div style={{ padding: '16px 14px', color: 'var(--dim)', fontSize: 12 }}>No inputs available.</div>
      )}
    </div>
  )
}
