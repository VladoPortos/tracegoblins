import { SafeLinkChip } from './SafeLinkChip'
import type { KbLink } from '../../api/kb'

// Thin alias over the shared SafeLinkChip (FECMP4) — kept so existing call sites + the phaseE
// contract import KbLinkRow by name.
export function KbLinkRow({ link }: { link: KbLink }) {
  return <SafeLinkChip link={link} />
}
