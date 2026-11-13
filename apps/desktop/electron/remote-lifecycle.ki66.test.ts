import { expect, test } from 'vitest'

import { pidIsOurDashboard } from './remote-lifecycle'
import { withDarwinArgvProbe } from './remote-lifecycle.ki66'

// Pins the anchors withDarwinArgvProbe relies on: if upstream reshapes the
// argv-read block, the patch silently stops applying and this fails.
test('the ownership probe reads darwin argv with sysctl instead of ps', async () => {
  const commands: string[] = []

  const ssh = {
    exec: async (command: string) => {
      commands.push(command)

      return 'FOREIGN\n'
    }
  }

  expect(await pidIsOurDashboard(ssh, 4242, '0123456789abcdef', '/x/hermes')).toBe(false)
  expect(commands).toHaveLength(1)
  expect(commands[0]).toContain('if sys.platform=="darwin":')
  expect(commands[0]).toContain('libc.sysctl(mib,3,buf,ctypes.byref(size),None,0)')
  expect(commands[0]).toContain('except (OSError,ValueError):')
  expect(commands[0]).toContain('import os,sys\n')
  expect(commands[0]).not.toContain('subprocess')
  expect(commands[0]).not.toContain('shlex')
})

test('an unrecognised script is returned unchanged', () => {
  expect(withDarwinArgvProbe('import os\nprint("x")')).toBe('import os\nprint("x")')
})
