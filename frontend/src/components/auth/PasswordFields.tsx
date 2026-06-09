import { Field } from '../atoms/Field'

export const MIN_PASSWORD_LEN = 12  // mirrors backend MIN_PASSWORD_LEN (app/security/passwords.py)

// Client-side pre-check for the new-password forms. Returns the error message or null.
export function validateNewPassword(pw: string, confirm: string): string | null {
  if (pw.length < MIN_PASSWORD_LEN) return `Password must be at least ${MIN_PASSWORD_LEN} characters.`
  if (pw !== confirm) return 'Passwords do not match.'
  return null
}

// New-password + confirm fields shared by the setup wizard, invite-accept and
// change-password forms. Labels differ per form; values/setters live in the parent.
export function PasswordFields({
  password, confirm, onPasswordChange, onConfirmChange,
  label = 'Password', confirmLabel = 'Confirm password',
}: {
  password: string
  confirm: string
  onPasswordChange: (v: string) => void
  onConfirmChange: (v: string) => void
  label?: string
  confirmLabel?: string
}) {
  return (
    <>
      <Field label={label} type="password" autoComplete="new-password" value={password} onChange={(e) => onPasswordChange(e.target.value)} hint={`At least ${MIN_PASSWORD_LEN} characters.`} required />
      <Field label={confirmLabel} type="password" autoComplete="new-password" value={confirm} onChange={(e) => onConfirmChange(e.target.value)} required />
    </>
  )
}
