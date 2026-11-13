/**
 * Local (ki66) gateway auth mode, kept out of the upstream-owned websocket-url.ts.
 *
 * A `native` gateway hands out single-use private tickets: always mint a fresh
 * URL right before the socket opens and never fall back to the stored one.
 */
import type { ResolveGatewayWsUrlDeps } from './websocket-url'

export async function resolveNativeGatewayWsUrl(
  mint: ResolveGatewayWsUrlDeps['getGatewayWsUrl'],
  profile: null | string
): Promise<string> {
  if (!mint) {
    throw new Error('Native gateway requires a fresh private ticket')
  }

  const result = await mint(profile)

  if (typeof result === 'string') {
    return result
  }

  if (!result.ok) {
    throw new Error(result.error || 'Could not refresh the native gateway WebSocket ticket.')
  }

  return result.wsUrl
}
