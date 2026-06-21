"use client";

import React from "react";
import { useAuthStore } from "@/features/auth/model";
import { useMe, useLogout } from "@/features/auth/api";
import { Avatar, AvatarFallback } from "@/shared/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/shared/ui/dropdown-menu";
import { Button } from "@/shared/ui/button";
import { useChatStore } from "@/features/chat-send/model";
import {
  PanelLeftClose,
  PanelLeftOpen,
  LogOut,
  Settings,
  Cloud,
} from "lucide-react";

interface AppHeaderProps {
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
}

export function AppHeader({ sidebarOpen, onToggleSidebar }: AppHeaderProps) {
  const { user, isAuthenticated } = useAuthStore();
  const { data: userData } = useMe();
  const logout = useLogout();

  // Only subscribe to user data when authenticated
  const currentUser = isAuthenticated ? userData || user : null;
  const { clearChat } = useChatStore();

  const handleNewChat = () => {
    clearChat();
  };

  return (
    <header className="sticky top-0 z-40 flex h-14 items-center gap-4 border-b border-border/50 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 px-4">
      <Button
        variant="ghost"
        size="icon"
        onClick={onToggleSidebar}
        className="shrink-0"
      >
        {sidebarOpen ? (
          <PanelLeftClose className="h-5 w-5" />
        ) : (
          <PanelLeftOpen className="h-5 w-5" />
        )}
      </Button>

      <div className="flex items-center gap-2">
        <Cloud className="h-6 w-6 text-primary" />
        <h1 className="text-lg font-semibold tracking-tight">sdCloud</h1>
      </div>

      <div className="ml-auto flex items-center gap-2">
        {isAuthenticated && currentUser ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="gap-2 h-8 px-2">
                <Avatar className="h-7 w-7">
                  <AvatarFallback className="bg-primary/10 text-primary text-xs">
                    {currentUser.username?.[0]?.toUpperCase() || "U"}
                  </AvatarFallback>
                </Avatar>
                <span className="text-sm hidden sm:inline">
                  {currentUser.username}
                </span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <div className="flex items-center gap-2 p-2">
                <Avatar className="h-8 w-8">
                  <AvatarFallback className="bg-primary/10 text-primary text-xs">
                    {currentUser.username?.[0]?.toUpperCase() || "U"}
                  </AvatarFallback>
                </Avatar>
                <div className="flex flex-col">
                  <span className="text-sm font-medium">
                    {currentUser.username}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {currentUser.email}
                  </span>
                </div>
              </div>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={handleNewChat}>
                <Cloud className="mr-2 h-4 w-4" />
                Новый чат
              </DropdownMenuItem>
              <DropdownMenuItem disabled>
                <Settings className="mr-2 h-4 w-4" />
                Настройки
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={logout} className="text-destructive">
                <LogOut className="mr-2 h-4 w-4" />
                Выйти
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          <Button variant="ghost" size="sm" asChild>
            <a href="/login">Войти</a>
          </Button>
        )}
      </div>
    </header>
  );
}
