"use client";

import React, { useState } from "react";
import { AppHeader } from "@/widgets/header/ui/AppHeader";
import { ChatSidebar } from "@/widgets/sidebar/ui/ChatSidebar";
import { ChatInput } from "@/features/chat-send/ui/ChatInput";
import { MessageList } from "@/features/chat-send/ui/MessageList";

export function ChatLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="flex h-screen flex-col bg-background text-foreground overflow-hidden">
      <AppHeader
        sidebarOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
      />
      <div className="flex flex-1 overflow-hidden">
        <ChatSidebar isOpen={sidebarOpen} />
        <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
          <div className="flex-1 overflow-y-auto">
            <MessageList />
          </div>
          <ChatInput />
        </main>
      </div>
    </div>
  );
}
