import { z } from 'zod'

export const conversationSchema = z.object({
  id: z.string(),
  title: z.string(),
  last_message_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
})
export type Conversation = z.infer<typeof conversationSchema>

export const messageSchema = z.object({
  id: z.string(),
  role: z.enum(['user', 'assistant']),
  content: z.string(),
  status: z.string(),
  generation_id: z.string().nullable().optional(),
  model_version_id: z.string().nullable().optional(),
  created_at: z.string(),
})
export type Message = z.infer<typeof messageSchema>

export const messageAcceptedSchema = z.object({
  user_message: messageSchema,
  assistant_message: messageSchema,
  generation_id: z.string(),
  status: z.string(),
})
export type MessageAccepted = z.infer<typeof messageAcceptedSchema>
