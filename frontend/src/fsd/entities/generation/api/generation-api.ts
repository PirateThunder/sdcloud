import { api } from '@/fsd/shared/api/http'

import { type Generation, generationSchema } from '../model/types'

export async function getGeneration(id: string): Promise<Generation> {
  const data = await api.get(`generations/${id}`).json()
  return generationSchema.parse(data)
}

export async function retryGeneration(id: string): Promise<Generation> {
  const data = await api.post(`generations/${id}/retry`).json()
  return generationSchema.parse(data)
}
