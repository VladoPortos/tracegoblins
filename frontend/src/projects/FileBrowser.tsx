import { useState } from 'react'
import { Glyph } from '../components/atoms/Glyph'
import { OutputViewer } from '../drawer/OutputViewer'
import { useProjectTree, fetchProjectBlob } from '../api/projects'
import type { RunCard } from '../api/client'

interface RefOption { value: string; label: string }

function refOptions(project: { status: string }, runs: RunCard[]): RefOption[] {
  const opts: RefOption[] = []
  if (project.status === 'cloned') opts.push({ value: 'HEAD', label: 'Default branch (HEAD)' })
  // distinct scm_revisions among linked runs, newest first, labelled template · date · short-sha
  const seen = new Set<string>()
  for (const r of runs) {
    const rev = r.scm_revision
    if (!rev || seen.has(rev)) continue
    seen.add(rev)
    const when = r.launched_at ?? r.log_time ?? r.created_at
    const date = when ? new Date(when).toLocaleDateString() : ''
    opts.push({ value: rev, label: `${r.template_name ?? 'run'} · ${date} · ${rev.slice(0, 8)}` })
  }
  opts.push({ value: 'uploads', label: 'Uploaded files' })
  return opts
}

function TreeLevel({ projectId, gitRef, path, onOpen }: {
  projectId: string; gitRef: string; path: string; onOpen: (p: string) => void
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const tree = useProjectTree(projectId, gitRef, path)
  if (tree.isPending) return <div className="muted" style={{ fontSize: 12, padding: '4px 8px' }}>Loading…</div>
  if (tree.isError) return <div style={{ fontSize: 12, color: 'var(--unreachable)', padding: '4px 8px' }}>Not available at this ref.</div>
  return (
    <div className="col" style={{ gap: 1 }}>
      {tree.data!.entries.map((e) => {
        const full = path ? `${path}/${e.name}` : e.name
        const isOpen = expanded.has(full)
        return (
          <div key={full} className="col">
            <button className="btn btn-ghost sm" style={{ justifyContent: 'flex-start', gap: 6 }}
              onClick={() => {
                if (e.type === 'tree') {
                  setExpanded((prev) => { const n = new Set(prev); n.has(full) ? n.delete(full) : n.add(full); return n })
                } else { onOpen(full) }
              }}>
              {/* chevD / chevR for expand/collapse; rows as a file icon substitute */}
              <Glyph name={e.type === 'tree' ? (isOpen ? 'chevD' : 'chevR') : 'rows'} size={13} />
              {e.name}
            </button>
            {e.type === 'tree' && isOpen && (
              <div style={{ marginLeft: 16 }}>
                <TreeLevel projectId={projectId} gitRef={gitRef} path={full} onOpen={onOpen} />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export function FileBrowser({ projectId, project, runs }: {
  projectId: string; project: { status: string }; runs: RunCard[]
}) {
  const opts = refOptions(project, runs)
  const [gitRef, setGitRef] = useState<string>(opts[0]?.value ?? 'HEAD')
  const [viewer, setViewer] = useState<{ title: string; value: string } | null>(null)

  async function open(path: string) {
    try {
      const blob = await fetchProjectBlob(projectId, gitRef, path)
      const value = blob.too_large ? '[file too large to display]'
        : blob.binary ? '[binary file]' : (blob.content ?? '')
      setViewer({ title: path, value })
    } catch {
      setViewer({ title: path, value: '[could not load file]' })
    }
  }

  if (opts.length === 0) return <div className="muted">Nothing to browse yet.</div>
  return (
    <div className="col" style={{ gap: 10 }}>
      <select className="input" value={gitRef} onChange={(e) => setGitRef(e.target.value)} aria-label="Source revision">
        {opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <div className="card" style={{ padding: 8, maxHeight: '52vh', overflow: 'auto' }}>
        <TreeLevel projectId={projectId} gitRef={gitRef} path="" onOpen={open} />
      </div>
      {viewer && (
        <OutputViewer open onOpenChange={(o) => { if (!o) setViewer(null) }}
          title={viewer.title} value={viewer.value} />
      )}
    </div>
  )
}
