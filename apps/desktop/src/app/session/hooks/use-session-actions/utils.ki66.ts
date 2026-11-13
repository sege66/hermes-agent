// ki66 (local-only) helper for use-session-actions/index.ts (resume hydration).
import { isMessagingSource } from '@/lib/session-source'
import type { SessionInfo } from '@/types/hermes'

import { sessionShouldHaveTranscript } from './utils'

// An empty REST page is normally not proof the transcript is empty (upstream
// keeps the activate/cache transcript then). A messaging shell whose stored
// row has no messages is the opposite: those durable row ids were persisted
// for some other conversation. Keeping them paints that transcript under the
// empty chat. Unsent local rows have no rowId and stay, and a messaging row
// that does have messages still ignores a transient empty page.
export function emptyMessagingShellHasForeignRows(
  persisted: { messages: readonly unknown[] } | null | undefined,
  stored: SessionInfo | undefined,
  activated: { inflight?: unknown; queued?: unknown },
  cachedViewState: { messages: readonly { rowId?: unknown }[] }
): boolean {
  return (
    persisted?.messages.length === 0 &&
    Boolean(stored) &&
    isMessagingSource(stored?.source) &&
    !sessionShouldHaveTranscript(stored) &&
    !activated.inflight &&
    !activated.queued &&
    cachedViewState.messages.length > 0 &&
    cachedViewState.messages.every(message => message.rowId !== undefined)
  )
}
