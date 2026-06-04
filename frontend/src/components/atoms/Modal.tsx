import * as Dialog from '@radix-ui/react-dialog'
import type { ReactNode } from 'react'

export function Modal({ open, onOpenChange, title, children, width = 460 }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; children: ReactNode; width?: number
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay style={{ position: 'fixed', inset: 0, background: 'var(--scrim)', zIndex: 80 }} />
        <Dialog.Content
          className="card"
          style={{ position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%,-50%)',
                   width, maxWidth: '92vw', maxHeight: '88vh', overflow: 'auto', zIndex: 81, boxShadow: 'var(--shadow-3)', padding: 20 }}>
          <Dialog.Title className="h2" style={{ marginBottom: 14 }}>{title}</Dialog.Title>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
