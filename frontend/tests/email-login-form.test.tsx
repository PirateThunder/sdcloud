import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { authEmailRequest, authEmailVerify } from '@/fsd/entities/session/api/auth-api'
import { useSession } from '@/fsd/entities/session/model/session-store'
import { EmailLoginForm } from '@/fsd/features/auth/email-login-form'

const replace = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace }) }))
vi.mock('@/fsd/entities/session/api/auth-api', () => ({
  authEmailRequest: vi.fn(),
  authEmailVerify: vi.fn(),
}))

const authResponse = {
  user: {
    id: 'user-1',
    email: 'user@example.com',
    display_name: 'user',
    email_verified_at: '2026-01-01T00:00:00Z',
    created_at: '2026-01-01T00:00:00Z',
  },
  access_token: 'token',
  expires_in: 900,
}

describe('EmailLoginForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useSession.getState().clear()
    vi.mocked(authEmailRequest).mockResolvedValue({
      detail: 'sent',
      retry_after: 60,
      dev_code: '123456',
    })
    vi.mocked(authEmailVerify).mockResolvedValue(authResponse)
  })

  it('runs email request, local code and verify in one flow', async () => {
    const user = userEvent.setup()
    render(<EmailLoginForm />)
    await user.type(screen.getByLabelText('Email'), 'user@example.com')
    await user.click(screen.getByRole('button', { name: 'Получить код' }))
    expect(authEmailRequest).toHaveBeenCalledWith('user@example.com')
    expect(await screen.findByLabelText('Код из письма')).toHaveValue('123456')
    await user.click(screen.getByRole('button', { name: 'Войти в sdCloud' }))
    expect(authEmailVerify).toHaveBeenCalledWith('user@example.com', '123456')
    expect(useSession.getState().status).toBe('auth')
    expect(useSession.getState().accessToken).toBe('token')
    expect(replace).toHaveBeenCalledWith('/chat')
  })
})
