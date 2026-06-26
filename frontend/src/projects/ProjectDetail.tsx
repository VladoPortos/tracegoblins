import { useState } from 'react'
import { useParams, Link } from 'react-router'
import { useMe } from '../api/queries'
import { PageShell } from '../components/atoms/PageShell'
import { Badge } from '../components/atoms/Badge'
import { Glyph } from '../components/atoms/Glyph'
import { errorMessage } from '../api/client'
import { useProject, useProjectRuns, useCloneProject, useRefreshMirror } from '../api/projects'
import { LinkGitModal } from './LinkGitModal'
import { UploadDropzone } from './UploadDropzone'
import { FileBrowser } from './FileBrowser'

const STATUS_BADGE: Record<string, string> = {
  unlinked: 'skipped', pending: 'changed', cloning: 'changed', cloned: 'ok', error: 'failed',
}

export function ProjectDetail() {
  const { id = '' } = useParams()
  const me = useMe()
  const isAdmin = me.data?.role === 'admin'
  const project = useProject(id)
  const runs = useProjectRuns(id)
  const clone = useCloneProject(id)
  const refresh = useRefreshMirror(id)
  const [showLink, setShowLink] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  if (project.isPending) return (
    <PageShell>
      <div className="muted" style={{ padding: 16 }}>Loading…</div>
    </PageShell>
  )
  if (!project.data) return (
    <PageShell>
      <div className="muted" style={{ padding: 16 }}>Not found.</div>
    </PageShell>
  )
  const p = project.data

  async function act(fn: () => Promise<unknown>) {
    setErr(null)
    try { await fn() } catch (e) { setErr(errorMessage(e)) }
  }

  return (
    <PageShell>
      <div className="col" style={{ gap: 16 }}>
        {/* Header */}
        <div className="card col" style={{ padding: '14px 16px', gap: 10 }}>
          <div className="row gap2" style={{ alignItems: 'center', flexWrap: 'wrap' }}>
            <Glyph name="folder" size={16} style={{ color: 'var(--accent)' }} />
            <h1 className="h1" style={{ fontSize: 15, margin: 0 }}>{p.name}</h1>
            <Badge status={STATUS_BADGE[p.status] ?? 'skipped'} withLabel={false} />
            <span className="chip" style={{ fontSize: 10.5 }}>{p.status}</span>
            <div className="grow" />
            {/* Refresh mirror — available to all members */}
            <button className="btn btn-ghost sm" onClick={() => act(() => refresh.mutateAsync())}
              disabled={refresh.isPending}>
              <Glyph name="spinner" size={14} />Refresh
            </button>
            {/* Admin-only: link git settings */}
            {isAdmin && (
              <button className="btn btn-ghost sm" onClick={() => setShowLink(true)}>
                <Glyph name="settings" size={14} />Link git
              </button>
            )}
            {/* Admin-only: trigger a fresh clone/pull */}
            {isAdmin && (
              <button className="btn btn-primary sm"
                onClick={() => act(() => clone.mutateAsync())}
                disabled={clone.isPending || p.scm_type !== 'git'}>
                {/* No download glyph — chevD (chevron-down) is closest to "pull from remote" */}
                <Glyph name="chevD" size={14} />Refresh source
              </button>
            )}
          </div>
          <div className="mono muted" style={{ fontSize: 11.5 }}>
            {p.controller_name} · {p.scm_type || 'no scm'}{p.scm_branch ? ` · ${p.scm_branch}` : ''}
            {p.effective_git_url ? ` · ${p.effective_git_url}` : ''}
          </div>
          {p.last_clone_error && (
            <div style={{ fontSize: 12, color: 'var(--unreachable)' }}>Clone error: {p.last_clone_error}</div>
          )}
          {err && <div style={{ fontSize: 12, color: 'var(--unreachable)' }}>{err}</div>}
          {/* Upload drop-zone only visible to admins */}
          {isAdmin && <UploadDropzone projectId={p.id} />}
        </div>

        {/* Two columns: linked runs + file browser */}
        <div className="row gap3" style={{ alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <div className="col" style={{ gap: 8, flex: '1 1 280px', minWidth: 260 }}>
            <h3 className="h3" style={{ fontSize: 13 }}>Linked runs ({runs.data?.total ?? 0})</h3>
            <div className="col" style={{ gap: 4 }}>
              {(runs.data?.items ?? []).map((r) => (
                <Link key={r.id} to={`/runs/${r.id}/path`} className="card row gap2"
                  style={{ padding: '8px 10px', alignItems: 'center', textDecoration: 'none' }}>
                  <Badge status={r.status} withLabel={false} />
                  <span className="grow" style={{ fontSize: 12.5 }}>{r.template_name ?? r.job_id ?? r.id}</span>
                  <span className="mono dim" style={{ fontSize: 10.5 }}>{r.launched_at?.slice(0, 10) ?? ''}</span>
                </Link>
              ))}
              {runs.isPending && <div className="muted" style={{ fontSize: 12 }}>Loading runs…</div>}
              {!runs.isPending && runs.data?.items.length === 0 && (
                <div className="muted" style={{ fontSize: 12 }}>No linked runs yet.</div>
              )}
            </div>
          </div>
          <div className="col" style={{ gap: 8, flex: '2 1 360px', minWidth: 320 }}>
            <h3 className="h3" style={{ fontSize: 13 }}>Source browser</h3>
            <FileBrowser projectId={p.id} project={{ status: p.status }} runs={runs.data?.items ?? []} />
          </div>
        </div>
      </div>
      {showLink && <LinkGitModal project={p} onClose={() => setShowLink(false)} />}
    </PageShell>
  )
}
