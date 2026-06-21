import { apiClient } from "@/shared/api/client";
import type { GeneratedModel } from "./model";

export async function getModels(): Promise<GeneratedModel[]> {
  return apiClient.get("models").json<GeneratedModel[]>();
}

export async function getModel(id: string): Promise<GeneratedModel> {
  return apiClient.get(`models/${id}`).json<GeneratedModel>();
}

export async function getModelByConversation(
  conversationId: string
): Promise<GeneratedModel | null> {
  try {
    return apiClient
      .get(`models/conversation/${conversationId}`)
      .json<GeneratedModel>();
  } catch {
    return null;
  }
}
