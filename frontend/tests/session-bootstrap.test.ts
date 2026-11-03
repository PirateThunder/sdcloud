import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchMe } from '@/fsd/entities/session/api/auth-api'
import { useSession } from '@/fsd/entities/session/model/session-store'
import { bootstrapSession } from '@/fsd/features/auth/session-bootstrap'
import { refreshSession } from '@/fsd/shared/api/http'

vi.mock('@/fsd/shared/api/http', () => ({ refreshSession: vi.fn() }))
vi.mock('@/fsd/entities/session/api/auth-api', () => ({ fetchMe: vi.fn() }))

const user = {
  id: 'user-1',
  email: 'user@example.com',
  display_name: 'user',
  email_verified_at: '2026-01-01T00:00:00Z',
  created_at: '2026-01-01T00:00:00Z',
}

describe('bootstrapSession', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useSession.setState({ user: null, accessToken: null, expiresAt: 0, status: 'unknown' })
    vi.mocked(refreshSession).mockResolvedValue(true)
    vi.mocked(fetchMe).mockResolvedValue(user)
  })

  it('marks a restored session as authenticated', async () => {
    await bootstrapSession()
    expect(refreshSession).toHaveBeenCalledOnce()
    expect(fetchMe).toHaveBeenCalledOnce()
    expect(useSession.getState().status).toBe('auth')
    expect(useSession.getState().user).toEqual(user)
  })

  it('marks a missing refresh session as anonymous', async () => {
    vi.mocked(refreshSession).mockResolvedValue(false)
    await bootstrapSession()
    expect(fetchMe).not.toHaveBeenCalled()
    expect(useSession.getState().status).toBe('anonymous')
  })
})
