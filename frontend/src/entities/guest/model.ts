import type { GeneratedModel } from "@/entities/model/model";

export type GuestMessageRole = "user" | "assistant" | "system";

export interface GuestMessage {
  role: GuestMessageRole;
  content: string;
}

export interface GuestChatRequest {
  messages: GuestMessage[];
  content: string;
}

export interface GuestAssistantMessage {
  id: string;
  role: GuestMessageRole;
  content: string;
  model_metadata?: {
    generated_model?: GeneratedModel;
    model_id?: string;
    variables_count?: number;
    equations_count?: number;
    cld_valid?: boolean;
    sfd_valid?: boolean;
    feedback_loops?: unknown[];
    generation_log?: string[];
    status?: string;
    error?: string;
  };
  tokens_used?: number;
  created_at: string;
}

export interface GuestChatResponse {
  message: GuestAssistantMessage;
  model?: GeneratedModel;
}

export interface GuestSimulationParameters {
  time_start: number;
  time_end: number;
  time_step: number;
  custom_params: Record<string, number>;
}

export interface GuestSimulationRequest {
  python_code?: string;
  vensim_code?: string;
  parameters: GuestSimulationParameters;
}

export interface GuestSimulationResult {
  time: number[];
  variables: Record<string, number[]>;
}

export interface GuestSimulationResponse {
  status: "completed" | "error" | "pending" | "running";
  results?: GuestSimulationResult;
  error?: string;
}
