// Local (ki66) cases split out of the upstream-owned session-control.test.ts.
import { JsonRpcGatewayError } from '@hermes/shared'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { refreshLegacyGoal } = vi.hoisted(() => ({ refreshLegacyGoal: vi.fn() }))

vi.mock('./goals', async importOriginal => ({
  ...(await importOriginal()),
  refreshSessionGoal: refreshLegacyGoal
}))

import { $gateway } from './gateway'
import { resetBackgroundPollingGuard } from './runtime-gone'
import {
  $sessionControlBySession,
  applySessionControlSnapshot,
  clearAllSessionControl,
  refreshSessionControl,
  runSessionControlAction,
  type SessionControlSnapshot
} from './session-control'

const FULL_SNAPSHOT: SessionControlSnapshot = {
  goal: {
    contract: {
      boundaries: 'desktop store only',
      constraints: 'do not lose state',
      outcome: 'session control is hydrated',
      stop_when: 'a human decision is required',
      verification: 'focused tests pass'
    },
    created_at: 1_700_000_000,
    gates: [{ attempts: 0, command: 'npm test', last_exit_code: null, max_retries: 2, timeout_seconds: 60 }],
    max_turns: 20,
    status: 'active',
    subgoals: ['write tests', 'repair state'],
    title: 'Repair session control',
    turns_used: 3,
    updated_at: 1_700_000_100,
    wait_barrier: { reason: 'waiting for deploy', type: 'until', until_at: 1_700_000_200 }
  },
  heartbeat: {
    created_at: 1_700_000_000,
    fire_count: 5,
    interval_seconds: 600,
    last_fired_at: 1_700_000_100,
    prompt: 'check health',
    status: 'active'
  },
  loop: {
    awaiting_response: false,
    created_at: 1_700_000_000,
    current_delay: 300,
    deferred_by_goal: false,
    interval_seconds: 300,
    last_fired_at: 1_700_000_100,
    max_ticks: 10,
    mode: 'interval',
    next_due_at: 1_700_000_400,
    prompt: 'check build status',
    status: 'active',
    ticks_fired: 3,
    times: 3,
    until: ''
  },
  revision: 'revision-1',
  updated_at: 1_700_000_100
}

function useGateway(request: (method: string, params: Record<string, unknown>) => Promise<unknown>): void {
  $gateway.set({ request } as never)
}

describe('session-control store (ki66)', () => {
  beforeEach(() => {
    refreshLegacyGoal.mockReset()
    clearAllSessionControl()
  })

  afterEach(() => {
    $gateway.set(null as never)
    resetBackgroundPollingGuard()
    clearAllSessionControl()
  })

  it.each([
    ['typed refusal', () => new JsonRpcGatewayError('stale_generation', { code: 4009, data: { reason: 'stale_generation' } })],
    ['bare message', () => new Error('stale_generation')]
  ])('keeps the last snapshot without an error when a read meets a retired route (%s)', async (_name, make) => {
    applySessionControlSnapshot('s1', FULL_SNAPSHOT)
    useGateway(
      vi.fn(async () => {
        throw make()
      })
    )

    await refreshSessionControl('s1')

    const entry = $sessionControlBySession.get().s1!
    expect(entry.snapshot!.revision).toBe(FULL_SNAPSHOT.revision)
    expect(entry.error).toBeNull()
    expect(entry.loading).toBe(false)
  })

  it('still reports stale_generation from an explicit control action', async () => {
    applySessionControlSnapshot('s1', FULL_SNAPSHOT)
    useGateway(
      vi.fn(async () => {
        throw new Error('stale_generation')
      })
    )

    await expect(runSessionControlAction('s1', 'goal.pause')).rejects.toThrow('stale_generation')
    expect($sessionControlBySession.get().s1!.error).toBe('stale_generation')
  })
})
