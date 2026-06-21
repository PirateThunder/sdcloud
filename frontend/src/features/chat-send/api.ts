import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getConversations,
  getMessages,
  createConversation,
  sendMessage,
  deleteConversation,
} from "@/entities/chat/api";
import { sendGuestChat } from "@/entities/guest/api";
import { useAuthStore } from "@/features/auth/model";
import { useChatStore } from "./model";
import type { Conversation, Message } from "@/entities/chat/model";

const CONVERSATION_KEYS = {
  all: ["conversations"] as const,
  list: () => [...CONVERSATION_KEYS.all, "list"] as const,
  detail: (id: string) => [...CONVERSATION_KEYS.all, "detail", id] as const,
  messages: (id: string) =>
    [...CONVERSATION_KEYS.all, "messages", id] as const,
};

export function useConversations() {
  const { isAuthenticated } = useAuthStore();

  return useQuery({
    queryKey: CONVERSATION_KEYS.list(),
    queryFn: getConversations,
    enabled: isAuthenticated,
    staleTime: 1000 * 60 * 2,
  });
}

export function useConversationMessages(conversationId: string | null) {
  return useQuery({
    queryKey: CONVERSATION_KEYS.messages(conversationId || ""),
    queryFn: () => {
      if (!conversationId) return Promise.resolve([] as Message[]);
      return getMessages(conversationId);
    },
    enabled: !!conversationId,
    staleTime: 1000 * 30,
  });
}

export function useCreateConversation() {
  const queryClient = useQueryClient();
  const { setCurrentConversation, setMessages } = useChatStore();

  return useMutation({
    mutationFn: createConversation,
    onSuccess: (conversation: Conversation) => {
      setCurrentConversation(conversation);
      setMessages([]);
      queryClient.invalidateQueries({
        queryKey: CONVERSATION_KEYS.list(),
      });
    },
  });
}

export function useDeleteConversation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteConversation,
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: CONVERSATION_KEYS.list(),
      });
    },
  });
}

export function useSendMessage() {
  const queryClient = useQueryClient();
  const { addMessage, setIsSubmitting, setCurrentModel, currentConversation } =
    useChatStore();

  return useMutation({
    mutationFn: async ({
      conversationId,
      content,
    }: {
      conversationId: string;
      content: string;
    }) => {
      setIsSubmitting(true);
      // Add user message immediately
      const userMessage: Message = {
        id: `temp-${Date.now()}`,
        conversation_id: conversationId,
        role: "user",
        content,
        created_at: new Date().toISOString(),
      };
      addMessage(userMessage);

      return sendMessage(conversationId, { content });
    },
    onSuccess: (response) => {
      addMessage(response.message);
      if (response.model) {
        setCurrentModel(response.model);
      }

      // Invalidate queries
      if (currentConversation) {
        queryClient.invalidateQueries({
          queryKey: CONVERSATION_KEYS.messages(currentConversation.id),
        });
      }
      queryClient.invalidateQueries({
        queryKey: CONVERSATION_KEYS.list(),
      });
    },
    onSettled: () => {
      setIsSubmitting(false);
    },
  });
}

export function useSendGuestMessage() {
  const { addMessage, setIsSubmitting, setCurrentModel } = useChatStore();

  return useMutation({
    mutationFn: async ({ content }: { content: string }) => {
      setIsSubmitting(true);

      // Add user message immediately
      const userMessage: Message = {
        id: `guest-user-${Date.now()}`,
        conversation_id: "guest",
        role: "user",
        content,
        created_at: new Date().toISOString(),
      };
      addMessage(userMessage);

      // Build history from current store messages (must read after addMessage)
      const currentMessages = useChatStore.getState().messages;
      const history = currentMessages.map((msg) => ({
        role: msg.role as "user" | "assistant" | "system",
        content: msg.content,
      }));

      return sendGuestChat({ messages: history, content });
    },
    onSuccess: (response) => {
      const assistantMessage: Message = {
        id: response.message.id,
        conversation_id: "guest",
        role: "assistant",
        content: response.message.content,
        model_metadata: response.model
          ? {
              generated_model: response.model,
              model_id: response.model.id,
              variables_count: response.message.model_metadata?.variables_count,
              equations_count: response.message.model_metadata?.equations_count,
              cld_valid: response.message.model_metadata?.cld_valid,
              sfd_valid: response.message.model_metadata?.sfd_valid,
              feedback_loops: response.message.model_metadata?.feedback_loops,
              generation_log: response.message.model_metadata?.generation_log,
            }
          : response.message.model_metadata,
        tokens_used: response.message.tokens_used,
        created_at: response.message.created_at,
      };

      addMessage(assistantMessage);

      if (response.model) {
        setCurrentModel(response.model);
      }
    },
    onError: (error: Error) => {
      const errorMessage: Message = {
        id: `guest-error-${Date.now()}`,
        conversation_id: "guest",
        role: "assistant",
        content: `Ошибка: ${error.message || "Не удалось получить ответ"}`,
        created_at: new Date().toISOString(),
      };
      addMessage(errorMessage);
    },
    onSettled: () => {
      setIsSubmitting(false);
    },
  });
}
