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

  return [...local, ...additions].sort((left, right) => {
    const leftTs = left.timestamp ?? Number.POSITIVE_INFINITY
    const rightTs = right.timestamp ?? Number.POSITIVE_INFINITY

    return leftTs - rightTs
  })
}
