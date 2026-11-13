// Local (ki66) cases split out of the upstream-owned use-route-resume.test.tsx.
import { cleanup, render } from '@testing-library/react'
import type { MutableRefObject } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { SessionProfileRoute } from '@/store/session-request-router'
import { markSelectionRestore } from '@/store/session-states'

import { useRouteResume } from './use-route-resume'

// The hook only arms the boot-restore one-shot; the listener consuming it lives
// in the real store (covered by session-states.test.ts). Mock the module so the
// store's side effects (persistence listeners) stay out of this harness.
vi.mock('@/store/session-states', () => ({ markSelectionRestore: vi.fn() }))

interface HarnessProps {
  activeSessionId: null | string
  activeSessionIdRef: MutableRefObject<null | string>
  creatingSessionRef: MutableRefObject<boolean>
  currentView: string
  freshDraftReady: boolean
  gatewayState: string
  locationPathname: string
  resumeSession: (
    sessionId: string,
    focus: boolean,
    ownerRoute?: SessionProfileRoute,
    options?: { authoritativeSnapshot?: boolean }
  ) => Promise<unknown>
  resumeFailedSessionId?: null | string
  resumeExhaustedSessionId?: null | string
  sessionResumeRequest?: null | {
    authoritativeSnapshot?: boolean
    ownerRoute?: SessionProfileRoute
    sequence: number
    sessionId: string
  }
  routedSessionId: null | string
  runtimeIdByStoredSessionIdRef: MutableRefObject<Map<string, string>>
  selectedStoredSessionId: null | string
  selectedStoredSessionIdRef: MutableRefObject<null | string>
  startFreshSessionDraft: (options: boolean | { replaceRoute?: boolean; rotateFreshDraftKey?: boolean }) => unknown
}

function RouteResumeHarness({
  resumeFailedSessionId = null,
  resumeExhaustedSessionId = null,
  sessionResumeRequest = null,
  ...props
}: HarnessProps) {
  useRouteResume({ ...props, resumeExhaustedSessionId, resumeFailedSessionId, sessionResumeRequest })

  return null
}

describe('useRouteResume (ki66)', () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('does not treat a replacement after manual selection as a boot restore', () => {
    vi.mocked(markSelectionRestore).mockClear()
    const resumeSession = vi.fn(async () => undefined)
    const startFreshSessionDraft = vi.fn()
    const activeSessionIdRef: MutableRefObject<null | string> = { current: null }
    const creatingSessionRef = { current: false }
    const runtimeIdByStoredSessionIdRef = { current: new Map<string, string>() }
    const selectedStoredSessionIdRef: MutableRefObject<null | string> = { current: null }

    const props = {
      activeSessionIdRef,
      creatingSessionRef,
      currentView: 'chat',
      gatewayState: 'open',
      resumeSession,
      runtimeIdByStoredSessionIdRef,
      selectedStoredSessionIdRef,
      startFreshSessionDraft
    }

    const { rerender } = render(
      <RouteResumeHarness
        {...props}
        activeSessionId={null}
        freshDraftReady
        locationPathname="/"
        routedSessionId={null}
        selectedStoredSessionId={null}
      />
    )

    activeSessionIdRef.current = 'runtime-old'
    selectedStoredSessionIdRef.current = 'session-old'
    runtimeIdByStoredSessionIdRef.current.set('session-old', 'runtime-old')
    rerender(
      <RouteResumeHarness
        {...props}
        activeSessionId="runtime-old"
        freshDraftReady={false}
        locationPathname="/session-old"
        routedSessionId="session-old"
        selectedStoredSessionId="session-old"
      />
    )

    expect(resumeSession).not.toHaveBeenCalled()

    rerender(
      <RouteResumeHarness
        {...props}
        activeSessionId="runtime-old"
        freshDraftReady={false}
        locationPathname="/session-new"
        routedSessionId="session-new"
        selectedStoredSessionId="session-old"
      />
    )

    expect(resumeSession).toHaveBeenCalledWith('session-new', true)
    expect(markSelectionRestore).not.toHaveBeenCalled()
  })

  it('preserves boot restore when the session hash parses after the initial pathname', () => {
    vi.mocked(markSelectionRestore).mockClear()
    const previousHash = window.location.hash

    window.location.hash = '#/session-hash'

    try {
      const resumeSession = vi.fn(async () => undefined)
      const activeSessionIdRef: MutableRefObject<null | string> = { current: null }
      const selectedStoredSessionIdRef: MutableRefObject<null | string> = { current: null }
      const props = {
        activeSessionId: null,
        activeSessionIdRef,
        creatingSessionRef: { current: false },
        currentView: 'chat',
        freshDraftReady: true,
        gatewayState: 'open',
        resumeSession,
        runtimeIdByStoredSessionIdRef: { current: new Map<string, string>() },
        selectedStoredSessionId: null,
        selectedStoredSessionIdRef,
        startFreshSessionDraft: vi.fn()
      }

      const { rerender } = render(<RouteResumeHarness {...props} locationPathname="/" routedSessionId={null} />)

      rerender(<RouteResumeHarness {...props} locationPathname="/session-hash" routedSessionId="session-hash" />)

      expect(resumeSession).toHaveBeenCalledWith('session-hash', true)
      expect(markSelectionRestore).toHaveBeenCalledTimes(1)
    } finally {
      window.location.hash = previousHash
    }
  })
})
