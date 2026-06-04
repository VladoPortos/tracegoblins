import { STATUS, stCls } from './status'
export function StatusDot({ status, size = 9 }: { status: string; size?: number }) {
  const cls = (STATUS as Record<string, unknown>)[status] ? stCls(status) : 'st-ok'
  return <span className={'dot-status ' + cls} style={{ width: size, height: size }} />
}
