import { z } from 'zod'

export const variableSchema = z.looseObject({
  id: z.string(),
  label: z.string().nullable().optional(),
  kind: z.enum(['stock', 'flow', 'auxiliary', 'constant']),
  units: z.record(z.string(), z.number()).nullable().optional(),
  subscripts: z.array(z.string()).optional(),
  initial: z.unknown().optional(),
  expression: z.unknown().optional(),
  derivative: z.unknown().optional(),
  source: z.unknown().optional(),
  target: z.unknown().optional(),
  bounds: z.unknown().optional(),
})
export type SDVariable = z.infer<typeof variableSchema>

export const graphSchema = z.looseObject({
  nodes: z.array(z.looseObject({ id: z.string(), label: z.string(), type: z.string() })),
  edges: z.array(
    z.looseObject({
      source: z.string(),
      target: z.string(),
      type: z.string().optional(),
      polarity: z.string().optional(),
      label: z.string().nullable().optional(),
    }),
  ),
})
export type ModelGraph = z.infer<typeof graphSchema>

export const modelDocumentSchema = z.looseObject({
  schema_version: z.string(),
  id: z.string(),
  name: z.string(),
  description: z.string(),
  time: z.looseObject({
    unit: z.string(),
    initial_time: z.number(),
    final_time: z.number(),
    time_step: z.number(),
    saveper: z.number(),
  }),
  variables: z.array(variableSchema),
  tables: z.array(z.unknown()).optional(),
  dimensions: z.array(z.unknown()).optional(),
  assumptions: z
    .array(
      z.looseObject({
        rationale: z.string().optional(),
        requires_confirmation: z.boolean().optional(),
      }),
    )
    .optional(),
  validation: z
    .looseObject({ status: z.string(), issues: z.array(z.unknown()).optional() })
    .optional(),
  cld_data: graphSchema.optional(),
  sfd_data: graphSchema.optional(),
  artifacts: z.record(z.string(), z.string()).optional(),
  assistant_text: z.string().nullable().optional(),
  warnings: z.array(z.string()).optional(),
})
export type ModelDocument = z.infer<typeof modelDocumentSchema>

export const modelListItemSchema = z.object({
  id: z.string(),
  conversation_id: z.string(),
  name: z.string(),
  kind: z.string(),
  latest_version: z.number(),
  latest_version_id: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
})
export type ModelListItem = z.infer<typeof modelListItemSchema>

export const modelVersionSchema = z.object({
  id: z.string(),
  model_id: z.string(),
  generation_id: z.string().nullable(),
  version: z.number(),
  name: z.string(),
  model_hash: z.string(),
  created_at: z.string(),
})
export type ModelVersion = z.infer<typeof modelVersionSchema>

export const modelVersionDetailSchema = modelVersionSchema.extend({
  document: modelDocumentSchema,
  available_exports: z.array(z.string()),
})
export type ModelVersionDetail = z.infer<typeof modelVersionDetailSchema>

export type ExportFormat = 'python' | 'vensim' | 'xmile'
