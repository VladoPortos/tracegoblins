// Render an ISO-8601 timestamp as a compact "YYYY-MM-DD HH:MM".
// We slice the ISO string rather than constructing a Date so the AWX-reported
// wall-clock time is shown verbatim (no browser-timezone shift).
export function shortTime(iso: string | null | undefined): string {
  if (!iso) return ''
  return iso.slice(0, 16).replace('T', ' ')
}
