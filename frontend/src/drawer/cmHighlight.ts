import { json } from '@codemirror/lang-json'
import { yaml } from '@codemirror/lang-yaml'
import { HighlightStyle } from '@codemirror/language'
import { tags as t } from '@lezer/highlight'

export const tgHighlight = HighlightStyle.define([
  { tag: t.comment, color: '#6a9a5b', fontStyle: 'italic' },
  { tag: [t.keyword, t.bool, t.null, t.atom, t.operatorKeyword], color: '#a072c4' },
  { tag: [t.string, t.special(t.string)], color: '#c7794a' },
  { tag: [t.number, t.integer, t.float], color: '#3f9f8f' },
  { tag: [t.propertyName, t.definition(t.propertyName)], color: '#2a7bd6', fontWeight: '600' },
  { tag: [t.meta, t.documentMeta, t.processingInstruction], color: '#8a8a8a' },
  { tag: t.invalid, color: '#d14' },
])

function isJson(s: string): boolean {
  try { JSON.parse(s); return true } catch { return false }
}

export function languageFor(value: string, filename?: string) {
  const ext = filename?.toLowerCase().split('.').pop()
  if (ext === 'yml' || ext === 'yaml') return [yaml()]
  if (ext === 'json') return [json()]
  if (filename === undefined && isJson(value)) return [json()]
  return []
}
