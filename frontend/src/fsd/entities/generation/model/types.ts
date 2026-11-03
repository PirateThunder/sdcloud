import { z } from 'zod'

export const generationStatusSchema = z.enum(['queued', 'submitted', 'running', 'done', 'error'])
export type GenerationStatus = z.infer<typeof generationStatusSchema>

export const generationSchema = z.object({
  id: z.string(),
  conversation_id: z.string(),
  user_message_id: z.string(),
  assistant_message_id: z.string(),
  retry_of_id: z.string().nullable(),
  status: generationStatusSchema,
  stage: z.string().nullable(),
  error: z.string().nullable(),
  attempt: z.number(),
  model_version_id: z.string().nullable(),
  created_at: z.string(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
})
export type Generation = z.infer<typeof generationSchema>
