// ki66 (local-only): read-only cron delivery log used by the Desktop cron mirror.
// api/cron.ts keeps only the route literal + the export so upstream edits to
// that file do not collide with this body.
import { connectionScoped, hermesApi, profileScoped, STARTUP_REQUEST_TIMEOUT_MS } from './client'

export interface CronDelivery {
  ts: number
  job_id: string
  job_name: string
  text: string
}

export function cronDeliveriesReader(path: string) {
  return async function listCronDeliveries(limit = 50): Promise<CronDelivery[]> {
    const result = await hermesApi<{ data?: CronDelivery[] }>({
      ...profileScoped(),
      ...connectionScoped(),
      path: `${path}?limit=${limit}`,
      timeoutMs: STARTUP_REQUEST_TIMEOUT_MS
    })

    return result.data ?? []
  }
}
