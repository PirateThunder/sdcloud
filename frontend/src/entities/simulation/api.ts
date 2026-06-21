import { apiClient } from "@/shared/api/client";
import type { SimulationParams, SimulationResult } from "./model";

export async function runSimulation(
  params: SimulationParams
): Promise<SimulationResult> {
  return apiClient
    .post("simulation/run", { json: params })
    .json<SimulationResult>();
}

export async function getSimulation(id: string): Promise<SimulationResult> {
  return apiClient.get(`simulation/${id}`).json<SimulationResult>();
}

export async function getSimulationByModel(
  modelId: string
): Promise<SimulationResult[]> {
  return apiClient
    .get(`simulation/model/${modelId}`)
    .json<SimulationResult[]>();
}
