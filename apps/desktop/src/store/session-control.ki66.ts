// ki66 (local-only): classification of a session-control read refused because
// its route was retired. session-control.ts keeps only the import + the catch
// branch that uses it.

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

// The owner refuses a read whose route now serves another conversation (an idle reset or /new
// rotated it) as `stale_generation`. Nothing on that retired route is controllable, so a read
// keeps its last snapshot quietly instead of raising the "controls unavailable" banner.
export function isRetiredRouteRead(error: unknown): boolean {
  const data = isRecord(error) ? error.data : undefined
  const reason = isRecord(data) ? data.reason : undefined

  if (typeof reason === 'string') {
    return reason === 'stale_generation'
  }

  const message =
    error instanceof Error ? error.message : isRecord(error) && typeof error.message === 'string' ? error.message : ''

  return message.trim() === 'stale_generation'
}
