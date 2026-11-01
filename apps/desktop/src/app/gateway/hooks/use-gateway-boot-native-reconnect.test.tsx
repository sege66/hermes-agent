import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { $desktopBoot } from '@/store/boot'
import { $activeGatewayProfile, $profiles } from '@/store/profile'
import { $connection, $gatewayState } from '@/store/session'
import { FakeWebSocket } from '@/test/fake-gateway-socket'

import { takeGatewaySurvivor } from './gateway-hmr-survivor'
import { useGatewayBoot } from './use-gateway-boot'

function Harness() {
  useGatewayBoot({
    beforeConnectionSwitch: () => undefined,
    handleGatewayEvent: () => undefined,
    handleServerRequest: () => false,
    onConnectionReady: () => undefined,
    onGatewayReady: () => undefined,
    refreshHermesConfig: async () => undefined,
    refreshSessions: async () => undefined
  })

  return null
}

beforeEach(() => {
  takeGatewaySurvivor()?.gateway.close()
  $activeGatewayProfile.set('default')
  $profiles.set([])
  $connection.set(null)
  $gatewayState.set('idle')
  $desktopBoot.set({
    error: null,
    fakeMode: false,
    message: '',
    phase: 'init',
    progress: 0,
    running: true,
    timestamp: Date.now(),
    visible: true
  })
  vi.useFakeTimers()
  vi.spyOn(Math, 'random').mockReturnValue(0.5)
  FakeWebSocket.instances = []
  FakeWebSocket.mode = 'open'
  FakeWebSocket.pingMode = 'pong'
  vi.stubGlobal('WebSocket', FakeWebSocket)
})

afterEach(() => {
  cleanup()
  takeGatewaySurvivor()?.gateway.close()
  $connection.set(null)
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('automatically recovers on a new port after a native ticket service outage', async () => {
  const connection = {
    authMode: 'native',
    baseUrl: 'http://127.0.0.1:41000',
    mode: 'local',
    profile: 'default',
    token: '',
    wsUrl: 'ws://127.0.0.1:41000/api/ws?native_dial=unminted'
  }

  const getGatewayWsUrl = vi.fn<NonNullable<Window['hermesDesktop']['getGatewayWsUrl']>>()

  getGatewayWsUrl.mockResolvedValue({
    ok: true,
    wsUrl: 'ws://127.0.0.1:41000/api/ws?native_dial=first&ticket=first-ticket'
  })
  vi.stubGlobal('hermesDesktop', {
    getConnection: vi.fn(async () => connection),
    getGatewayWsUrl,
    getBootProgress: vi.fn(async () => ({ ...$desktopBoot.get(), retryable: false })),
    onBootProgress: vi.fn(() => () => undefined),
    onBackendExit: vi.fn(() => () => undefined),
    onConnectionApplied: vi.fn(() => () => undefined),
    onWindowStateChanged: vi.fn(() => () => undefined),
    revalidateConnection: vi.fn(async () => ({ ok: true, rebuilt: false })),
    profile: { get: vi.fn(async () => ({ profile: 'default' })) }
  })
  render(<Harness />)
  await act(async () => vi.advanceTimersByTimeAsync(0))
  expect($gatewayState.get()).toBe('open')
  expect($desktopBoot.get().running).toBe(false)

  getGatewayWsUrl.mockResolvedValue({ ok: false, error: 'Gateway ticket control socket missing' })
  await act(async () => {
    FakeWebSocket.instances[0].drop()
    await vi.advanceTimersByTimeAsync(2_000)
  })
  expect(getGatewayWsUrl.mock.calls.length).toBeGreaterThan(2)
  expect($gatewayState.get()).not.toBe('connecting')
  expect(FakeWebSocket.instances).toHaveLength(1)

  getGatewayWsUrl.mockResolvedValue({
    ok: true,
    wsUrl: 'ws://127.0.0.1:42000/api/ws?native_dial=recovered&ticket=next-ticket'
  })
  await act(async () => vi.advanceTimersByTimeAsync(10_000))

  expect($gatewayState.get()).toBe('open')
  expect($desktopBoot.get().error).toBeNull()
  expect($desktopBoot.get().visible).toBe(false)
  expect(FakeWebSocket.instances).toHaveLength(2)
  expect(FakeWebSocket.instances[1].url).toBe('ws://127.0.0.1:42000/api/ws?native_dial=recovered')
})
