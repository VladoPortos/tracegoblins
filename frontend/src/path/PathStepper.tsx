// frontend/src/path/PathStepper.tsx
// Floating loop stepper rendered over the canvas when view.type === 'loop'.

interface PathStepperProps {
  iter: number
  total: number
  onStep: (dir: 1 | -1) => void
}

export function PathStepper({ iter, total, onStep }: PathStepperProps) {
  const label = `${iter + 1} / ${total}`

  return (
    <div
      data-testid="path-stepper"
      style={{
        position: 'absolute',
        left: '50%',
        bottom: 18,
        transform: 'translateX(-50%)',
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '8px 10px',
        background: 'var(--panel-glass)',
        border: '1px solid var(--border)',
        borderRadius: 12,
        backdropFilter: 'blur(8px)',
        boxShadow: '0 10px 34px rgba(0,0,0,.35)',
        zIndex: 4,
      }}
    >
      <button
        aria-label="Previous iteration"
        onClick={() => onStep(-1)}
        disabled={iter === 0}
        style={{
          width: 32,
          height: 32,
          borderRadius: 8,
          background: 'var(--node-2)',
          border: '1px solid var(--border)',
          color: 'var(--text)',
          cursor: iter === 0 ? 'default' : 'pointer',
          fontSize: 15,
          opacity: iter === 0 ? 0.4 : 1,
        }}
      >
        ‹
      </button>

      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 2,
          minWidth: 80,
        }}
      >
        <span
          style={{
            fontFamily: "'IBM Plex Mono'",
            fontSize: 13,
            fontWeight: 600,
            color: 'var(--text)',
            fontFeatureSettings: '"zero"',
            letterSpacing: '0.02em',
          }}
        >
          {label}
        </span>
      </div>

      <button
        aria-label="Next iteration"
        onClick={() => onStep(1)}
        disabled={iter === total - 1}
        style={{
          width: 32,
          height: 32,
          borderRadius: 8,
          background: 'var(--node-2)',
          border: '1px solid var(--border)',
          color: 'var(--text)',
          cursor: iter === total - 1 ? 'default' : 'pointer',
          fontSize: 15,
          opacity: iter === total - 1 ? 0.4 : 1,
        }}
      >
        ›
      </button>
    </div>
  )
}
