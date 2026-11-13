// ki66 (local-only) helper for use-session-list-actions.ts.
import type { SessionInfo } from '@/hermes'
import { sameCronSignature } from '@/lib/session-signatures'
import { mergeSessionPage } from '@/store/session'

// The messaging list is fetched with min_messages=1, which omits an open empty
// messaging chat. Without the keep set the workspace tab loses the row and
// falls back to "New session". Upstream replaces the list with the fetched
// page; locally the page is merged over the previous list for the kept ids.
export function keepOpenMessagingRows(prev: SessionInfo[], rows: SessionInfo[], keep: Set<string>): SessionInfo[] {
  const next = mergeSessionPage(prev, rows, keep)

  return sameCronSignature(prev, next) ? prev : next
}
