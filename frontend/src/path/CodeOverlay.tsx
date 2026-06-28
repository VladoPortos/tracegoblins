import { useEffect, useRef, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { EditorState, RangeSetBuilder } from '@codemirror/state'
import { EditorView, lineNumbers, Decoration } from '@codemirror/view'
import { syntaxHighlighting } from '@codemirror/language'
import { Glyph } from '../components/atoms/Glyph'
import { tgHighlight, languageFor } from '../drawer/cmHighlight'
import { useNodeSource } from '../api/path'
import type { PathNode, NodeSource } from '../api/path'

const runLine = Decoration.line({ attributes: { style: 'background: rgba(192,140,255,.16); box-shadow: inset 3px 0 0 var(--flow);' } })
const skipLine = Decoration.line({ attributes: { style: 'background: var(--skipped-bg); box-shadow: inset 3px 0 0 var(--skipped);' } })
const deadLine = Decoration.line({ attributes: { style: 'opacity:.5; filter:grayscale(.7);' } })
const focusLine = Decoration.line({ attributes: { style: 'background: rgba(192,140,255,.10); box-shadow: inset 4px 0 0 var(--flow), inset 0 -1px 0 var(--flow), inset 0 1px 0 var(--flow);' } })

function lineDecos(view: EditorView, executed: number[], skipped: number[], neverRun: number[], focus: number | null) {
  const exec = new Set(executed), skip = new Set(skipped), dead = new Set(neverRun)
  const b = new RangeSetBuilder<Decoration>()
  for (let ln = 1; ln <= view.state.doc.lines; ln++) {
    const from = view.state.doc.line(ln).from
    if (ln === focus) b.add(from, from, focusLine)   // focus wins → the clicked task stays identifiable (OV7)
    else if (dead.has(ln)) b.add(from, from, deadLine)
    else if (skip.has(ln)) b.add(from, from, skipLine)  // reached-and-skipped (OV4) — distinct from executed
    else if (exec.has(ln)) b.add(from, from, runLine)
  }
  return b.finish()
}

function CodePane({ value, filename, executed, skipped, neverRun, focus }: {
  value: string; filename?: string; executed: number[]; skipped: number[]; neverRun: number[]; focus: number | null
}) {
  const host = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!host.current) return
    const view = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          lineNumbers(), ...languageFor(value, filename), syntaxHighlighting(tgHighlight),
          EditorView.lineWrapping, EditorState.readOnly.of(true), EditorView.editable.of(false),
          EditorView.decorations.of((v) => lineDecos(v, executed, skipped, neverRun, focus)),
          EditorView.theme({
            '&': { backgroundColor: 'var(--surface-2)', color: 'var(--text)', fontSize: '12.5px' },
            '.cm-gutters': { backgroundColor: 'var(--surface-2)', color: 'var(--text-3)', border: 'none' },
            '.cm-activeLine, .cm-activeLineGutter': { backgroundColor: 'transparent' },
          }, { dark: true }),
        ],
      }),
    })
    if (focus != null && focus >= 1 && focus <= view.state.doc.lines) {
      const pos = view.state.doc.line(focus).from
      view.dispatch({ selection: { anchor: pos }, effects: EditorView.scrollIntoView(pos, { y: 'center' }) })
    }
    return () => view.destroy()
  }, [value, filename, executed, skipped, neverRun, focus])
  return <div ref={host} style={{ flex: 1, minHeight: 0, overflow: 'auto', borderRadius: 'var(--r-md)', border: '1px solid var(--border)' }} />
}

const SOURCE_LABEL: Record<string, string> = {
  module_args: 'arg', set_fact: 'fact', debug: 'debug', task_args: 'arg', item: 'item', when: 'when',
}

function ResolvedRow({ r }: { r: NodeSource['resolved'][number] }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '4px 0' }}>
      <span className="mono dim" style={{ fontSize: 12, display: 'flex', gap: 5, alignItems: 'baseline', minWidth: 0 }}>
        <span className="truncate">{r.key}</span>
        <span style={{ fontSize: 9.5, opacity: 0.6, textTransform: 'uppercase', letterSpacing: '.04em', flex: '0 0 auto' }}>{SOURCE_LABEL[r.source] ?? r.source}</span>
      </span>
      {r.recorded
        ? <span className="mono" style={{ fontSize: 12, color: r.value == null ? 'var(--dim)' : 'var(--ok, var(--changed))', textAlign: 'right', wordBreak: 'break-all' }}>
            {r.expr ? <span style={{ color: 'var(--included)', opacity: 0.85 }}>{r.expr} → </span> : null}
            {r.value == null ? 'null' : typeof r.value === 'string' ? `"${r.value}"` : JSON.stringify(r.value)}
            {r.host ? <span className="dim"> · {r.host}</span> : null}
          </span>
        : <span className="mono dim" style={{ fontSize: 12, fontStyle: 'italic', textAlign: 'right' }}>
            {r.expr ? <span style={{ color: 'var(--included)' }}>{r.expr}</span> : null} (not recorded)
          </span>}
    </div>
  )
}

