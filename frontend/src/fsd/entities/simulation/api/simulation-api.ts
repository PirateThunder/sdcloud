import { z } from 'zod'

import { api } from '@/fsd/shared/api/http'

import { type Simulation, type SimulationParameters, simulationSchema } from '../model/types'

export async function createSimulation(
  versionId: string,
  parameters: SimulationParameters,
  idempotencyKey: string,
): Promise<Simulation> {
  const data = await api
    .post(`model-versions/${versionId}/simulations`, {
      json: { parameters },
      headers: { 'Idempotency-Key': idempotencyKey },
    })
    .json()
  return simulationSchema.parse(data)
}

export async function getSimulation(id: string): Promise<Simulation> {
  const data = await api.get(`simulations/${id}`).json()
  return simulationSchema.parse(data)
}

export async function listSimulations(versionId: string): Promise<Simulation[]> {
  const data = await api.get(`model-versions/${versionId}/simulations`).json()
  return z.array(simulationSchema).parse(data)
}

export async function retrySimulation(id: string): Promise<Simulation> {
  const data = await api.post(`simulations/${id}/retry`).json()
  return simulationSchema.parse(data)
}
