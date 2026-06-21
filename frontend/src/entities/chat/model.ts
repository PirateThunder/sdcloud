import type { GeneratedModel } from "@/entities/model/model";

export type MessageRole = "user" | "assistant" | "system";

export interface Conversation {
  id: string;
  title: string;
  model_type: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  model_metadata?: {
    generated_model?: GeneratedModel;
    model_id?: string;
  };
  tokens_used?: number;
  created_at: string;
}

export interface SendMessageRequest {
  content: string;
  conversation_id?: string;
  model_type?: string;
}

export interface SendMessageResponse {
  message: Message;
  model?: GeneratedModel;
}

export interface CreateConversationRequest {
  title?: string;
  model_type?: string;
}
