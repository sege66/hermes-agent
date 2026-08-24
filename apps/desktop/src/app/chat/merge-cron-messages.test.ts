import { describe, expect, it } from 'vitest'

import { chatMessageText, preserveLocalAssistantErrors, textPart, toChatMessages, type ChatMessage } from '@/lib/chat-messages'
import type { SessionMessage } from '@/types/hermes'

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

  it('keeps local order even when a local timestamp is out of sequence', () => {
    // The hydration reconciler can hand a later message an earlier timestamp;
    // local order (durable row order) must win, cron goes by time.
    const local = [message('a', 'a', 10), message('b', 'b', 30), message('c', 'c', 15)]
    const cron = [message('__cron__x__20', '🤖 x\n\ncron20', 20), message('__cron__y__40', '🤖 y\n\ncron40', 40)]

    expect(mergeCronMessages(local, cron).map(item => item.id)).toEqual(['a', '__cron__x__20', 'b', 'c', '__cron__y__40'])
  })
})

// Real rows from state.db session 20260824_225812_00c47098 (2026-08-24): a
// Telegram greeting answered twice with the identical sentence, 25 minutes
// apart. The second reply rendered right under the first one.
const REPLY = '대표님, 안녕하세요. 자비스가 대기 중입니다.'
const rows = [
  { id: 39208, role: 'user', content: 'hi', timestamp: 1787580276.0 },
  { id: 39209, role: 'assistant', content: REPLY, timestamp: 1787580281.485 },
  { id: 39211, role: 'user', content: '내일 웰링턴 골프인데 날씨 알려줘', timestamp: 1787581467.167 },
  { id: 39216, role: 'assistant', content: '대표님, 내일 8월 25일 웰링턴CC는 흐림', timestamp: 1787581501.03 },
  { id: 39217, role: 'user', content: '안녕', timestamp: 1787581744.0 },
  { id: 39218, role: 'assistant', content: REPLY, timestamp: 1787581748.448 }
] as unknown as SessionMessage[]

const heads = (messages: ChatMessage[]) => messages.map(m => chatMessageText(m).split('\n')[0])

describe('external refresh with a repeated identical reply', () => {
  it('keeps the later reply after its own user turn (reconcile + cron merge)', () => {
    const current = toChatMessages(rows.slice(0, 4)) // before "안녕" arrived
    const next = toChatMessages(rows) // refreshed tail after the Telegram turn
    const reconciled = preserveLocalAssistantErrors(next, current)
    const cron = [message('__cron__journal__1787577895', '🤖 하루 마감 자동 저널\n\n📝 오늘의 저널', 1787577895.5)]

    expect(reconciled[reconciled.length - 1].timestamp).toBe(1787581748.448)
    expect(heads(mergeCronMessages(reconciled, cron))).toEqual([
      '🤖 하루 마감 자동 저널', 'hi', REPLY, '내일 웰링턴 골프인데 날씨 알려줘', '대표님, 내일 8월 25일 웰링턴CC는 흐림', '안녕', REPLY
    ])
  })
})
