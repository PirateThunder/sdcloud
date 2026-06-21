import { publicClient } from "@/shared/api/client";
import type {
  GuestChatRequest,
  GuestChatResponse,
  GuestSimulationRequest,
  GuestSimulationResponse,
} from "./model";

export async function sendGuestChat(
  data: GuestChatRequest
): Promise<GuestChatResponse> {
  // Model generation can take 60-90 seconds through the full pipeline.
  return publicClient
    .post("guest/chat", { json: data, timeout: 180000 })
    .json<GuestChatResponse>();
}

export async function runGuestSimulation(
  data: GuestSimulationRequest
): Promise<GuestSimulationResponse> {
  return publicClient
    .post("guest/simulate", { json: data, timeout: 120000 })
    .json<GuestSimulationResponse>();
}
