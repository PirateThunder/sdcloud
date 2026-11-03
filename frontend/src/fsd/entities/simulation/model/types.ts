import { z } from 'zod'

export const simulationResultSchema = z.looseObject({
  schema_version: z.string(),
  model_id: z.string(),
  model_hash: z.string(),
  time: z.array(z.number()),
  variables: z.record(z.string(), z.array(z.number())),
  requested_engine: z.string(),
  engine: z.string(),
  requested_method: z.string(),
  integration_method: z.string(),
  time_step: z.number(),
  saveper: z.number(),
  fallback_reason: z.string().nullable(),
  warnings: z.array(z.string()),
})
export type SimulationResult = z.infer<typeof simulationResultSchema>

export const simulationSchema = z.object({
  id: z.string(),
  model_version_id: z.string(),
  retry_of_id: z.string().nullable(),
  status: z.enum(['queued', 'submitted', 'running', 'done', 'error']),
  stage: z.string().nullable(),
  parameters: z.record(z.string(), z.unknown()),
  result: simulationResultSchema.nullable(),
  requested_engine: z.string().nullable(),
  engine: z.string().nullable(),
  requested_method: z.string().nullable(),
  integration_method: z.string().nullable(),
  fallback_reason: z.string().nullable(),
  error: z.string().nullable(),
  attempt: z.number(),
  created_at: z.string(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
})
export type Simulation = z.infer<typeof simulationSchema>

export interface SimulationParameters {
  engine?: 'auto' | 'pysd' | 'scipy'
  integration_method?: 'euler' | 'rk4' | 'rk45' | 'dop853' | 'lsoda' | 'bdf'
  initial_time?: number | null
  final_time?: number | null
  time_step?: number | null
  saveper?: number | null
  parameters?: Record<string, number>
  stock_initial?: Record<string, number>
  input_series?: Record<string, unknown>
  rtol?: number
  atol?: number
}
