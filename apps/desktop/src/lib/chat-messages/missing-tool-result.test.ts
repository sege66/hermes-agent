import { describe, expect, it } from 'vitest'

import {
  applyStoredToolResultToParts,
  toolCallOwnerMessageId,
  toolEventOwnerMessageId,
  upsertToolPart
} from './tool-parts'
import type { ChatMessage } from './types'

const payload = { tool_id: 'tool-1', name: 'terminal', args: { command: 'true' } }

const message = (parts: ChatMessage['parts']): ChatMessage => ({
  id: 'original',
  role: 'assistant',
  interim: true,
  parts
})

describe('completion without a result', () => {
  it('reconciles a later result with the original tool row', () => {
    const parts = upsertToolPart([], payload, 'complete', 10)
    const complete = { ...payload, result: { exit_code: 0 } }
    expect(toolCallOwnerMessageId([message(parts)], complete, 'complete')).toBe('original')
    const updated = upsertToolPart(parts, complete, 'complete', 11)
    expect(updated).toHaveLength(1)
    expect(updated[0]).toMatchObject({ toolCallId: 'tool-1', result: { exit_code: 0 } })
  })

  it('accepts a stored result after a result-less completion', () => {
    const parts = upsertToolPart([], payload, 'complete', 10)

    const updated = applyStoredToolResultToParts(parts, {
      role: 'tool',
      tool_call_id: 'tool-1',
      content: '{"exit_code":0}',
      timestamp: 11
    })

    expect(updated).toHaveLength(1)
    expect(updated?.[0]).toMatchObject({ result: { exit_code: 0 } })
  })

  it('re-arms a late matching start without taking over an unrelated call', () => {
    const parts = upsertToolPart([], payload, 'complete', 10)
    const settled = { ...message(parts), interim: false }
    expect(toolEventOwnerMessageId([settled], payload, 'running', false)).toBe('original')
    expect(toolEventOwnerMessageId([settled], { ...payload, args: { command: 'false' } }, 'running', false)).toBeNull()
    expect(toolEventOwnerMessageId([settled], { ...payload, tool_id: 'other' }, 'complete', false)).toBeNull()
  })

  it.each([null, false, 0, '', {}])('preserves an actual result %j through an incomplete replay', result => {
    const parts = upsertToolPart([], { ...payload, result }, 'complete', 10)
    const replayed = upsertToolPart(parts, payload, 'complete', 11)
    expect(replayed).toHaveLength(1)
    expect(replayed[0]).toMatchObject({ result })
    expect(toolCallOwnerMessageId([message(replayed)], payload, 'complete')).toBeNull()
  })
})
