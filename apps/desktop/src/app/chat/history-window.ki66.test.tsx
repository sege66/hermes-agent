// ki66 (local-only): cron mirror cases for the bounded history runtime. The
// upstream history-window.test.tsx stays byte-identical; this file carries its
// own mount() with a QueryClientProvider seeded with cron deliveries.
import { useAssistantRuntime } from '@assistant-ui/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render } from '@testing-library/react'
import { atom } from 'nanostores'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { stubThreadEnvironment } from '@/components/assistant-ui/test-utils'
import { type TranscriptWindowValue, useTranscriptWindow } from '@/components/assistant-ui/thread/transcript-window'
import type { ChatMessage } from '@/lib/chat-messages'
import { $transcriptTailBySessionId } from '@/store/transcript-tail'

import { PRIMARY_SESSION_VIEW, SessionViewProvider } from './session-view'

import { ChatRuntimeBoundary } from '.'

stubThreadEnvironment()

const message = (rowId: number): ChatMessage => ({
  id: `live-${rowId}`,
  rowId,
  role: 'user',
  parts: [{ type: 'text', text: `prompt ${rowId}` }]
})

const page = (rowId: number) => ({
  session_id: 'stored',
  pagination: { has_older: true, has_newer: true, limit: 120, offset: 40, returned: 120, order: 'oldest' },
  messages: Array.from({ length: 120 }, (_, index) => ({
    id: rowId + index,
    role: 'user' as const,
    content: `prompt ${rowId + index}`,
    timestamp: rowId + index
  }))
})

beforeEach(() => {
  $transcriptTailBySessionId.set({})
  Object.defineProperty(window, 'hermesDesktop', { configurable: true, value: { api: vi.fn() } })
})

function mount(storedId = 'stored', withCron = false, source: null | string = null) {
  const $messages = atom(Array.from({ length: 120 }, (_, index) => message(10_000 + index)))

  const view = {
    ...PRIMARY_SESSION_VIEW,
    $messages,
    $runtimeId: atom<string | null>('runtime'),
    $storedId: atom<string | null>(storedId)
  }

  let window!: Required<TranscriptWindowValue>
  let runtime!: NonNullable<ReturnType<typeof useAssistantRuntime>>

  function Observe() {
    window = useTranscriptWindow()
    runtime = useAssistantRuntime()!

    return null
  }

  const mutations = { onEdit: vi.fn(), onReload: vi.fn(), onCancel: vi.fn(), onThreadMessagesChange: vi.fn() }

  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(['cron-deliveries'], withCron
    ? [{ ts: Date.now() / 1000, job_id: 'cron-test', job_name: 'Cron test', text: 'cron delivery' }]
    : [])
  // The source guard's lookup: a messaging source must keep the mirror off.
  queryClient.setQueryData(['cron-mirror-session-source', storedId], source)

  const rendered = render(
    <QueryClientProvider client={queryClient}>
      <SessionViewProvider value={view}>
        <ChatRuntimeBoundary busy={false} suppressMessages={false} {...mutations}>
          <Observe />
        </ChatRuntimeBoundary>
      </SessionViewProvider>
    </QueryClientProvider>
  )

  return {
    view,
    mutations,
    ...rendered,
    get window() {
      return window
    },
    get runtime() {
      return runtime
    }
  }
}

describe('bounded direct history runtime — cron mirror (ki66)', () => {
  it('keeps cron deliveries out of a messaging session and its history', async () => {
    vi.spyOn(window.hermesDesktop, 'api').mockResolvedValue(page(40))
    const mounted = mount('tg-session', true, 'telegram')
    const hasCron = () => mounted.runtime.thread.getState().messages.some(message => message.id.startsWith('__cron__'))
    expect(hasCron()).toBe(false)
    await act(async () => { await mounted.window.revealRow(40, new AbortController().signal) })
    expect(hasCron()).toBe(false)
    expect(mounted.view.$messages.get().some(message => message.id.startsWith('__cron__'))).toBe(false)
    act(() => { mounted.window.returnToLatest() })
    expect(hasCron()).toBe(false)
  })

  it('still shows the cron mirror on the local primary thread', async () => {
    vi.spyOn(window.hermesDesktop, 'api').mockResolvedValue(page(40))
    const mounted = mount('stored', true, 'tui')
    expect(mounted.runtime.thread.getState().messages.some(message => message.id.startsWith('__cron__'))).toBe(true)
  })
})
