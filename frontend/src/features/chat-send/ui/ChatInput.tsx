"use client";

import React, { useRef, useEffect } from "react";
import { Button } from "@/shared/ui/button";
import { Textarea } from "@/shared/ui/textarea";
import { useAuthStore } from "@/features/auth/model";
import { useChatStore } from "../model";
import {
  useSendMessage,
  useCreateConversation,
  useSendGuestMessage,
} from "../api";
import { Send, Loader2 } from "lucide-react";

export function ChatInput() {
  const { inputValue, setInputValue, currentConversation, isSubmitting } =
    useChatStore();
  const { isAuthenticated } = useAuthStore();
  const sendMessage = useSendMessage();
  const sendGuestMessage = useSendGuestMessage();
  const createConversation = useCreateConversation();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    }
  }, [inputValue]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const content = inputValue.trim();
    if (!content || isSubmitting) return;

    setInputValue("");

    if (!isAuthenticated) {
      // Guest mode: keep everything in memory, no backend conversation
      sendGuestMessage.mutate({ content });
      return;
    }

    if (!currentConversation) {
      // Create new conversation first
      const newConv = await createConversation.mutateAsync({
        title: content.slice(0, 50),
      });
      // Then send message
      sendMessage.mutate({
        conversationId: newConv.id,
        content,
      });
    } else {
      sendMessage.mutate({
        conversationId: currentConversation.id,
        content,
      });
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const isBusy =
    isSubmitting || createConversation.isPending || sendGuestMessage.isPending;

  return (
    <form
      onSubmit={handleSubmit}
      className="border-t border-border bg-background p-4"
    >
      <div className="relative flex items-end gap-2 max-w-4xl mx-auto">
        <Textarea
          ref={textareaRef}
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Опишите систему для моделирования..."
          className="min-h-[56px] max-h-[200px] pr-14 resize-none bg-muted/50 border-border/50"
          disabled={isBusy}
          rows={1}
        />
        <Button
          type="submit"
          size="icon"
          disabled={!inputValue.trim() || isBusy}
          className="absolute right-2 bottom-2 h-8 w-8 shrink-0"
        >
          {isBusy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" />
          )}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground text-center mt-2">
        Нажмите Enter для отправки, Shift+Enter для новой строки
      </p>
    </form>
  );
}
