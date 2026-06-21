"use client";

import React from "react";
import { ScrollArea } from "@/shared/ui/scroll-area";
import { Button } from "@/shared/ui/button";
import { Separator } from "@/shared/ui/separator";
import { Skeleton } from "@/shared/ui/skeleton";
import {
  useConversations,
  useDeleteConversation,
} from "@/features/chat-send/api";
import { useChatStore } from "@/features/chat-send/model";
import { useAuthStore } from "@/features/auth/model";
import {
  MessageSquare,
  Plus,
  Trash2,
  Loader2,
} from "lucide-react";
import { cn, truncateText } from "@/shared/lib/utils";

interface ChatSidebarProps {
  isOpen: boolean;
}

export function ChatSidebar({ isOpen }: ChatSidebarProps) {
  const { data: conversations, isLoading } = useConversations();
  const deleteConversation = useDeleteConversation();
  const { currentConversation, setCurrentConversation, setMessages, clearChat } =
    useChatStore();
  const { isAuthenticated } = useAuthStore();

  const handleSelectConversation = (conv: NonNullable<typeof conversations>[0]) => {
    setCurrentConversation(conv);
    setMessages([]);
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    await deleteConversation.mutateAsync(id);
    if (currentConversation?.id === id) {
      clearChat();
    }
  };

  if (!isOpen) return null;

  return (
    <aside className="w-[280px] shrink-0 border-r border-border/50 bg-muted/30 flex flex-col h-full">
      <div className="p-3">
        <Button
          onClick={clearChat}
          className="w-full justify-start gap-2"
          variant="outline"
        >
          <Plus className="h-4 w-4" />
          Новый чат
        </Button>
      </div>

      <Separator />

      {!isAuthenticated ? (
        <div className="flex-1 flex flex-col items-center justify-center p-6 text-center">
          <MessageSquare className="h-8 w-8 text-muted-foreground mb-3" />
          <p className="text-sm text-muted-foreground mb-2">
            Гостевой режим
          </p>
          <p className="text-xs text-muted-foreground mb-3">
            История чата хранится только в этом окне браузера и исчезнет после перезагрузки.
            Войдите, чтобы сохранять чаты.
          </p>
          <Button size="sm" asChild variant="outline">
            <a href="/login">Войти</a>
          </Button>
        </div>
      ) : (
        <>
          <div className="px-3 py-2">
            <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              История чатов
            </h3>
          </div>
          <ScrollArea className="flex-1 px-2">
            {isLoading ? (
              <div className="space-y-2 p-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : !conversations?.length ? (
              <div className="flex flex-col items-center justify-center p-6 text-center">
                <MessageSquare className="h-8 w-8 text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">
                  Нет чатов. Начните новый разговор.
                </p>
              </div>
            ) : (
              <div className="space-y-1 pb-2">
                {conversations.map((conv) => (
                  <button
                    key={conv.id}
                    onClick={() => handleSelectConversation(conv)}
                    className={cn(
                      "w-full flex items-center gap-2 px-3 py-2.5 rounded-md text-left text-sm transition-colors group",
                      currentConversation?.id === conv.id
                        ? "bg-accent text-accent-foreground"
                        : "hover:bg-accent/50 text-foreground"
                    )}
                  >
                    <MessageSquare className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="flex-1 truncate">
                      {truncateText(conv.title || "Новый чат", 25)}
                    </span>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                      onClick={(e) => handleDelete(e, conv.id)}
                      disabled={deleteConversation.isPending}
                    >
                      {deleteConversation.isPending &&
                      deleteConversation.variables === conv.id ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Trash2 className="h-3 w-3 text-muted-foreground hover:text-destructive" />
                      )}
                    </Button>
                  </button>
                ))}
              </div>
            )}
          </ScrollArea>
        </>
      )}

      <Separator />
      <div className="p-3 text-center">
        <p className="text-[10px] text-muted-foreground">
          sdCloud — AI для системной динамики
        </p>
      </div>
    </aside>
  );
}
