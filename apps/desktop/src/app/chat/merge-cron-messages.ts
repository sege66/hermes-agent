import { type ChatMessage, chatMessageText } from '@/lib/chat-messages'

const CRON_MARKER_RE = /^🤖[^\n]*\n\n/

function comparableText(message: ChatMessage): string {
  return chatMessageText(message).replace(CRON_MARKER_RE, '').trim()
}

/** Interleave read-only cron deliveries without echoing text already in chat. */
export function mergeCronMessages(local: ChatMessage[], cron: ChatMessage[]): ChatMessage[] {
  if (!cron.length) {
    return local
  }

  const seen = new Set(local.map(comparableText).filter(Boolean))
  const additions = cron.filter(message => {
    const text = comparableText(message)

    if (!text || seen.has(text)) {
      return false
    }

    seen.add(text)
    return true
  })

  if (!additions.length) {
    return local
  }

  // Local transcript order is authoritative (durable row order). Only the
  // cron deliveries are placed by timestamp — a delivery goes right before
  // the first local message that is newer than it. Never re-sort the local
  // messages themselves: their `timestamp` is display metadata that the
  // hydration reconciler may rewrite (a repeated identical reply inherits the
  // earlier twin's timestamp, 2026-08-24), and a global sort turned that into
  // a visibly misplaced bubble.
  const queue = [...additions].sort((left, right) => {
    const leftTs = left.timestamp ?? Number.POSITIVE_INFINITY
    const rightTs = right.timestamp ?? Number.POSITIVE_INFINITY

    return leftTs - rightTs
  })
  const merged: ChatMessage[] = []
  let cursor = 0

  for (const message of local) {
    if (message.timestamp !== undefined) {
      while (cursor < queue.length && (queue[cursor].timestamp ?? Number.POSITIVE_INFINITY) <= message.timestamp) {
        merged.push(queue[cursor])
        cursor += 1
      }
    }

    merged.push(message)
  }

  merged.push(...queue.slice(cursor))

  return merged
}
