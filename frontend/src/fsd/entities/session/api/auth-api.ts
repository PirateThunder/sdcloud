import { api } from '@/fsd/shared/api/http'

import {
  type AuthResponse,
  authResponseSchema,
  type OtpRequest,
  otpRequestSchema,
  type User,
  userSchema,
} from '../model/types'

export async function authEmailRequest(email: string): Promise<OtpRequest> {
  const data = await api.post('auth/email/request', { json: { email } }).json()
  return otpRequestSchema.parse(data)
}

export async function authEmailVerify(email: string, code: string): Promise<AuthResponse> {
  const data = await api.post('auth/email/verify', { json: { email, code } }).json()
  return authResponseSchema.parse(data)
}

export async function fetchMe(): Promise<User> {
  const data = await api.get('auth/me').json()
  return userSchema.parse(data)
}

export async function logout(): Promise<void> {
  await api.post('auth/logout', { retry: 0 })
}
