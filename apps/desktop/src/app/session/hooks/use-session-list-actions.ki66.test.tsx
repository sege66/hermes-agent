// Local (ki66) cases split out of the upstream-owned use-session-list-actions.test.tsx.
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SessionInfo, SidebarSessionsResponse } from '@/hermes'
import { setCronJobs } from '@/store/cron'
import {
  $messagingSessions,
  $selectedStoredSessionId,
  setCronSessions,
  setMessagingPlatformTotals,
  setMessagingSessions,
  setMessagingTruncated,
  setSessionProfilesFailed,
  setSessionProfilesTruncated,
  setSessionProfilesUsage,
  setSessions,
  setSessionsLoadError,
  setSessionsLoading
} from '@/store/session'

import { useSessionListActions } from './use-session-list-actions'

const row = (id: string, over: Partial<SessionInfo> = {}): SessionInfo =>
  ({
    ended_at: null,
    id,
    input_tokens: 0,
    is_active: false,
    last_active: 1000,
    message_count: 3,
    model: 'm',
    output_tokens: 0,
    preview: 'hey',
    profile: 'default',
    source: 'desktop',
    started_at: 900,
    title: `Chat ${id}`,
    ...over
  }) as SessionInfo

const sidebar = (
  recents: { sessions: SessionInfo[]; profiles_truncated?: Record<string, boolean> },
  cron: SessionInfo[] = [],
  messaging: SessionInfo[] = []
): SidebarSessionsResponse => ({
  recents: { sessions: recents.sessions, profiles_truncated: recents.profiles_truncated },
  cron: { sessions: cron },
  messaging: { sessions: messaging }
})

const listSidebarSessions = vi.fn()
const listAllProfileSessions = vi.fn()
const getCronJobs = vi.fn()
const gatewayScope = vi.hoisted(() => ({ epoch: 0 }))

vi.mock('@/hermes', async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getCronJobs: (...args: unknown[]) => getCronJobs(...args),
  listAllProfileSessions: (...args: unknown[]) => listAllProfileSessions(...args),
  listSidebarSessions: (...args: unknown[]) => listSidebarSessions(...args)
}))

vi.mock('@/store/gateway', async importOriginal => ({
  ...(await importOriginal<Record<string, unknown>>()),
  gatewayActivationEpoch: () => gatewayScope.epoch
}))

// The refresh only reads the optimistic tombstone set; stub it so we don't pull
// the whole projects store (gateway / fs / git) into this hook's test.
const removed = vi.hoisted(() => ({ ids: new Set<string>() }))

vi.mock('@/store/session-removal', async importActual => ({
  ...(await importActual<Record<string, unknown>>()),
  $removedSessionIds: { get: () => removed.ids }
}))

// The settle-grace keep set must be mocked at MODULE scope: the hook imports
// getRecentlySettledSessionIds as a live ESM binding, so patching a
// dynamically-imported copy (or a temporary object) never reaches it.
const settled = vi.hoisted(() => ({ ids: [] as string[] }))

vi.mock('@/store/session-states', async importActual => ({
  ...(await importActual<Record<string, unknown>>()),
  getRecentlySettledSessionIds: () => settled.ids
}))

beforeEach(() => {
  gatewayScope.epoch = 0
  settled.ids = []
  getCronJobs.mockReset()
  getCronJobs.mockResolvedValue([])
  listSidebarSessions.mockReset()
  listAllProfileSessions.mockReset()
  removed.ids = new Set()
  setCronJobs([])
  setSessions([])
  setCronSessions([])
  setMessagingSessions([])
  setMessagingPlatformTotals({})
  setMessagingTruncated(false)
  $selectedStoredSessionId.set(null)
  setSessionProfilesTruncated({})
  setSessionProfilesUsage({})
  setSessionProfilesFailed([])
  setSessionsLoading(false)
  setSessionsLoadError(false)
})

afterEach(() => {
  setCronJobs([])
  setSessions([])
  setCronSessions([])
  setMessagingSessions([])
  setMessagingPlatformTotals({})
  setMessagingTruncated(false)
  $selectedStoredSessionId.set(null)
  setSessionProfilesTruncated({})
  setSessionProfilesUsage({})
  setSessionsLoading(false)
  setSessionsLoadError(false)
})

describe('open empty messaging session', () => {
  it('keeps the open chat when the min-message page omits it', async () => {
    const open = row('tg-empty', { message_count: 0, preview: null, source: 'telegram', title: null })
    const older = row('tg-old', { source: 'telegram', title: 'older' })
    $selectedStoredSessionId.set('tg-empty')
    setMessagingSessions([open])
    listSidebarSessions.mockResolvedValue(sidebar({ sessions: [] }, [], [older]))
    const { result } = renderHook(() => useSessionListActions({ profileScope: 'default' }))

    await act(async () => {
      await result.current.refreshSessions()
    })

    expect($messagingSessions.get().map(session => session.id)).toContain('tg-empty')
    expect($messagingSessions.get().map(session => session.id)).toContain('tg-old')
  })
})
