// ki66 (local-only): resume hydration must not keep another conversation's
// durable rows under an empty messaging session. Lives beside the upstream
// use-session-actions.test.tsx (kept byte-identical to upstream) and carries
// its own copy of that file's resume harness.
import { cleanup, render, waitFor } from '@testing-library/react'
import type { MutableRefObject } from 'react'
import { useEffect } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { getLatestSessionMessages, getSession, type SessionInfo } from '@/hermes'
import { createClientSessionState } from '@/lib/chat-runtime'
import { clearClarifyRequest } from '@/store/clarify'
import { requestGatewayForAgent, requestGatewayForProfile } from '@/store/gateway'
import {
  setActiveSessionId,
  setConnection,
  setMessages,
  setMessagingSessions,
  setResumeFailedSessionId,
  setSessions,
  setSessionStartedAt
} from '@/store/session'
import type { SessionProfileRoute } from '@/store/session-request-router'

import type { ClientSessionState } from '../../types'

import { useSessionActions } from './use-session-actions'
import { suppressTranscriptForView, transcriptRowContentKey } from './use-session-actions/transcript-provenance'
import type { TranscriptViewCutoff } from './use-session-actions/transcript-provenance'

vi.mock('@/hermes', async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  deleteSession: vi.fn(),
  getSession: vi.fn(),
  getAllSessionMessages: vi.fn(),
  getLatestSessionMessages: vi.fn(),
  listAllProfileSessions: vi.fn(),
  setApiRequestProfile: vi.fn(),
  setSessionArchived: vi.fn()
}))

vi.mock('@/store/profile', async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  ensureGatewayAgent: vi.fn().mockResolvedValue(undefined),
  ensureGatewayProfile: vi.fn().mockResolvedValue(undefined)
}))

vi.mock('@/store/gateway', async importOriginal => {
  const original = await importOriginal<Record<string, unknown>>()

  return {
    ...original,
    // Default-preserving spy: tests that route by the active source override it.
    activeGatewayConnectionId: vi.fn(original.activeGatewayConnectionId as () => null | string),
    requestGatewayForAgent: vi.fn(),
    requestGatewayForProfile: vi.fn(),
    retainGatewayForAgent: vi.fn(async () => () => undefined)
  }
})

vi.mock('@/components/pane-shell/tree/store', async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  noteActiveTreeGroup: vi.fn(),
  revealTreePane: vi.fn()
}))

function storedSession(overrides: Partial<SessionInfo> = {}): SessionInfo {
  return {
    ended_at: null,
    id: 'stored-1',
    input_tokens: 0,
    is_active: false,
    last_active: 1,
    message_count: 0,
    model: null,
    output_tokens: 0,
    preview: null,
    source: 'desktop',
    started_at: 1,
    title: 'stored',
    tool_call_count: 0,
    ...overrides
  }
}

function ResumeHarness({
  onStateUpdate,
  onViewSync,
  onReady,
  getRouteToken = () => 'token',
  requestGateway,
  runtimeIdByStoredSessionIdRef,
  selectedStoredSessionId = null,
  sessionStateByRuntimeIdRef
}: {
  getRouteToken?: () => string
  onStateUpdate?: (sessionId: string, state: ClientSessionState) => void
  onViewSync?: (sessionId: string, state: ClientSessionState) => void
  onReady: (
    resume: (
      storedSessionId: string,
      replaceRoute?: boolean,
      ownerRoute?: SessionProfileRoute,
      options?: { authoritativeSnapshot?: boolean }
    ) => Promise<unknown>
  ) => void
  requestGateway: <T>(method: string, params?: Record<string, unknown>) => Promise<T>
  runtimeIdByStoredSessionIdRef?: MutableRefObject<Map<string, string>>
  selectedStoredSessionId?: string | null
  sessionStateByRuntimeIdRef?: MutableRefObject<Map<string, ClientSessionState>>
}) {
  const ref = <T,>(value: T): MutableRefObject<T> => ({ current: value })
  const runtimeMapRef = runtimeIdByStoredSessionIdRef ?? ref(new Map<string, string>())
  const stateMapRef = sessionStateByRuntimeIdRef ?? ref(new Map<string, ClientSessionState>())
  // Stand in for the real hook's gate: without it this stub would publish the
  // unproven warm cache before REST authority lands. Kept here (not per-test)
  // so every resume through this harness sees one shared suppression policy.
  const heldCutoffsByRuntimeIdRef = ref(new Map<string, TranscriptViewCutoff>())

  const actions = useSessionActions({
    activeSessionId: null,
    activeSessionIdRef: ref<string | null>(null),
    busyRef: ref(false),
    creatingSessionRef: ref(false),
    ensureSessionState: () => ({}) as ClientSessionState,
    getRouteToken,
    getRoutedStoredSessionId: () => null,
    navigate: vi.fn() as never,
    requestGateway,
    resetViewSync: vi.fn(),
    routedSessionId: null,
    runtimeIdByStoredSessionIdRef: runtimeMapRef,
    selectedStoredSessionId,
    selectedStoredSessionIdRef: ref<string | null>(selectedStoredSessionId),
    sessionStateByRuntimeIdRef: stateMapRef,
    holdSessionTranscriptView: runtimeId => {
      const rows = stateMapRef.current.get(runtimeId)?.messages ?? []

      const cutoff: TranscriptViewCutoff = {
        cutoffIds: new Set(rows.map(message => message.id)),
        cutoffKeys: new Set(rows.map(transcriptRowContentKey))
      }

      heldCutoffsByRuntimeIdRef.current.set(runtimeId, cutoff)

      return () => {
        heldCutoffsByRuntimeIdRef.current.delete(runtimeId)
      }
    },
    syncSessionStateToView: (sessionId, state) => {
      const cutoff = heldCutoffsByRuntimeIdRef.current.get(sessionId) ?? null

      onViewSync?.(sessionId, suppressTranscriptForView(state, cutoff))
    },
    updateSessionState: (sessionId, updater, storedSessionId) => {
      // Full default shape (not a bare {} cast) so seeded/derived fields like
      // turnStartedAt behave as in production state updates.
      const current = stateMapRef.current.get(sessionId) ?? createClientSessionState(storedSessionId ?? null)
      const next = updater(current)

      stateMapRef.current.set(sessionId, next)
      onStateUpdate?.(sessionId, next)

      return next
    }
  })

  useEffect(() => {
    onReady(actions.resumeSession)
  }, [actions.resumeSession, onReady])

  return null
}

