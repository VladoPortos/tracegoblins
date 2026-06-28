import { useEffect, useState } from 'react'
import type { PathNode, PathStatus, NodeResult } from '../api/path'
import { useNodeResults } from '../api/path'
import type { HostScopeId } from './HostScopeChip'
import { Glyph } from '../components/atoms/Glyph'

// ---------- helpers ----------

const STATUS_LABEL: Record<PathStatus, string> = {
  ok: 'OK', changed: 'Changed', failed: 'Failed',
  unreachable: 'Unreachable', skipped: 'Skipped', included: 'Included', never_run: 'Never ran',
}
const STATUS_GLYPH: Record<string, string> = {
  ok: '✓', changed: '~', failed: '✕', unreachable: '⚠', skipped: '–', included: '◌', never_run: '◌',
}
const statusVar = (s: PathStatus | string) =>
  `var(--${s === 'unreachable' ? 'failed' : s === 'never_run' ? 'skipped' : s})`

// Deep-link a fully-qualified module name to its official docs page. Derive from the RAW
// node.action only (e.g. "ansible.builtin.apt"); a short name or composed subtitle yields null
// so we never render a wrong link. Strictly namespace.collection.module (3 identifier parts).
export function moduleDocUrl(action: string | null | undefined): string | null {
  if (!action) return null
  const parts = action.split('.')
  if (parts.length !== 3 || !parts.every(p => /^[a-z0-9_]+$/i.test(p))) return null
  const [ns, coll, mod] = parts
  return `https://docs.ansible.com/ansible/latest/collections/${ns}/${coll}/${mod}_module.html`
}

function nodeGlyph(node: PathNode): string {
  if (node.type === 'role' || node.type === 'block' || node.type === 'include' || node.type === 'play') return '▣'
  if (node.type === 'loop') return '⟳'
  if (node.type === 'when') return '⎇'
  if (node.type === 'item') return '»'
  return STATUS_GLYPH[node.status] || '•'
}
function nodeGlyphColor(node: PathNode): string {
  if (node.type === 'role' || node.type === 'block' || node.type === 'include' || node.type === 'play' || node.type === 'when') return 'var(--included)'
  if (node.type === 'loop') return 'var(--changed)'
  if (node.type === 'item') return 'var(--dim)'
  return statusVar(node.status)
}

function StatusPill({ status }: { status: PathStatus | string }) {
  const cls = `badge st-${status}`
  return (
    <span className={cls}>
      <span className="dot" />
      {STATUS_LABEL[status as PathStatus] ?? status}
    </span>
  )
}

// ---------- args table ----------

type ArgRow = [string, string]

