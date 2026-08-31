import { useEffect, useState } from 'react'
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
  const refreshMirror = useRefreshMirror(id)
  const [showLink, setShowLink] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  // Tracks a clone we kicked off, so the "pending" status (also used right after Link git)
  // only reads as in-progress when WE triggered it. Reset once the clone reaches a terminal state.
  const [cloneTriggered, setCloneTriggered] = useState(false)
  const status = project.data?.status
  useEffect(() => {
    if (status === 'cloned' || status === 'error') setCloneTriggered(false)
  }, [status])

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
  // Live clone state: actively cloning, or a clone WE triggered that's still queued (pending).
  const cloneInProgress = clone.isPending || p.status === 'cloning' || (cloneTriggered && p.status === 'pending')

  // Refresh source = trigger a clone/fetch. Clears any prior error immediately and marks the
  // clone in-flight so the UI shows live "Cloning…" until it converges (poll-driven).
  async function doClone() {
    setErr(null)
    setCloneTriggered(true)
    try { await clone.mutateAsync() } catch (e) { setErr(errorMessage(e)); setCloneTriggered(false) }
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
            <button
              className="btn btn-ghost sm"
              onClick={() => {
                setErr(null)
                refreshMirror.mutate(undefined, { onError: (e) => setErr(errorMessage(e)) })
              }}
              disabled={refreshMirror.isPending}
            >
              <Glyph name={refreshMirror.isPending ? 'spinner' : 'chevD'} size={14} />
              {refreshMirror.isPending ? 'Refreshing metadata…' : 'Refresh metadata'}
            </button>
            {/* Admin-only: link git (saving auto-starts the clone) */}
            {isAdmin && (
              <button className="btn btn-ghost sm" onClick={() => setShowLink(true)}>
                <Glyph name="settings" size={14} />Link git
              </button>
            )}
            {/* Admin-only: re-pull an already-linked repo (fetch new revisions). Hidden until linked. */}
            {isAdmin && p.git_auth_type !== null && (
              <button className="btn btn-ghost sm"
                onClick={doClone}
                disabled={cloneInProgress || p.scm_type !== 'git'}>
                <Glyph name={cloneInProgress ? 'spinner' : 'chevD'} size={14} />
                {cloneInProgress ? 'Cloning…' : 'Refresh source'}
              </button>
            )}
          </div>
          <div className="mono muted" style={{ fontSize: 11.5 }}>
            {p.controller_name} · {p.scm_type || 'no scm'}{p.scm_branch ? ` · ${p.scm_branch}` : ''}
            {p.effective_git_url ? ` · ${p.effective_git_url}` : ''}
          </div>
          {/* Live clone status — wipes the stale error while a new attempt is in flight */}
          {cloneInProgress && (
            <div className="row gap2" style={{ fontSize: 12, color: 'var(--accent)', alignItems: 'center',
              animation: 'pulse 1.4s ease-in-out infinite' }}>
              <Glyph name="spinner" size={13} />
              Cloning source{p.effective_git_url ? ` from ${p.effective_git_url}` : ''}…
            </div>
          )}
          {!cloneInProgress && p.status === 'error' && p.last_clone_error && (
            <div style={{ fontSize: 12, color: 'var(--unreachable)', padding: '8px 10px', borderRadius: 6,
              background: 'var(--surface-2)', border: '1px solid color-mix(in srgb, var(--unreachable) 50%, transparent)' }}>
              <strong>Clone failed:</strong> {p.last_clone_error}
            </div>
          )}
          {!cloneInProgress && p.status === 'cloned' && (
            <div style={{ fontSize: 12, color: 'var(--ok)' }}>
              ✓ Source cloned{p.clone_size_bytes ? ` · ${(p.clone_size_bytes / 1048576).toFixed(1)} MB` : ''}
            </div>
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
      {showLink && (
        <LinkGitModal project={p} onClose={() => setShowLink(false)}
          onSaved={() => { void doClone() }} />
      )}
    </PageShell>
  )
}
