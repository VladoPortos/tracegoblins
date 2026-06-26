import { useNavigate } from 'react-router'
import { useProjects } from '../api/projects'
import { PageShell } from '../components/atoms/PageShell'
import { Badge } from '../components/atoms/Badge'
import { Glyph } from '../components/atoms/Glyph'
import { EmptyState } from '../components/atoms/EmptyState'

const STATUS_LABEL: Record<string, string> = {
  unlinked: 'Not linked', pending: 'Queued', cloning: 'Cloning…', cloned: 'Cloned', error: 'Error',
}
const STATUS_BADGE: Record<string, string> = {
  unlinked: 'skipped', pending: 'changed', cloning: 'changed', cloned: 'ok', error: 'failed',
}

export function ProjectsList() {
  const nav = useNavigate()
  const projects = useProjects()
  const list = projects.data?.items ?? []

  return (
    <PageShell>
      <h1 className="h1" style={{ marginBottom: 20 }}>Projects</h1>
      {projects.isPending && <div className="muted" style={{ padding: 16 }}>Loading…</div>}
      {projects.isError && <div className="muted" style={{ padding: 16 }}>Failed to load projects.</div>}
      {!projects.isPending && list.length === 0 && (
        <div className="card">
          <EmptyState icon="folder" title="No projects yet"
            sub="Projects are mirrored from your AWX controllers when runs sync." />
        </div>
      )}
      <div className="col" style={{ gap: 10 }}>
        {list.map((p) => (
          <button key={p.id} className="card row gap2" onClick={() => nav(`/projects/${p.id}`)}
            style={{ padding: '14px 16px', alignItems: 'center', textAlign: 'left', cursor: 'pointer' }}>
            <Glyph name="folder" size={16} style={{ color: 'var(--accent)' }} />
            <div className="grow col" style={{ gap: 2 }}>
              <div className="row gap2" style={{ alignItems: 'center' }}>
                <span className="h3" style={{ fontSize: 14 }}>{p.name}</span>
                <Badge status={STATUS_BADGE[p.status] ?? 'skipped'} withLabel={false} />
                <span className="chip" style={{ fontSize: 10.5 }}>{STATUS_LABEL[p.status] ?? p.status}</span>
              </div>
              <div className="mono muted" style={{ fontSize: 11.5 }}>
                {p.controller_name ?? p.controller_id} · {p.scm_type || 'no scm'}{p.scm_branch ? ` · ${p.scm_branch}` : ''}
              </div>
            </div>
            <span className="chip" style={{ fontSize: 11 }}>{p.linked_run_count} runs</span>
          </button>
        ))}
      </div>
    </PageShell>
  )
}
