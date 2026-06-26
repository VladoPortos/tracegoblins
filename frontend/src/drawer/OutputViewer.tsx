import { useEffect, useRef } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { EditorState } from '@codemirror/state'
import { EditorView, lineNumbers } from '@codemirror/view'
import { json } from '@codemirror/lang-json'
import { yaml } from '@codemirror/lang-yaml'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import { tags as t } from '@lezer/highlight'
import { Glyph } from '../components/atoms/Glyph'
import { useCopied } from '../components/atoms/useCopied'

function CopyBtn({ text }: { text: string }) {
  const { copied, copy } = useCopied()
  return (
    <button
      className="btn btn-ghost sm"
      onClick={() => copy(text)}
      aria-label="Copy output"
      title="Copy"
    >
      <Glyph name={copied ? 'check' : 'copy'} size={14} />{copied ? 'Copied' : 'Copy'}
    </button>
  )
}

function isJson(s: string): boolean {
  try { JSON.parse(s); return true } catch { return false }
}

// Syntax colours tuned to read on BOTH the light and dark file-viewer surface (mid-saturation
// tones). CodeMirror's language packages only PARSE — without a highlight style nothing is
// coloured, which is why YAML/JSON looked monochrome before.
const tgHighlight = HighlightStyle.define([
  { tag: t.comment, color: '#6a9a5b', fontStyle: 'italic' },
  { tag: [t.keyword, t.bool, t.null, t.atom, t.operatorKeyword], color: '#a072c4' },
  { tag: [t.string, t.special(t.string)], color: '#c7794a' },
  { tag: [t.number, t.integer, t.float], color: '#3f9f8f' },
  { tag: [t.propertyName, t.definition(t.propertyName)], color: '#2a7bd6', fontWeight: '600' },
  { tag: [t.meta, t.documentMeta, t.processingInstruction], color: '#8a8a8a' },
  { tag: t.invalid, color: '#d14' },
])

// Pick a CodeMirror language by file extension when a filename is known (the project file
// browser passes one — Ansible source is mostly YAML). With no filename (the run-log viewer)
// fall back to the JSON-or-plain heuristic so log output isn't mis-tokenized.
function languageFor(value: string, filename?: string) {
  const ext = filename?.toLowerCase().split('.').pop()
  if (ext === 'yml' || ext === 'yaml') return [yaml()]
  if (ext === 'json') return [json()]
  if (filename === undefined && isJson(value)) return [json()]
  return []
}

function CmPane({ value, filename }: { value: string; filename?: string }) {
  const host = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!host.current) return
    const lang = languageFor(value, filename)
    const view = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          lineNumbers(),
          ...lang,
          syntaxHighlighting(tgHighlight),
          EditorView.lineWrapping,
          EditorState.readOnly.of(true),
          EditorView.editable.of(false),
          EditorView.theme({
            '&': { backgroundColor: 'var(--surface-2)', color: 'var(--text)', fontSize: '12.5px' },
            '.cm-gutters': { backgroundColor: 'var(--surface-2)', color: 'var(--text-3)', border: 'none' },
            '.cm-activeLine, .cm-activeLineGutter': { backgroundColor: 'transparent' },
          }, { dark: true }),
        ],
      }),
    })
    return () => view.destroy()
  }, [value, filename])
  return <div ref={host} style={{ height: '70vh', overflow: 'auto', borderRadius: 'var(--r-md)', border: '1px solid var(--border)' }} />
}

export function OutputViewer({ open, onOpenChange, title, value, filename }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; value: string; filename?: string
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay style={{ position: 'fixed', inset: 0, background: 'var(--scrim)', zIndex: 90 }} />
        <Dialog.Content
          className="card"
          style={{ position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%,-50%)',
                   width: 'min(980px, 94vw)', maxHeight: '90vh', overflow: 'hidden', zIndex: 91, boxShadow: 'var(--shadow-3)', padding: 16 }}>
          <div className="row gap2" style={{ alignItems: 'center', marginBottom: 12 }}>
            <Dialog.Title className="h2" style={{ fontSize: 15 }}>{title}</Dialog.Title>
            <div className="grow" />
            <CopyBtn text={value} />
            <Dialog.Close asChild>
              <button className="btn icon sm btn-ghost" aria-label="Close"><Glyph name="close" size={16} /></button>
            </Dialog.Close>
          </div>
          <CmPane value={value} filename={filename} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
