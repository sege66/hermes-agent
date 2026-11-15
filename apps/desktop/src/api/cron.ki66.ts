// ki66 (local-only): read-only cron delivery log used by the Desktop cron mirror.
// Lives entirely here (api/cron.ts is untouched upstream code); use-cron-merge
// imports it from this module.
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

export const listCronDeliveries = cronDeliveriesReader('/api/cron/deliveries')
