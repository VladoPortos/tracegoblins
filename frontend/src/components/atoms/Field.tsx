import { useId, type InputHTMLAttributes } from 'react'
export function Field({ label, hint, id, ...rest }: { label: string; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  // Associate label↔input so Playwright get_by_label (the E2E acceptance driver) resolves.
  const autoId = useId()
  const inputId = id ?? autoId
  return (
    <div>
      <label className="field-label" htmlFor={inputId}>{label}</label>
      <input id={inputId} className="input" {...rest} />
      {hint && <div className="dim" style={{ fontSize: 11.5, marginTop: 5 }}>{hint}</div>}
    </div>
  )
}
