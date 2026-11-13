// ki66 (local-only): marker-line helper for the Desktop cron mirror. Re-exported
// from parts.ts so the upstream file carries a single local line. Builds the
// text part inline (same shape as textPart without a timestamp) so this module
// does not import parts.ts back.
import type { ChatMessagePart } from './types'

export function prependMarkerLine(parts: ChatMessagePart[], label: string): ChatMessagePart[] {
  const [first, ...rest] = parts

  if (first?.type === 'text') {
    return [{ type: 'text', text: `${label}\n\n${first.text}` }, ...rest]
  }

  return [{ type: 'text', text: label }, ...parts]
}
