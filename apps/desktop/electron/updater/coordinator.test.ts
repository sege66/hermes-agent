import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'

import { afterEach, expect, it, vi } from 'vitest'

import * as markers from '../update-marker'
import * as processes from '../updater-process'

import * as source from './checkout-source'
import { type CoordinatorDeps, handOffMacUpdateToCoordinator } from './coordinator'

const roots: string[] = []
afterEach(() => {
  vi.restoreAllMocks()
  for (const root of roots.splice(0)) fs.rmSync(root, { recursive: true, force: true })
})

function fixture(): CoordinatorDeps {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'protected-click-'))
  roots.push(home)
  fs.mkdirSync(path.join(home, 'bin'))
  fs.mkdirSync(path.join(home, 'hermes-agent'))
  fs.writeFileSync(path.join(home, 'bin', 'hermes-update-coordinator'), '#!/bin/sh\nexit 0\n', { mode: 0o755 })
  vi.spyOn(source, 'sourceUpdateEnvironment').mockResolvedValue({ PATH: process.env.PATH })
  vi.spyOn(processes, 'spawnUpdaterProcess').mockReturnValue({ pid: process.ppid, unref: () => {} })
  vi.spyOn(processes, 'observeUpdaterHandoff').mockResolvedValue({ ok: true })
  vi.spyOn(processes, 'killHandoffTree').mockImplementation(() => {})
  vi.spyOn(markers, 'waitForHandoffClaim').mockResolvedValue({ taken: true, pid: process.ppid })
  vi.spyOn(markers, 'writeUpdateMarker').mockResolvedValue({ ok: true })
  return {
    hermesHome: home,
    updateRoot: path.join(home, 'hermes-agent'),
    isMac: true,
    appBundle: '/Applications/Hermes.app',
    dwellMs: 0,
    check: vi.fn(async () => ({
      supported: true,
      updateAvailable: true,
      channel: 'stable',
      targetSha: 'a'.repeat(40)
    })),
    remoteGatewayActive: () => false,
    emitUpdateProgress: vi.fn(),
    rememberLog: vi.fn(),
    quit: vi.fn()
  }
}

it('a fresh current result leaves the app open without starting an updater', async () => {
  const deps = fixture()
  deps.check = vi.fn(async () => ({ supported: true, updateAvailable: false }))
  expect(await handOffMacUpdateToCoordinator(deps)).toMatchObject({ ok: true, updateAvailable: false })
  expect(processes.spawnUpdaterProcess).not.toHaveBeenCalled()
  expect(deps.quit).not.toHaveBeenCalled()
})

it('uses the checked target once for the protected local installation', async () => {
  const deps = fixture()
  const probe = path.join(deps.hermesHome, 'preflight')
  fs.writeFileSync(
    path.join(deps.hermesHome, 'bin', 'hermes-update-coordinator'),
    `#!/bin/sh\nprintf '%s\\n' "$HERMES_UPDATE_TARGET_SHA" "$@" > '${probe}'\n`,
    { mode: 0o755 }
  )
  expect(await handOffMacUpdateToCoordinator(deps)).toMatchObject({ ok: true, handedOff: true })
  expect(fs.readFileSync(probe, 'utf8')).toContain('a'.repeat(40))
  expect(fs.readFileSync(probe, 'utf8')).toContain('--channel\nstable')
  expect(processes.spawnUpdaterProcess).toHaveBeenCalledTimes(1)
  const [, args, options] = vi.mocked(processes.spawnUpdaterProcess).mock.calls[0]!
  expect(args).toContain('--channel')
  expect(args).toContain('stable')
  expect(args).not.toContain('--force')
  expect(args).toContain('--gateway')
  expect(options.env?.HERMES_UPDATE_TARGET_SHA).toBe('a'.repeat(40))
  expect(deps.quit).toHaveBeenCalledOnce()
})

it('a remote connection cannot start the local-only protected transaction', async () => {
  const deps = fixture()
  deps.remoteGatewayActive = () => true
  expect(await handOffMacUpdateToCoordinator(deps)).toMatchObject({
    ok: false,
    message: expect.stringContaining('local connection')
  })
  expect(processes.spawnUpdaterProcess).not.toHaveBeenCalled()
  expect(deps.quit).not.toHaveBeenCalled()
})

it('a foreign or missing marker claim never closes the app', async () => {
  const deps = fixture()
  vi.mocked(markers.waitForHandoffClaim).mockResolvedValue({ taken: false })
  expect(await handOffMacUpdateToCoordinator(deps)).toMatchObject({ ok: false })
  expect(deps.quit).not.toHaveBeenCalled()
  expect(processes.killHandoffTree).toHaveBeenCalledOnce()
})

it('does not intercept a different checkout sharing the same profile', async () => {
  const deps = fixture()
  deps.updateRoot = deps.hermesHome
  expect(await handOffMacUpdateToCoordinator(deps)).toBeNull()
  expect(processes.spawnUpdaterProcess).not.toHaveBeenCalled()
})

it('preflight yields to the event loop and reports its real refusal without quitting', async () => {
  const deps = fixture()
  fs.mkdirSync(path.join(deps.hermesHome, 'migration', 'update-coordinator'), { recursive: true })
  fs.writeFileSync(path.join(deps.hermesHome, 'bin', 'hermes-update-coordinator'), '#!/bin/sh\nsleep 2\nexit 92\n')
  let settled = false
  const pending = handOffMacUpdateToCoordinator(deps)
  void pending.then(() => {
    settled = true
  })
  await new Promise<void>(resolve => setImmediate(resolve))
  expect(settled).toBe(false)
  const result = await pending
  expect(result).toMatchObject({ ok: false })
  expect(result?.message).toContain('92')
  expect(deps.quit).not.toHaveBeenCalled()
  expect(processes.spawnUpdaterProcess).not.toHaveBeenCalled()
})

it.each([
  { supported: true, updateAvailable: true, targetSha: 'HEAD' },
  { supported: true, error: 'offline', message: 'Release server unavailable.' }
])('invalid or failed checks keep the app open', async status => {
  const deps = fixture()
  deps.check = async () => status
  expect(await handOffMacUpdateToCoordinator(deps)).toMatchObject({ ok: false })
  expect(processes.spawnUpdaterProcess).not.toHaveBeenCalled()
  expect(deps.quit).not.toHaveBeenCalled()
})

it('a failed updater spawn leaves the app open', async () => {
  const deps = fixture()
  vi.mocked(processes.observeUpdaterHandoff).mockResolvedValue({ ok: false, message: 'updater spawn failed: ENOENT' })
  expect(await handOffMacUpdateToCoordinator(deps)).toMatchObject({ ok: false })
  expect(deps.quit).not.toHaveBeenCalled()
})
