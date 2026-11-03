'use client'

import { Menu } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import { Button } from '@/fsd/shared/ui/button'
import { Logo } from '@/fsd/shared/ui/logo'
import { ConversationSidebar } from '@/fsd/widgets/conversation-sidebar/conversation-sidebar'

export function AppChrome({ children }: { children: ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const close = () => setSidebarOpen(false)

  return (
    <div className="flex h-dvh overflow-hidden bg-background text-foreground">
      <aside className="hidden w-72 shrink-0 lg:block">
        <ConversationSidebar onNavigate={close} />
      </aside>
      {sidebarOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-black/35"
            onClick={close}
            aria-label="Закрыть меню"
          />
          <aside className="relative h-full w-[min(88vw,320px)] shadow-xl">
            <ConversationSidebar onNavigate={close} />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-card px-3 lg:hidden">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setSidebarOpen(true)}
            aria-label="Открыть меню"
          >
            <Menu />
          </Button>
          <Logo href="/chat" className="text-sm" />
          <span className="size-8" />
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  )
}
