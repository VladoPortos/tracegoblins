import { useEffect, useRef } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { EditorState } from '@codemirror/state'
import { EditorView, lineNumbers } from '@codemirror/view'
import { syntaxHighlighting } from '@codemirror/language'
import { Glyph } from '../components/atoms/Glyph'
import { useCopied } from '../components/atoms/useCopied'
import { tgHighlight, languageFor } from './cmHighlight'

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
