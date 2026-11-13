// ki66 (local-only): single import surface for the Desktop cron mirror wiring
// in chat/index.tsx.
//
// The mirror interleaves read-only cron deliveries on the LOCAL primary thread
// only. Pure-script cron jobs deliver stdout straight to Telegram without
// creating an agent session, so the session-derived store misses them; the
// mirror backfills them. A messaging session never gets it — its chat is that
// platform's own transcript (use-cron-merge guards by source).
import { QueryClientContext } from '@tanstack/react-query'
import { useContext } from 'react'

import type { ChatMessage } from '@/lib/chat-messages'

import { useCronMergeMessages as useCronMergeMessagesWithClient } from './use-cron-merge'

export { mergeCronMessages } from './merge-cron-messages'

const NO_CRON_MESSAGES: ChatMessage[] = []

function useNoCronMessages(): ChatMessage[] {
  return NO_CRON_MESSAGES
}

// The app always mounts ChatRuntimeBoundary under a QueryClientProvider, so the
// mirror always runs there. Upstream's own tests mount the boundary bare; with
// no client there is nothing to query, so the mirror stays empty instead of
// throwing — which lets those upstream test files stay byte-identical. Provider
// presence cannot change for a mounted boundary, so the hook choice is stable.
export function useCronMergeMessages(enabled = true, storedId: string | null = null): ChatMessage[] {
  const hasQueryClient = useContext(QueryClientContext) !== undefined
  const useMessages = hasQueryClient ? useCronMergeMessagesWithClient : useNoCronMessages

  return useMessages(enabled, storedId)
}
