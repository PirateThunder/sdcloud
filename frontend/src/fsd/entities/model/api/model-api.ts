import { z } from 'zod'

import { api } from '@/fsd/shared/api/http'

import {
  type ExportFormat,
  type ModelListItem,
  type ModelVersion,
  type ModelVersionDetail,
  modelListItemSchema,
  modelVersionDetailSchema,
  modelVersionSchema,
} from '../model/types'

export async function listModels(): Promise<ModelListItem[]> {
  const data = await api.get('models').json()
  return z.object({ items: z.array(modelListItemSchema), total: z.number() }).parse(data).items
}

export async function getModel(id: string): Promise<ModelListItem> {
  const data = await api.get(`models/${id}`).json()
  return modelListItemSchema.parse(data)
}

export async function deleteModel(id: string): Promise<void> {
  await api.delete(`models/${id}`)
}

export async function listModelVersions(modelId: string): Promise<ModelVersion[]> {
  const data = await api.get(`models/${modelId}/versions`).json()
  return z.object({ items: z.array(modelVersionSchema), total: z.number() }).parse(data).items
}

export async function getModelVersion(id: string): Promise<ModelVersionDetail> {
  const data = await api.get(`model-versions/${id}`).json()
  return modelVersionDetailSchema.parse(data)
}

export function exportPath(modelId: string, version: number, format: ExportFormat): string {
  return `models/${modelId}/versions/${version}/export?format=${format}`
}

export async function getExportText(
  modelId: string,
  version: number,
  format: ExportFormat,
): Promise<string> {
  return api.get(exportPath(modelId, version, format)).text()
}