const clientState = (storedSessionId: string | null): ClientSessionState => createClientSessionState(storedSessionId)

describe('resumeSession on an empty messaging session (ki66)', () => {
  afterEach(() => {
    cleanup()
    setActiveSessionId(null)
    setResumeFailedSessionId(null)
    setSessionStartedAt(null)
    setMessages([])
    setSessions([])
    setMessagingSessions([])
    vi.mocked(getSession).mockReset()
    vi.mocked(getLatestSessionMessages)
      .mockReset()
      .mockResolvedValue({ messages: [] } as never)
    vi.mocked(requestGatewayForAgent).mockReset()
    clearClarifyRequest()
    vi.mocked(requestGatewayForProfile).mockReset()
    setConnection(null)
    vi.restoreAllMocks()
  })

  it('drops another conversation painted under an empty messaging session', async () => {
    const runtimeIdByStoredSessionIdRef: MutableRefObject<Map<string, string>> = {
      current: new Map([['stored-A', 'rt-A']])
    }

    const state = clientState('stored-A')
    state.messages = [
      {
        id: 'foreign-user',
        role: 'user',
        rowId: 9001,
        parts: [{ type: 'text', text: 'HuggingNews briefing that belongs to cron' }]
      },
      {
        id: 'foreign-assistant',
        role: 'assistant',
        rowId: 9002,
        parts: [{ type: 'text', text: 'DeepSeek Harness foreign tail' }]
      }
    ]

    const sessionStateByRuntimeIdRef: MutableRefObject<Map<string, ClientSessionState>> = {
      current: new Map([['rt-A', state]])
    }

    const row = storedSession({ id: 'stored-A', message_count: 0, profile: 'default', source: 'telegram', title: null })
    setMessagingSessions([row])
    vi.mocked(getSession).mockResolvedValue(row)
    vi.mocked(getLatestSessionMessages).mockResolvedValue({ messages: [], session_id: 'stored-A' } as never)

    const requestGateway = vi.fn(async (method: string) => {
      if (method === 'session.activate') {
        return {
          session_id: 'rt-A',
          session_key: 'stored-A',
          resumed: 'stored-A',
          message_count: 0,
          messages: [],
          messages_omitted: true,
          running: false,
          info: {}
        } as never
      }

      return {} as never
    })

    // The row carries a profile, so the activate goes through the profile route.
    vi.mocked(requestGatewayForProfile).mockImplementation(((_profile: string, method: string) =>
      requestGateway(method)) as never)

    let resumedState: ClientSessionState | undefined
    let resume: ((storedSessionId: string, replaceRoute?: boolean) => Promise<unknown>) | null = null

    render(
      <ResumeHarness
        onReady={ready => (resume = ready)}
        onStateUpdate={(_sessionId, next) => (resumedState = next)}
        requestGateway={requestGateway}
        runtimeIdByStoredSessionIdRef={runtimeIdByStoredSessionIdRef}
        sessionStateByRuntimeIdRef={sessionStateByRuntimeIdRef}
      />
    )
    await waitFor(() => expect(resume).not.toBeNull())
    await resume!('stored-A', true)

    expect(requestGateway).toHaveBeenCalledWith('session.activate')
    expect(resumedState).toBeDefined()
    const renderedMessages = JSON.stringify(resumedState?.messages ?? [])
    expect(renderedMessages).not.toContain('HuggingNews briefing that belongs to cron')
    expect(renderedMessages).not.toContain('DeepSeek Harness foreign tail')
    expect(resumedState?.messages ?? []).toHaveLength(0)
  })
})
