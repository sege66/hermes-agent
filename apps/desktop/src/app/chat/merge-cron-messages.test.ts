import { describe, expect, it } from 'vitest'

import { textPart, type ChatMessage } from '@/lib/chat-messages'

import { mergeCronMessages } from './merge-cron-messages'

function message(id: string, text: string, timestamp: number): ChatMessage {
  return { id, role: 'assistant', timestamp, parts: [textPart(text)] }
}

describe('mergeCronMessages', () => {
  it('interleaves cron deliveries by timestamp', () => {
    const local = [message('local', 'local', 20)]
    const cron = [message('__cron__brief__10', '🤖 brief\n\ncron', 10)]

    expect(mergeCronMessages(local, cron).map(item => item.id)).toEqual(['__cron__brief__10', 'local'])
  })

  it('dedupes a delivery whose body already exists locally', () => {
    const local = [message('local', 'same text', 10)]
    const cron = [message('__cron__brief__20', '🤖 brief\n\nsame text', 20)]

    expect(mergeCronMessages(local, cron)).toBe(local)
  })
})
