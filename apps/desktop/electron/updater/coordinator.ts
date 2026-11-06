import { execFile } from 'node:child_process'
import { accessSync, constants, readFileSync, realpathSync } from 'node:fs'
import path from 'node:path'
import { promisify } from 'node:util'

import { makeHandoffRunId, updateHandoffConflict, waitForHandoffClaim } from '../update-marker'
import { killHandoffTree, observeUpdaterHandoff, spawnUpdaterProcess } from '../updater-process'

import { sourceUpdateEnvironment } from './checkout-source'

import type { UpdaterApplyResultWire, UpdaterStatusWire } from './index'

export interface CoordinatorDeps {
  hermesHome: string
  updateRoot: string
  isMac: boolean
  appBundle: string | null
  check: () => Promise<UpdaterStatusWire>
  remoteGatewayActive: () => boolean
  emitUpdateProgress: (payload: { stage: string; message: string; percent: number | null }) => void
  rememberLog: (message: string) => void
  quit: () => void
  dwellMs: number
}

const execute: typeof execFile.__promisify__ = promisify(execFile)

export async function handOffMacUpdateToCoordinator(deps: CoordinatorDeps): Promise<UpdaterApplyResultWire | null> {
  const coordinator = path.join(deps.hermesHome, 'bin', 'hermes-update-coordinator')
  if (!deps.isMac || deps.appBundle !== '/Applications/Hermes.app') return null
  try {
    accessSync(coordinator, constants.X_OK)
    if (realpathSync(deps.updateRoot) !== realpathSync(path.join(deps.hermesHome, 'hermes-agent'))) return null
  } catch {
    return null
  }
  const fail = (message: string): UpdaterApplyResultWire => {
    deps.emitUpdateProgress({ stage: 'error', message, percent: null })
    return { ok: false, error: 'protected-update-failed', message }
  }
  const conflict = await updateHandoffConflict(deps.hermesHome)
  if (conflict) return fail(conflict.message)
  deps.emitUpdateProgress({ stage: 'checking', message: 'Checking for updates…', percent: 4 })
  const status = await deps.check()
  if (!status.supported || status.error)
    return fail(status.message ?? status.error ?? status.reason ?? 'Update check unavailable.')
  if (status.updateAvailable === false) return { ok: true, updateAvailable: false }
  if (!status.updateAvailable || !status.targetSha || !/^[0-9a-f]{40}$/i.test(status.targetSha)) {
    return fail('The update target could not be verified. Check for updates again.')
  }
  // This coordinator verifies and restarts the local messaging gateway as one transaction.
  if (deps.remoteGatewayActive()) {
    return fail(
      'Switch Hermes to its local connection, then update this app. The protected updater needs the local gateway.'
    )
  }
  const targetArgs = status.channel ? ['--channel', status.channel] : ['--branch', status.branch ?? 'main']
  const updateArgs = ['--yes', '--gateway', ...targetArgs]
  const runId = makeHandoffRunId()
  const env = {
    ...(await sourceUpdateEnvironment(deps.updateRoot, deps.hermesHome, deps.rememberLog)),
    HERMES_REPO: deps.updateRoot,
    HERMES_UPDATE_TARGET_SHA: status.targetSha,
    HERMES_UPDATE_CORRELATION_ID: runId,
    HERMES_UPDATE_STARTED_AT: String(Math.floor(Date.now() / 1000))
  }
  deps.emitUpdateProgress({
    stage: 'checking',
    message: 'Checking that the update can be installed safely…',
    percent: 8
  })
  try {
    await execute(coordinator, ['update', '--dry-run', '--source', 'desktop-preflight', '--', ...updateArgs], {
      cwd: deps.updateRoot,
      env,
      timeout: 900_000,
      maxBuffer: 1024 * 1024
    })
  } catch (error: unknown) {
    const code = error instanceof Error && 'code' in error ? String(error.code) : 'unavailable'
    let message = `The update check failed (exit ${code}). Hermes will stay open; try again after resolving the reported problem.`
    try {
      const report: unknown = JSON.parse(
        readFileSync(path.join(deps.hermesHome, 'migration', 'update-coordinator', 'last-status.json'), 'utf8')
      )
      if (
        report &&
        typeof report === 'object' &&
        'run_id' in report &&
        report.run_id === runId &&
        'detail' in report &&
        typeof report.detail === 'string' &&
        report.detail
      ) {
        message = `${report.detail.slice(0, 400)} Hermes will stay open.`
      }
    } catch {
      /* The failed process may not have published a status. */
    }
    deps.rememberLog(`[updates] coordinator preflight refused: ${code}`)
    return fail(message)
  }
  const raced = await updateHandoffConflict(deps.hermesHome)
  if (raced) return fail(raced.message)
  const child = spawnUpdaterProcess(
    coordinator,
    ['update', '--source', 'desktop-app', '--retry-once', '--', ...updateArgs],
    {
      cwd: deps.updateRoot,
      env: { ...env, HERMES_UPDATE_COORDINATOR_OWNS_DESKTOP: '1', HERMES_DESKTOP_CHILD_PID: String(process.pid) },
      detached: true,
      stdio: 'ignore'
    }
  )
  const handoff = await observeUpdaterHandoff(child, deps.dwellMs)
  if (!handoff.ok) return fail(handoff.message ?? 'The updater could not start. Hermes will stay open.')
  // The coordinator claims its marker before waiting for this app to quit.
  const claim = await waitForHandoffClaim(deps.hermesHome, process.pid)
  if (!claim.taken || claim.pid !== child.pid) {
    killHandoffTree(child)
    return fail('The updater did not take ownership. Hermes will stay open; try again.')
  }
  deps.emitUpdateProgress({
    stage: 'restart',
    message: 'Updating Hermes. The app will reopen automatically.',
    percent: 100
  })
  deps.quit()
  return { ok: true, handedOff: true, updater: coordinator }
}
