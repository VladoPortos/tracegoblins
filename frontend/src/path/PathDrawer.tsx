import { useEffect } from 'react'
import type { PathNode, PathStatus } from '../api/path'
import { loopResults } from '../api/pathFixture'
import type { HostScopeId } from './HostScopeChip'
import { Glyph } from '../components/atoms/Glyph'

// ---------- helpers ----------

const STATUS_LABEL: Record<PathStatus, string> = {
  ok: 'OK', changed: 'Changed', failed: 'Failed',
  unreachable: 'Unreachable', skipped: 'Skipped', included: 'Included',
}
const STATUS_GLYPH: Record<string, string> = {
  ok: '✓', changed: '~', failed: '✕', unreachable: '⚠', skipped: '–', included: '◌',
}
const statusVar = (s: PathStatus | string) =>
  `var(--${s === 'unreachable' ? 'failed' : s})`

function nodeGlyph(node: PathNode): string {
  if (node.type === 'role' || node.type === 'block' || node.type === 'include') return '▣'
  if (node.type === 'loop') return '⟳'
  if (node.type === 'when') return '⎇'
  if (node.type === 'item') return '»'
  return STATUS_GLYPH[node.status] || '•'
}
function nodeGlyphColor(node: PathNode): string {
  if (node.type === 'role' || node.type === 'block' || node.type === 'include' || node.type === 'when') return 'var(--included)'
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

function detailFor(node: PathNode, iter: number, hostScope: HostScopeId): Detail {
  const hostScopeText = hostScope === 'all' ? 'all 50 hosts' : 'host: ' + hostScope

  if (node.type === 'loop') {
    return {
      title: node.label,
      module: `loop · ${node.action ?? 'ansible.builtin.package'}`,
      status: 'changed',
      hostText: `${node.host_count ?? 50} hosts × ${node.item_count ?? 50} items`,
      args: [
        ['loop', `packages (${node.item_count ?? 50})`],
        ['name', '{{ item }}'],
        ['state', 'present'],
      ],
      outputLabel: 'Aggregate',
      output: `${node.ok_count ?? 0} ok · ${node.fail_count ?? 0} failed\nEnter to step through every iteration.`,
      duration: node.duration_s != null ? `${node.duration_s}s` : undefined,
    }
  }

  if (node.type === 'when') {
    return {
      title: 'OS family decision',
      module: 'when condition',
      status: node.status,
      hostText: hostScopeText,
      args: [
        ['when', node.condition ?? ''],
        ['→ true', '49 hosts → yum repo'],
        ['→ false', '1 host → choco repo'],
      ],
      outputLabel: 'How it floated',
      output: hostScope === 'all'
        ? 'Both branches taken (RedHat ×49, Windows ×1).'
        : hostScope === 'win-01'
          ? 'win-01 is Windows → false → choco branch.'
          : `${hostScope} is RedHat → true → yum branch.`,
      duration: node.duration_s != null ? `${node.duration_s}s` : '0.1s',
    }
  }

  if (node.type === 'role' || node.type === 'block' || node.type === 'include') {
    return {
      title: node.label,
      module: `role · ${node.child_count ?? 0} tasks`,
      status: node.status,
      hostText: `${node.host_count ?? 50} hosts`,
      args: [
        ['role', node.label],
        ['tasks', String(node.child_count ?? 0)],
        ['result', `${(node.ok_count ?? node.child_count ?? 0)} ok`],
      ],
      outputLabel: 'Summary',
      output: `All ${node.child_count ?? 0} tasks completed. Enter to view the sub-flow.`,
      duration: node.duration_s != null ? `${node.duration_s}s` : undefined,
    }
  }

  if (node.type === 'item') {
    // label carries the item value e.g. `= "nginx"`
    const itemVal = node.label.replace(/^=\s*/, '')
    return {
      title: `item ${itemVal}`,
      module: 'loop variable',
      status: 'ok',
      hostText: `iteration ${iter + 1} / ${node.item_count ?? 50}`,
      args: [
        ['item', itemVal],
        ['index', String(iter)],
      ],
      duration: undefined,
    }
  }

  if (node.type === 'result') {
    const results = loopResults()
    const res = results[iter] ?? results[0]
    const isFail = res.status === 'failed' || res.status === 'unreachable'
    return {
      title: 'result',
      module: node.action ?? 'ansible.builtin.package',
      status: res.status,
      hostText: `iteration ${iter + 1} / 50`,
      outputLabel: isFail ? 'Error' : 'Output',
      output: res.output ?? undefined,
      duration: res.duration_s != null ? `${res.duration_s}s` : undefined,
      args: [],
    }
  }

  // generic task
  const isFail = node.status === 'failed' || node.status === 'unreachable'
  const module = node.action ?? (node.sub ? `ansible.builtin.${node.sub}` : 'task')
  const hostText = node.host_count != null
    ? (hostScope === 'all' ? `${node.host_count} hosts` : '1 host')
    : hostScopeText

  let output: string | undefined
  if (node.id === 'restart') {
    output = 'web-13: FAILED — Job for app.service failed; see "systemctl status app.service".'
  } else if (isFail) {
    output = 'Task failed on 1 host.'
  } else {
    output = `ok: ${node.host_count ?? 50} hosts`
  }

  const skipReason = node.status === 'skipped' ? "Conditional 'when' evaluated to false" : undefined

  return {
    title: node.label,
    module,
    status: node.status,
    hostText,
    args: [
      ['module', node.sub ?? module],
      ['state', 'present'],
    ],
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
}

export function PathDrawer({ node, iter, hostScope, reduced, onClose }: PathDrawerProps) {
  const d = detailFor(node, iter, hostScope)
  const glyph = nodeGlyph(node)
  const glyphColor = nodeGlyphColor(node)
  const isFail = d.status === 'failed' || d.status === 'unreachable'

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
          <div className="mono" style={{ fontSize: 11.5, color: 'var(--dim)', marginTop: 2 }}>{d.module}</div>
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
        {/* Details tab is always active in Task 11; Code tab is Task 12 */}
        <TabBtn active={true} onClick={() => {}}>Details</TabBtn>
        <TabBtn active={false} onClick={() => {}}>&lt;/&gt; Code</TabBtn>
      </div>

      {/* Details body */}
      <div className="scroll grow" style={{ padding: 16 }}>
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
      </div>
    </div>
  )
}