function ArgsTable({ rows }: { rows: ArgRow[] }) {
  if (!rows.length) return null
  return (
    <div>
      <div className="eyebrow" style={{ marginBottom: 7 }}>Rendered args</div>
      <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
        {rows.map(([k, v], i) => (
          <div
            key={i}
            style={{
              display: 'flex', justifyContent: 'space-between', gap: 14,
              padding: '8px 11px',
              background: i % 2 ? 'var(--surface-2)' : 'transparent',
            }}
          >
            <span className="mono" style={{ fontSize: 12, color: 'var(--dim)', fontFeatureSettings: "'zero'" }}>{k}</span>
            <span className="mono" style={{ fontSize: 12, color: 'var(--text)', fontFeatureSettings: "'zero'", textAlign: 'right', wordBreak: 'break-all' }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------- output box ----------

function OutputBox({ label, text, isFail }: { label: string; text: string; isFail: boolean }) {
  return (
    <div>
      <div className="eyebrow" style={{ marginBottom: 7 }}>{label}</div>
      <pre
        className="mono"
        style={{
          margin: 0, padding: '11px', fontSize: 12, lineHeight: 1.55,
          whiteSpace: 'pre-wrap', wordBreak: 'break-word',
          fontFeatureSettings: "'zero'",
          color: isFail ? 'var(--failed)' : 'var(--text)',
          background: 'var(--canvas)',
          border: `1px solid ${isFail ? 'var(--failed-line, var(--unreachable-line))' : 'var(--border)'}`,
          borderRadius: 8,
        }}
      >{text}</pre>
    </div>
  )
}

// ---------- timing row ----------

function TimingRow({ duration }: { duration: string }) {
  return (
    <div>
      <div className="eyebrow" style={{ marginBottom: 7 }}>Timing</div>
      <div style={{ display: 'flex', gap: 18 }}>
        <div>
          <div className="mono" style={{ fontSize: 13, color: 'var(--text)', fontFeatureSettings: "'zero'" }}>{duration}</div>
          <div style={{ fontSize: 10.5, color: 'var(--dim)', marginTop: 2 }}>duration</div>
        </div>
      </div>
    </div>
  )
}

// ---------- skip box ----------

function SkipBox({ reason }: { reason: string }) {
  return (
    <div style={{ display: 'flex', gap: 9, padding: 11, borderRadius: 8, background: 'var(--skipped-bg, rgba(130,130,130,.1))', border: '1px solid var(--skipped-line, var(--border))' }}>
      <span style={{ color: 'var(--skipped)' }}>–</span>
      <div>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>Skipped</div>
        <div className="mono" style={{ fontSize: 11.5, color: 'var(--dim)', marginTop: 3 }}>{reason}</div>
      </div>
    </div>
  )
}

// ---------- per-node detail derivation (mirrors prototype detailFor) ----------

interface Detail {
  title: string
  module: string
  status: PathStatus | string
  hostText: string
  args: ArgRow[]
  outputLabel?: string
  output?: string
  skipReason?: string
  duration?: string
}

function hostCountText(node: PathNode, hostScope: HostScopeId): string {
  if (hostScope !== 'all') return 'host: ' + hostScope
  if (node.host_count != null) return node.host_count === 1 ? '1 host' : `${node.host_count} hosts`
  return 'all hosts'
}

function detailFor(node: PathNode, iter: number, hostScope: HostScopeId, iterResult: NodeResult | null): Detail {
  if (node.never_run) {
    // FE3: a never-run ghost was never REACHED — don't present it as an evaluated when=false skip.
    const isBlock = node.type === 'role' || node.type === 'block' || node.type === 'include' || node.type === 'play'
    return {
      title: node.label,
      module: isBlock ? 'never-run block' : (node.sub ?? node.action ?? 'never-run task'),
      status: 'never_run',
      hostText: 'not on this run’s path',
      args: node.condition ? [['when', node.condition]] : [],
      outputLabel: 'Why',
      output: node.condition
        ? 'This task was never reached on this run; it is guarded by the `when:` above.'
        : 'This task is in the playbook but was never reached on this run (e.g. an earlier failure, a skipped block/include, or tag filtering).',
    }
  }
  if (node.type === 'loop') {
    const hc = node.host_count != null ? node.host_count : null
    const ic = node.item_count != null ? node.item_count : null
    const hostPart = hc != null ? (hc === 1 ? '1 host' : `${hc} hosts`) : 'hosts'
    const itemPart = ic != null ? `${ic} items` : 'items'
    return {
      title: node.label,
      module: `loop · ${node.action ?? 'task'}`,
      status: node.status,
      hostText: `${hostPart} × ${itemPart}`,
      args: [
        ['loop', ic != null ? `items (${ic})` : 'items'],
        ['name', '{{ item }}'],
      ],
      outputLabel: 'Aggregate',
      output: `${node.ok_count ?? 0} ok · ${node.fail_count ?? 0} failed\nEnter to step through every iteration.`,
      duration: node.duration_s != null ? `${node.duration_s}s` : undefined,
    }
  }

  if (node.type === 'when') {
    // Build branch summary from node data only — the real counts come from sub-node host_count fields.
    // We don't have branch counts here without additional fetches; show the condition and a generic hint.
    return {
      title: node.label || 'conditional',
      module: 'when condition',
      status: node.status,
      hostText: hostCountText(node, hostScope),
      args: [
        ['when', node.condition ?? ''],
      ],
      outputLabel: 'How it floated',
      output: hostScope === 'all'
        ? 'Multiple branches taken — select a host to see which branch it followed.'
        : `Checking which branch ${hostScope} followed.`,
      duration: node.duration_s != null ? `${node.duration_s}s` : undefined,
    }
  }

  if (node.type === 'role' || node.type === 'block' || node.type === 'include' || node.type === 'play') {
    const cc = node.child_count ?? 0
    return {
      title: node.label,
      module: `role · ${cc} tasks`,
      status: node.status,
      hostText: hostCountText(node, hostScope),
      args: [
        ['role', node.label],
        ['tasks', String(cc)],
        ['result', `${node.ok_count ?? cc} ok`],
      ],
      outputLabel: 'Summary',
      output: cc > 0
        ? `${cc} task${cc === 1 ? '' : 's'} in sub-flow. Enter to inspect.`
        : 'Enter to view the sub-flow.',
      duration: node.duration_s != null ? `${node.duration_s}s` : undefined,
    }
  }

  if (node.type === 'item') {
    // node.label already carries the item value e.g. `= "nginx"`; keep the leading `=`.
    // item_value from nodeResults gives the canonical rendered value for the args row.
    const itemVal = iterResult?.item_value != null ? `"${iterResult.item_value}"` : node.label.replace(/^=\s*/, '')
    return {
      title: `item ${node.label}`,
      module: 'loop variable',
      status: iterResult?.status ?? node.status,
      hostText: `iteration ${iter + 1}${node.item_count != null ? ` / ${node.item_count}` : ''}`,
      args: [
        ['item', itemVal],
        ['index', String(iterResult?.item_index ?? iter)],
      ],
      duration: undefined,
    }
  }

  if (node.type === 'result') {
    const status = iterResult?.status ?? node.status
    const isFail = status === 'failed' || status === 'unreachable'
    return {
      title: 'result',
      module: node.action ?? (node.sub ?? 'task'),
      status,
      hostText: `iteration ${iter + 1}`,
      outputLabel: isFail ? 'Error' : 'Output',
      output: iterResult?.output ?? undefined,
      duration: iterResult?.duration_s != null ? `${iterResult.duration_s}s` : undefined,
      args: [],
    }
  }

  // generic task
  const isFail = node.status === 'failed' || node.status === 'unreachable'
  const module = node.action ?? (node.sub ? `ansible.builtin.${node.sub}` : 'task')

  // Output: for failed tasks show a generic message (real output comes from NodeResults in future);
  // for ok/changed tasks summarise the host count. No hardcoded node IDs or host names.
  let output: string | undefined
  if (isFail) {
    const fc = node.fail_count
    output = fc != null && fc > 0 ? `Task failed on ${fc} host${fc === 1 ? '' : 's'}.` : 'Task failed.'
  } else if (node.status !== 'skipped') {
    const hc = node.host_count
    output = hc != null ? `ok: ${hc} host${hc === 1 ? '' : 's'}` : undefined
  }

  const skipReason = node.status === 'skipped' ? (node.condition ? `when: ${node.condition}` : "Conditional 'when' evaluated to false") : undefined

  return {
    title: node.label,
    module,
    status: node.status,
    hostText: hostCountText(node, hostScope),
    args: node.sub ? [['module', node.sub]] : [],
    outputLabel: isFail ? 'Error' : 'Result',
    output,
    skipReason,
    duration: node.duration_s != null ? `${node.duration_s}s` : undefined,
  }
}

// ---------- tab button ----------

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '7px 12px', fontSize: 12, fontWeight: 600,
        color: active ? 'var(--text)' : 'var(--dim)',
        background: 'transparent', border: 'none',
        borderBottom: `2px solid ${active ? 'var(--flow)' : 'transparent'}`,
        cursor: 'pointer',
        fontFamily: "'IBM Plex Sans', sans-serif",
      }}
    >
      {children}
    </button>
  )
}

// ---------- main component ----------

export interface PathDrawerProps {
  runId: string
  node: PathNode
  iter: number
  hostScope: HostScopeId
  reduced: boolean
  onClose: () => void
  onViewSource?: (node: PathNode) => void
}

// ---------- code tab ----------

function CodeTab({ node, args, onViewSource }: { node: PathNode; args: ArgRow[]; onViewSource?: (n: PathNode) => void }) {
  if (!node.task_path && args.length === 0) {
    return <div className="mono" style={{ fontSize: 12, color: 'var(--dim)' }}>No source path for this node.</div>
  }
  return (
    <div className="col" style={{ gap: 14 }}>
      {node.task_path && (
        <div>
          <div className="eyebrow" style={{ marginBottom: 7 }}>Source path</div>
          <div className="mono" data-testid="code-tab-path" style={{
            fontSize: 12, color: 'var(--text)', fontFeatureSettings: "'zero'", padding: '9px 12px',
            borderRadius: 8, background: 'var(--canvas)', border: '1px solid var(--border)', wordBreak: 'break-all' }}>
            {node.task_path}
          </div>
        </div>
      )}
      {args.length > 0 && (
        <ArgsTable rows={args} />
      )}
      {node.task_path && onViewSource && (
        <button data-testid="view-source-btn" className="btn sm"
                onClick={() => onViewSource(node)}
                style={{ alignSelf: 'flex-start', color: 'var(--flow)', borderColor: 'var(--flow-line, var(--border))' }}>
          ⤢ View source
        </button>
      )}
    </div>
  )
}

export function PathDrawer({ runId, node, iter, hostScope, reduced, onClose, onViewSource }: PathDrawerProps) {
  // Loop leaves (item/result) carry per-iteration detail; fetch via the data seam.
  // Their ids are synthetic ("item"/"result"), so query the REAL loop node_id carried in
  // result_node_id (FE2) — otherwise no RunNodeResult matches and the output never renders.
  // Pass offset=iter&limit=1 so the API returns exactly the result for this iteration.
  const isLoopLeaf = node.type === 'result' || node.type === 'item'
  const resultsId = node.result_node_id ?? node.id
  const nodeResults = useNodeResults(runId, resultsId, { offset: iter, limit: 1 }, isLoopLeaf)
  const iterResult = nodeResults.data?.results?.[0] ?? null

  const d = detailFor(node, iter, hostScope, iterResult)
  const docUrl = moduleDocUrl(node.action)
  const glyph = nodeGlyph(node)
  const glyphColor = nodeGlyphColor(node)
  const isFail = d.status === 'failed' || d.status === 'unreachable'

  // Tab state: reset to 'details' whenever a new node is selected
  const [drawerTab, setDrawerTab] = useState<'details' | 'code'>('details')
  useEffect(() => { setDrawerTab('details') }, [node.id])

  // Esc to close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      data-testid="path-drawer"
      style={{
        position: 'absolute', top: 0, right: 0, bottom: 0, width: 392,
        background: 'var(--surface)',
        borderLeft: '1px solid var(--border)',
        boxShadow: '-12px 0 44px rgba(0,0,0,.34)',
        display: 'flex', flexDirection: 'column',
        zIndex: 20,
        animation: reduced ? 'none' : 'drawerIn .22s cubic-bezier(.2,.7,.3,1) both',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '16px 16px 12px', borderBottom: '1px solid var(--border)' }}>
        <span className="mono" style={{ fontSize: 17, fontWeight: 600, color: glyphColor, flex: '0 0 auto', marginTop: 1 }}>{glyph}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="mono" style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', fontFeatureSettings: "'zero'", wordBreak: 'break-word' }}>
            {d.title}
          </div>
          <div className="mono" style={{ fontSize: 11.5, color: 'var(--dim)', marginTop: 2, display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' }}>
            <span>{d.module}</span>
            {docUrl && (
              <a
                data-testid="module-doc-link"
                href={docUrl}
                target="_blank"
                rel="noopener noreferrer nofollow"
                title="Open module documentation"
                style={{ color: 'var(--flow)', textDecoration: 'none', fontSize: 11, flex: '0 0 auto' }}
              >docs ↗</a>
            )}
          </div>
        </div>
        <button
          className="btn icon sm btn-ghost"
          onClick={onClose}
          aria-label="Close drawer"
          style={{ flex: '0 0 auto' }}
        >
          <Glyph name="close" size={16} />
        </button>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 2, padding: '8px 12px 0', borderBottom: '1px solid var(--border)' }}>
        <TabBtn active={drawerTab === 'details'} onClick={() => setDrawerTab('details')}>Details</TabBtn>
        <TabBtn active={drawerTab === 'code'} onClick={() => setDrawerTab('code')}>&lt;/&gt; Code</TabBtn>
      </div>

      {/* Tab body */}
      <div className="scroll grow" style={{ padding: 16 }}>
        {drawerTab === 'details' ? (
          <div className="col" style={{ gap: 16 }}>

            {/* Status pill + host text */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <StatusPill status={d.status} />
              <span className="mono" style={{ fontSize: 11.5, color: 'var(--dim)' }}>{d.hostText}</span>
            </div>

            {/* Args table */}
            {d.args.length > 0 && <ArgsTable rows={d.args} />}

            {/* Output / error box */}
            {d.output && (
              <OutputBox
                label={d.outputLabel ?? (isFail ? 'Error' : 'Output')}
                text={d.output}
                isFail={isFail}
              />
            )}

            {/* Skip reason */}
            {d.skipReason && <SkipBox reason={d.skipReason} />}

            {/* Timing */}
            {d.duration && <TimingRow duration={d.duration} />}

          </div>
        ) : (
          <CodeTab node={node} args={d.args} onViewSource={onViewSource} />
        )}
      </div>
    </div>
  )
}
