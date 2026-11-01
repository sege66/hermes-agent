import { isGatewayReauthRequired, resolveGatewayWsUrl } from '@hermes/shared'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { HermesGateway } from '@/hermes'
import { FakeWebSocket } from '@/test/fake-gateway-socket'

const connection = {
  authMode: 'native',
  profile: 'default',
  wsUrl: 'ws://127.0.0.1:41000/api/ws?native_dial=unminted'
}

const freshUrl = 'ws://127.0.0.1:42000/api/ws?native_dial=fresh&ticket=test-ticket'

describe('native gateway reconnect', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeWebSocket.instances = []
    FakeWebSocket.mode = 'open'
    FakeWebSocket.pingMode = 'pong'
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it.each(['structured', 'rejected'] as const)('keeps a %s mint failure retryable without using an unminted URL', async failure => {
    const cause = new Error('Gateway ticket control socket missing')
    const getGatewayWsUrl = vi.fn<NonNullable<Window['hermesDesktop']['getGatewayWsUrl']>>()

    if (failure === 'structured') {
      getGatewayWsUrl.mockResolvedValueOnce({ ok: false, error: cause.message })
    } else {
      getGatewayWsUrl.mockRejectedValueOnce(cause)
    }

    getGatewayWsUrl.mockResolvedValueOnce({ ok: true, wsUrl: freshUrl })
    const failed = resolveGatewayWsUrl({ getGatewayWsUrl }, connection)

    await expect(failed).rejects.toThrow(cause.message)
    expect(isGatewayReauthRequired(await failed.catch(error => error))).toBe(false)
    await expect(resolveGatewayWsUrl({ getGatewayWsUrl }, connection)).resolves.toBe(freshUrl)
    expect(getGatewayWsUrl).toHaveBeenNthCalledWith(2, 'default')
  })

  it('refuses a native connection without a ticket bridge', async () => {
    await expect(resolveGatewayWsUrl({}, connection)).rejects.toThrow(/native.*ticket/i)
  })

  it('can retry the same client after synchronous socket construction fails', async () => {
    const gateway = new HermesGateway()

    try {
      await expect(gateway.connect(connection.wsUrl)).rejects.toThrow('Native gateway requires a fresh private ticket')
      expect(gateway.connectionState).not.toBe('connecting')

      const connecting = gateway.connect(freshUrl)
      await vi.advanceTimersByTimeAsync(0)
      await connecting

      expect(gateway.connectionState).toBe('open')
      expect(FakeWebSocket.instances).toHaveLength(1)
      expect(FakeWebSocket.instances[0].url).not.toContain('ticket=')
      expect(FakeWebSocket.instances[0].url).toContain(':42000/')
    } finally {
      gateway.close()
    }
  })
})
