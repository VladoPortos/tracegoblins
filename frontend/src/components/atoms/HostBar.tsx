// HostBar.tsx — recap may be a HostRecap-ish or a {ok,changed,skipped,unreachable,failed} stats object
export function HostBar({ recap, height = 8, rounded = true }:
  { recap: Record<string, number>; height?: number; rounded?: boolean }) {
  const order = ['ok', 'changed', 'skipped', 'included', 'unreachable', 'failed'] as const
  const total = order.reduce((a, k) => a + (recap[k] || 0), 0) || 1
  return (
    <div className="row" style={{ height, width: '100%', borderRadius: rounded ? 999 : 3, overflow: 'hidden', background: 'var(--surface-3)' }}>
      {order.map((k) => (recap[k] || 0) > 0 ? (
        <div key={k} className={'st-' + k} title={`${k}: ${recap[k]}`}
          style={{ width: (recap[k] / total * 100) + '%', height: '100%', background: 'var(--c)' }} />
      ) : null)}
    </div>
  )
}
