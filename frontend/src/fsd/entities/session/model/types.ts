import { z } from 'zod'

export const userSchema = z.object({
  id: z.string(),
  email: z.string(),
  display_name: z.string(),
  email_verified_at: z.string().nullable(),
  created_at: z.string(),
})
export type User = z.infer<typeof userSchema>

export const authResponseSchema = z.object({
  user: userSchema,
  access_token: z.string(),
  expires_in: z.number(),
})
export type AuthResponse = z.infer<typeof authResponseSchema>

export const otpRequestSchema = z.object({
  detail: z.string(),
  retry_after: z.number(),
  dev_code: z.string().nullable().optional(),
})
export type OtpRequest = z.infer<typeof otpRequestSchema>
