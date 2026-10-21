import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { getSession, listCronDeliveries } from '@/hermes'
import { type ChatMessage, prependMarkerLine, textPart } from '@/lib/chat-messages'
import { isMessagingSource } from '@/lib/session-source'

const NO_MESSAGES: ChatMessage[] = []
const WINDOW_SECONDS = 24 * 60 * 60
const MAX_DELIVERIES = 20
const REFETCH_MS = 45_000

// The cron mirror belongs to the local chat surface only. A messaging session
// (Telegram & co.) has its own delivery channel — painting cron output there
// showed one job's transcript under an unrelated conversation (2026-10-19).
// While a stored session's source is still loading the mirror stays off: the
// guard must resolve before any foreign row can render.
export function useCronMergeMessages(enabled = true, storedId: string | null = null): ChatMessage[] {
  const { data: sessionSource } = useQuery({
    queryKey: ['cron-mirror-session-source', storedId],
    enabled: enabled && Boolean(storedId),
    staleTime: 60_000,
    queryFn: async () => ((await getSession(storedId as string)).source ?? null)
  })

  const sourceKnown = !storedId || sessionSource !== undefined
  const mirrorAllowed = enabled && sourceKnown && !isMessagingSource(sessionSource ?? undefined)

  const { data } = useQuery({
    queryKey: ['cron-deliveries'],
    enabled: mirrorAllowed,
    staleTime: REFETCH_MS,
    refetchInterval: mirrorAllowed ? REFETCH_MS : false,
    queryFn: () => listCronDeliveries(50)
  })

  return useMemo(() => {
    if (!mirrorAllowed || !data) {
      return NO_MESSAGES
    }

    const cutoff = Date.now() / 1000 - WINDOW_SECONDS

    return data
      .filter(delivery => delivery.ts >= cutoff && delivery.text.trim())
      .slice(0, MAX_DELIVERIES)
      .map(delivery => ({
        id: `__cron__${delivery.job_id}__${delivery.ts}`,
        role: 'assistant' as const,
        timestamp: delivery.ts,
        parts: prependMarkerLine([textPart(delivery.text)], `🤖 ${delivery.job_name}`)
      }))
  }, [data, mirrorAllowed])
}
