import { describe, expect, it, vi } from 'vitest'

import { externalSessionReplacement, refreshExternalSessionUpdate } from './wiring'

describe('externalSessionReplacement', () => {
  it('follows the replacement only when the selected stored session matches the previous id', () => {
    expect(
      externalSessionReplacement('sess-old', {
        previous_session_id: 'sess-old',
        stored_session_id: 'sess-new'
      })
    ).toBe('sess-new')
  })

  it('does not steal selection from another stored session', () => {
    expect(
      externalSessionReplacement('sess-other', {
        previous_session_id: 'sess-old',
        stored_session_id: 'sess-new'
      })
    ).toBeNull()
  })

  it('rejects missing and malformed session ids', () => {
    expect(externalSessionReplacement('sess-old', { stored_session_id: 'sess-new' })).toBeNull()
    expect(externalSessionReplacement('sess-old', { previous_session_id: 4, stored_session_id: false })).toBeNull()
    expect(externalSessionReplacement('sess-old', null)).toBeNull()
  })

  it('resumes a reset replacement without refreshing the ended previous transcript', async () => {
    const refreshActiveTranscript = vi.fn().mockRejectedValue(new Error('previous session ended'))
    const refreshMessagingSessions = vi.fn().mockResolvedValue(undefined)
    const resumeSession = vi.fn().mockResolvedValue(undefined)

    await refreshExternalSessionUpdate('sess-new', {
      refreshActiveTranscript,
      refreshMessagingSessions,
      resumeSession
    }).catch(() => undefined)

    expect(refreshMessagingSessions).toHaveBeenCalledOnce()
    expect(refreshActiveTranscript).not.toHaveBeenCalled()
    expect(resumeSession).toHaveBeenCalledWith('sess-new', true)
  })
})
