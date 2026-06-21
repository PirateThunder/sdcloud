import { apiClient } from "@/shared/api/client";
import type {
  Conversation,
  Message,
  SendMessageRequest,
  SendMessageResponse,
  CreateConversationRequest,
} from "./model";

export async function getConversations(): Promise<Conversation[]> {
  return apiClient.get("conversations").json<Conversation[]>();
}

export async function getConversation(id: string): Promise<Conversation> {
  return apiClient.get(`conversations/${id}`).json<Conversation>();
}

export async function createConversation(
  data: CreateConversationRequest = {}
): Promise<Conversation> {
  return apiClient
    .post("conversations", { json: data })
    .json<Conversation>();
}

export async function deleteConversation(id: string): Promise<void> {
  await apiClient.delete(`conversations/${id}`);
}

export async function getMessages(conversationId: string): Promise<Message[]> {
  return apiClient
    .get(`conversations/${conversationId}/messages`)
    .json<Message[]>();
}

export async function sendMessage(
  conversationId: string,
  data: SendMessageRequest
): Promise<SendMessageResponse> {
  return apiClient
    .post(`conversations/${conversationId}/send`, { json: data })
    .json<SendMessageResponse>();
}
