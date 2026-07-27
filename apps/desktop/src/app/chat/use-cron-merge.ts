import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { listCronDeliveries } from '@/hermes'
import { type ChatMessage, prependMarkerLine, textPart } from '@/lib/chat-messages'

const NO_MESSAGES: ChatMessage[] = []
const WINDOW_SECONDS = 24 * 60 * 60
const MAX_DELIVERIES = 20
const REFETCH_MS = 45_000

export function useCronMergeMessages(enabled = true): ChatMessage[] {
  const { data } = useQuery({
    queryKey: ['cron-deliveries'],
    enabled,
    staleTime: REFETCH_MS,
    refetchInterval: enabled ? REFETCH_MS : false,
    queryFn: () => listCronDeliveries(50)
  })

  return useMemo(() => {
    if (!enabled || !data) {
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
  }, [data, enabled])
}