function ResolvedSidebar({ d }: { d: NodeSource }) {
  const [showDefaults, setShowDefaults] = useState(false)
  // Real module_args dump many null/default plumbing params; hide them by default so the values the
  // user actually set stay visible (VV-B). A null is a "default" only for the noisy module_args source.
  const isDefault = (r: NodeSource['resolved'][number]) => r.source === 'module_args' && r.value == null
  const defaults = d.resolved.filter(isDefault)
  const shown = showDefaults ? d.resolved : d.resolved.filter((r) => !isDefault(r))
  return (
    <div data-testid="resolved-sidebar" style={{
      flex: '0 0 300px', overflow: 'auto', background: 'var(--surface-2)',
      border: '1px solid var(--border)', borderRadius: 'var(--r-md)', padding: 12 }}>
      <div className="eyebrow" style={{ marginBottom: 8 }}>Resolved · this run</div>
      {d.hosts.length > 0 && (
        <div className="mono dim" style={{ fontSize: 11, marginBottom: 8 }}>
          {d.hosts.length} host{d.hosts.length === 1 ? '' : 's'} · {d.hosts.join(', ')}
        </div>
      )}
      {d.resolved.length === 0 && <div className="dim mono" style={{ fontSize: 12 }}>No recorded values.</div>}
      {shown.map((r, i) => (
        <ResolvedRow key={i} r={r} />
      ))}
      {defaults.length > 0 && (
        <button onClick={() => setShowDefaults((v) => !v)} className="mono"
                style={{ marginTop: 8, fontSize: 11, color: 'var(--flow)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
          {showDefaults ? 'hide' : 'show'} {defaults.length} default{defaults.length === 1 ? '' : 's'}
        </button>
      )}
      {d.skipped_lines.length > 0 && (
        <>
          <div className="eyebrow" style={{ margin: '14px 0 6px' }}>Reached &amp; skipped</div>
          <div className="mono" style={{ fontSize: 12, color: 'var(--skipped)' }}>
            {d.skipped_lines.length} line{d.skipped_lines.length === 1 ? '' : 's'} · {d.skipped_lines.join(', ')}
          </div>
        </>
      )}
      {d.never_run_lines.length > 0 && (
        <>
          <div className="eyebrow" style={{ margin: '14px 0 6px' }}>Never ran</div>
          <div className="mono dim" style={{ fontSize: 12 }}>
            {d.never_run_lines.length} line{d.never_run_lines.length === 1 ? '' : 's'} · {d.never_run_lines.join(', ')}
          </div>
        </>
      )}
    </div>
  )
}

const UNAVAILABLE_MSG: Record<string, string> = {
  not_linked: 'This run has no linked project — no source to show.',
  not_cloned: 'Project source is not cloned yet. Clone it from Projects to view code.',
  revision_missing: "This run's revision isn't in the clone yet — refresh the project source.",
  no_path: 'This node has no source path (stdout-only run).',
  binary: 'The file at this revision is binary.',
  too_large: 'The file at this revision is too large to display.',
}

export function CodeOverlay({ runId, node, onClose }: { runId: string; node: PathNode; onClose: () => void }) {
  const src = useNodeSource(runId, node.id)
  const d = src.data
  return (
    <Dialog.Root open onOpenChange={(o) => { if (!o) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay style={{ position: 'fixed', inset: 0, background: 'var(--scrim)', zIndex: 90 }} />
        <Dialog.Content
          data-testid="code-overlay"
          className="card"
          style={{ position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%,-50%)',
                   width: 'min(1180px, 96vw)', height: '88vh', overflow: 'hidden', zIndex: 91,
                   boxShadow: 'var(--shadow-3)', padding: 14, display: 'flex', flexDirection: 'column' }}>
          <div className="row gap2" style={{ alignItems: 'center', marginBottom: 10 }}>
            <Dialog.Title className="mono" style={{ fontSize: 13, fontWeight: 600 }}>
              {d?.path ?? node.label}{d?.ref ? <span className="dim" style={{ marginLeft: 4 }}>@ {d.ref.slice(0, 8)}</span> : null}
            </Dialog.Title>
            <Dialog.Description style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>
              Source overlay for {d?.path ?? node.label}
            </Dialog.Description>
            <div className="grow" />
            <Dialog.Close asChild>
              <button className="btn icon sm btn-ghost" aria-label="Close"><Glyph name="close" size={16} /></button>
            </Dialog.Close>
          </div>
          {src.isPending && <div className="dim mono" style={{ padding: 24 }}>Loading source…</div>}
          {src.isError && <div className="dim mono" style={{ padding: 24 }}>Failed to load source.</div>}
          {d && d.unavailable && (
            <div data-testid="code-overlay-unavailable" className="dim mono" style={{ padding: 24 }}>
              {UNAVAILABLE_MSG[d.unavailable] ?? 'Source unavailable.'}
            </div>
          )}
          {d && d.revision_mismatch && (
            <div className="mono" style={{ marginBottom: 8, padding: '6px 10px', borderRadius: 6,
              fontSize: 11.5, color: 'var(--failed)', background: 'var(--failed-bg, var(--surface-2))',
              border: '1px solid var(--failed-line, var(--border))' }}>
              ⚠ This file may not match the run's revision — some recorded lines fall outside it.
            </div>
          )}
          {d && !d.unavailable && d.content != null && (
            <div style={{ display: 'flex', gap: 12, flex: 1, minHeight: 0 }}>
              <CodePane value={d.content} filename={d.path ?? undefined}
                        executed={d.executed_lines} skipped={d.skipped_lines}
                        neverRun={d.never_run_lines} focus={d.focus_line} />
              <ResolvedSidebar d={d} />
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
