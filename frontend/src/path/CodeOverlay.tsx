import { useEffect, useRef } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { EditorState, RangeSetBuilder } from '@codemirror/state'
import { EditorView, lineNumbers, Decoration } from '@codemirror/view'
import { syntaxHighlighting } from '@codemirror/language'
import { Glyph } from '../components/atoms/Glyph'
import { tgHighlight, languageFor } from '../drawer/cmHighlight'
import { useNodeSource } from '../api/path'
import type { PathNode, NodeSource } from '../api/path'

const runLine = Decoration.line({ attributes: { style: 'background: rgba(192,140,255,.16); box-shadow: inset 3px 0 0 var(--flow);' } })
const deadLine = Decoration.line({ attributes: { style: 'opacity:.5; filter:grayscale(.7);' } })

function lineDecos(view: EditorView, executed: number[], neverRun: number[]) {
  const exec = new Set(executed), dead = new Set(neverRun)
  const b = new RangeSetBuilder<Decoration>()
  for (let ln = 1; ln <= view.state.doc.lines; ln++) {
    const from = view.state.doc.line(ln).from
    if (dead.has(ln)) b.add(from, from, deadLine)
    else if (exec.has(ln)) b.add(from, from, runLine)
  }
  return b.finish()
}

function CodePane({ value, filename, executed, neverRun, focus }: {
  value: string; filename?: string; executed: number[]; neverRun: number[]; focus: number | null
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
          EditorView.decorations.of((v) => lineDecos(v, executed, neverRun)),
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
  }, [value, filename, executed, neverRun, focus])
  return <div ref={host} style={{ flex: 1, minHeight: 0, overflow: 'auto', borderRadius: 'var(--r-md)', border: '1px solid var(--border)' }} />
}

function ResolvedRow({ r }: { r: NodeSource['resolved'][number] }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '4px 0' }}>
      <span className="mono dim" style={{ fontSize: 12 }}>{r.key}</span>
      {r.recorded
        ? <span className="mono" style={{ fontSize: 12, color: 'var(--ok, var(--changed))', textAlign: 'right', wordBreak: 'break-all' }}>
            {typeof r.value === 'string' ? `"${r.value}"` : JSON.stringify(r.value)}
            {r.host ? <span className="dim"> · {r.host}</span> : null}
          </span>
        : <span className="mono dim" style={{ fontSize: 12, fontStyle: 'italic', textAlign: 'right' }}>(not recorded)</span>}
    </div>
  )
}

function ResolvedSidebar({ d }: { d: NodeSource }) {
  return (
    <div data-testid="resolved-sidebar" style={{
      flex: '0 0 300px', overflow: 'auto', background: 'var(--surface-2)',
      border: '1px solid var(--border)', borderRadius: 'var(--r-md)', padding: 12 }}>
      <div className="eyebrow" style={{ marginBottom: 8 }}>Resolved · this run</div>
      {d.resolved.length === 0 && <div className="dim mono" style={{ fontSize: 12 }}>No recorded values.</div>}
      {d.resolved.map((r, i) => (
        <ResolvedRow key={i} r={r} />
      ))}
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
              {d?.path ?? node.label}{d?.ref ? <span className="dim">  @ {d.ref.slice(0, 8)}</span> : null}
            </Dialog.Title>
            <div className="grow" />
            <Dialog.Close asChild>
              <button className="btn icon sm btn-ghost" aria-label="Close"><Glyph name="close" size={16} /></button>
            </Dialog.Close>
          </div>
          {src.isPending && <div className="dim mono" style={{ padding: 24 }}>Loading source…</div>}
          {d && d.unavailable && (
            <div data-testid="code-overlay-unavailable" className="dim mono" style={{ padding: 24 }}>
              {UNAVAILABLE_MSG[d.unavailable] ?? 'Source unavailable.'}
            </div>
          )}
          {d && !d.unavailable && d.content != null && (
            <div style={{ display: 'flex', gap: 12, flex: 1, minHeight: 0 }}>
              <CodePane value={d.content} filename={d.path ?? undefined}
                        executed={d.executed_lines} neverRun={d.never_run_lines} focus={d.focus_line} />
              <ResolvedSidebar d={d} />
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
