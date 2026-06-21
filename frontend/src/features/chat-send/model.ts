import { create } from "zustand";
import type { Message, Conversation } from "@/entities/chat/model";
import type { GeneratedModel } from "@/entities/model/model";

interface ChatState {
  // Current conversation
  currentConversation: Conversation | null;
  messages: Message[];
  isLoading: boolean;
  error: string | null;

  // Model data
  currentModel: GeneratedModel | null;

  // Input
  inputValue: string;
  isSubmitting: boolean;

  // Actions
  setCurrentConversation: (conversation: Conversation | null) => void;
  setMessages: (messages: Message[]) => void;
  addMessage: (message: Message) => void;
  updateMessage: (id: string, updates: Partial<Message>) => void;
  setIsLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setCurrentModel: (model: GeneratedModel | null) => void;
  setInputValue: (value: string) => void;
  setIsSubmitting: (submitting: boolean) => void;
  clearChat: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  currentConversation: null,
  messages: [],
  isLoading: false,
  error: null,
  currentModel: null,
  inputValue: "",
  isSubmitting: false,

  setCurrentConversation: (conversation) =>
    set({ currentConversation: conversation }),
  setMessages: (messages) => set({ messages }),
  addMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),
  updateMessage: (id, updates) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === id ? { ...m, ...updates } : m
      ),
    })),
  setIsLoading: (isLoading) => set({ isLoading }),
  setError: (error) => set({ error }),
  setCurrentModel: (currentModel) => set({ currentModel }),
  setInputValue: (inputValue) => set({ inputValue }),
  setIsSubmitting: (isSubmitting) => set({ isSubmitting }),
  clearChat: () =>
    set({
      currentConversation: null,
      messages: [],
      currentModel: null,
      error: null,
      inputValue: "",
    }),
}));
