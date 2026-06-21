"use client";

import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useChatStore } from "../model";
import { useConversationMessages } from "../api";
import { Avatar, AvatarFallback } from "@/shared/ui/avatar";
import { Skeleton } from "@/shared/ui/skeleton";
import { User, Bot, Loader2 } from "lucide-react";
import { ModelTabs } from "@/features/model-view/ui/ModelTabs";

function UserMessage({ content }: { content: string }) {
  return (
    <div className="flex gap-3 max-w-4xl mx-auto w-full py-4">
      <Avatar className="h-8 w-8 shrink-0 bg-primary/10">
        <AvatarFallback className="bg-primary/10 text-primary">
          <User className="h-4 w-4" />
        </AvatarFallback>
      </Avatar>
      <div className="flex-1 min-w-0 pt-1">
        <p className="text-sm font-medium mb-1">Вы</p>
        <div className="text-sm leading-relaxed whitespace-pre-wrap">
          {content}
        </div>
      </div>
    </div>
  );
}

function AssistantMessage({
  content,
  modelMetadata,
}: {
  content: string;
  modelMetadata?: { generated_model?: import("@/entities/model/model").GeneratedModel };
}) {
  return (
    <div className="bg-muted/30 border-y border-border/50">
      <div className="flex gap-3 max-w-4xl mx-auto w-full py-4">
        <Avatar className="h-8 w-8 shrink-0 bg-emerald-500/10">
          <AvatarFallback className="bg-emerald-500/10 text-emerald-500">
            <Bot className="h-4 w-4" />
          </AvatarFallback>
        </Avatar>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium mb-1">sdCloud Assistant</p>
          <div className="markdown-body text-sm">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {content}
            </ReactMarkdown>
          </div>
          {modelMetadata?.generated_model && (
            <div className="mt-4">
              <ModelTabs model={modelMetadata.generated_model} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="bg-muted/30 border-y border-border/50">
      <div className="flex gap-3 max-w-4xl mx-auto w-full py-4">
        <Avatar className="h-8 w-8 shrink-0 bg-emerald-500/10">
          <AvatarFallback className="bg-emerald-500/10 text-emerald-500">
            <Bot className="h-4 w-4" />
          </AvatarFallback>
        </Avatar>
        <div className="flex-1 flex items-center gap-2 pt-1">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          <span className="text-sm text-muted-foreground">
            Генерирую модель...
          </span>
        </div>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-4">
      <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-6">
        <Bot className="h-8 w-8 text-primary" />
      </div>
      <h2 className="text-2xl font-bold mb-2">
        Добро пожаловать в sdCloud
      </h2>
      <p className="text-muted-foreground max-w-md mb-8">
        Опишите систему, и я сгенерирую для неё системно-динамическую модель с
        причинно-следственной диаграммой, диаграммой потоков и уравнениями.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-lg">
        {[
          "Модель хищник-жертва (Lotka-Volterra)",
          "Пандемия: распространение инфекции (SIR)",
          "Перегрузка проекта: эффекты давления",
          "Рыночная динамика: спрос и предложение",
        ].map((example) => (
          <button
            key={example}
            onClick={() => {
              const store = useChatStore.getState();
              store.setInputValue(example);
            }}
            className="p-3 text-left text-sm border border-border/50 rounded-lg hover:bg-accent transition-colors"
          >
            {example}
          </button>
        ))}
      </div>
    </div>
  );
}

export function MessageList() {
  const { currentConversation, messages, isSubmitting } = useChatStore();
  const { isLoading: isLoadingMessages } = useConversationMessages(
    currentConversation?.id || null
  );
  const scrollRef = React.useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom
  React.useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isSubmitting]);

  if (!currentConversation && messages.length === 0) {
    return <EmptyState />;
  }

  if (isLoadingMessages && messages.length === 0) {
    return (
      <div className="flex-1 p-4 space-y-4">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    );
  }

  return (
    <div className="divide-y divide-border/30" ref={scrollRef}>
      {messages.map((message) =>
        message.role === "user" ? (
          <UserMessage key={message.id} content={message.content} />
        ) : (
          <AssistantMessage
            key={message.id}
            content={message.content}
            modelMetadata={message.model_metadata}
          />
        )
      )}
      {isSubmitting && messages[messages.length - 1]?.role === "user" && (
        <TypingIndicator />
      )}
    </div>
  );
}
