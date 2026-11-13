// ki66 (local-only): Desktop handling of the `session.external_updated` push.
//
// A turn that arrived on Telegram was written to state.db by the always-on
// gateway process, not by this window's runtime — nothing in the normal event
// flow carries it. The window refetches instead of routing the frame through
// the desktop handler, which expects locally-originated frames. When the push
// says the selected conversation was replaced (Telegram `/new`), the window
// follows to the new conversation instead.
//
// wiring.tsx keeps three hooks only: the import, one `useExternalSessionSync`
// call that publishes the live actions, and the event branch that calls
// `handleExternalSessionUpdate`. The actions travel through a module-level
// slot (one ContribWiring per window) so the upstream `useCallback` dependency
// list around the event branch stays untouched.
import { type MutableRefObject, useEffect } from 'react'
import type { NavigateFunction } from 'react-router'

import { sessionRoute } from '../routes'

export function externalSessionReplacement(
  selectedStoredSessionId: string | null | undefined,
  payload: unknown
): string | null {
  if (!payload || typeof payload !== 'object') {
    return null
  }

  const candidate = payload as { previous_session_id?: unknown; stored_session_id?: unknown }

  const previousSessionId =
    typeof candidate.previous_session_id === 'string' ? candidate.previous_session_id.trim() : ''

  const storedSessionId = typeof candidate.stored_session_id === 'string' ? candidate.stored_session_id.trim() : ''

  return previousSessionId && storedSessionId && selectedStoredSessionId === previousSessionId ? storedSessionId : null
}

interface ExternalSessionUpdateActions {
  refreshActiveTranscript: () => Promise<unknown>
  refreshMessagingSessions: () => Promise<unknown>
  replaceSessionRoute: (storedSessionId: string) => void
}

export async function refreshExternalSessionUpdate(
  replacementSessionId: string | null,
  actions: ExternalSessionUpdateActions
): Promise<void> {
  await actions.refreshMessagingSessions()

  if (replacementSessionId) {
    actions.replaceSessionRoute(replacementSessionId)

    return
  }

  await actions.refreshActiveTranscript()
}

interface ExternalSessionSync {
  navigate: NavigateFunction
  refreshActiveTranscript: () => Promise<unknown>
  refreshMessagingSessions: () => Promise<unknown>
  selectedStoredSessionIdRef: MutableRefObject<string | null | undefined>
}

let liveSync: ExternalSessionSync | null = null

/** Publishes this window's live actions for `handleExternalSessionUpdate`. */
export function useExternalSessionSync(sync: ExternalSessionSync): void {
  // Assigned during render as well so the slot is never older than the render
  // the gateway event handler closure was created in.
  liveSync = sync

  useEffect(() => {
    liveSync = sync

    return () => {
      if (liveSync === sync) {
        liveSync = null
      }
    }
  })
}

/** Handles one `session.external_updated` payload with the published actions. */
export function handleExternalSessionUpdate(payload: unknown): void {
  const sync = liveSync

  if (!sync) {
    return
  }

  const { navigate, refreshActiveTranscript, refreshMessagingSessions, selectedStoredSessionIdRef } = sync
  const replacementSessionId = externalSessionReplacement(selectedStoredSessionIdRef.current, payload)

  void refreshExternalSessionUpdate(replacementSessionId, {
    refreshActiveTranscript,
    refreshMessagingSessions,
    replaceSessionRoute: storedSessionId => navigate(sessionRoute(storedSessionId), { replace: true })
  }).catch(() => undefined)
}
