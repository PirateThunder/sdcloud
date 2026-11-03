'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Library, MessageSquare, Pencil, Plus, Trash2, X } from 'lucide-react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useState } from 'react'

import {
  deleteConversation,
  listConversations,
  renameConversation,
} from '@/fsd/entities/conversation/api/conversation-api'
import type { Conversation } from '@/fsd/entities/conversation/model/types'
import { useSession } from '@/fsd/entities/session/model/session-store'
import { LogoutButton } from '@/fsd/features/auth/logout-button'
import { ThemeToggle } from '@/fsd/features/theme/theme-toggle'
import { cn } from '@/fsd/shared/lib/utils'
import { Button } from '@/fsd/shared/ui/button'
import { Input } from '@/fsd/shared/ui/input'
import { Logo } from '@/fsd/shared/ui/logo'

function ConversationRow({
  conversation,
  active,
  onNavigate,
}: {
  conversation: Conversation
  active: boolean
  onNavigate: () => void
}) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [title, setTitle] = useState(conversation.title)
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['conversations'] })
  const rename = useMutation({
    mutationFn: () => renameConversation(conversation.id, title.trim()),
    onSuccess: async () => {
      setEditing(false)
      await invalidate()
    },
  })
  const remove = useMutation({
    mutationFn: () => deleteConversation(conversation.id),
    onSuccess: async () => {
      await invalidate()
      if (active) router.push('/chat')
    },
  })

  if (editing) {
    return (
      <form
        className="flex items-center gap-1 px-2 py-1"
        onSubmit={(event) => {
          event.preventDefault()
          if (title.trim()) rename.mutate()
        }}
      >
        <Input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          className="h-8 text-xs"
          autoFocus
        />
        <Button
          type="submit"
          size="icon-sm"
          variant="ghost"
          disabled={rename.isPending}
          aria-label="Сохранить название"
        >
          <Check />
        </Button>
        <Button
          type="button"
          size="icon-sm"
          variant="ghost"
          onClick={() => setEditing(false)}
          aria-label="Отмена"
        >
          <X />
        </Button>
      </form>
    )
  }

  if (confirming) {
    return (
      <div className="mx-2 rounded-lg bg-destructive/8 p-2 text-xs">
        <p className="px-1 pb-2 text-muted-foreground">Удалить беседу и её модели?</p>
        <div className="flex gap-1">
          <Button
            size="sm"
            variant="destructive"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
          >
            Удалить
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
            Отмена
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className={cn('group relative mx-2 rounded-lg', active && 'bg-secondary')}>
      <Link
        href={`/chat/${conversation.id}`}
        onClick={onNavigate}
        className="block truncate rounded-lg py-2 pl-3 pr-14 text-sm text-secondary-foreground hover:bg-muted"
        title={conversation.title}
      >
        {conversation.title}
      </Link>
      <div className="absolute right-1 top-1 flex opacity-100 transition-opacity lg:opacity-0 lg:group-hover:opacity-100 lg:group-focus-within:opacity-100">
        <button
          type="button"
          onClick={() => {
            setTitle(conversation.title)
            setEditing(true)
          }}
          className="grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
          aria-label={`Переименовать ${conversation.title}`}
        >
          <Pencil className="size-3.5" />
        </button>
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
          aria-label={`Удалить ${conversation.title}`}
        >
          <Trash2 className="size-3.5" />
        </button>
      </div>
    </div>
  )
}

export function ConversationSidebar({ onNavigate }: { onNavigate: () => void }) {
  const pathname = usePathname()
  const user = useSession((state) => state.user)
  const conversations = useQuery({ queryKey: ['conversations'], queryFn: listConversations })

  return (
    <div className="flex h-full flex-col border-r border-border bg-card">
      <div className="flex h-16 items-center justify-between px-4">
        <Logo href="/chat" />
        <Button
          size="icon-sm"
          variant="ghost"
          className="lg:hidden"
          onClick={onNavigate}
          aria-label="Закрыть меню"
        >
          <X />
        </Button>
      </div>
      <div className="px-3 pb-3">
        <Button
          render={<Link href="/chat" onClick={onNavigate} />}
          className="w-full justify-start"
        >
          <Plus /> Новая модель
        </Button>
      </div>
      <nav className="flex-1 overflow-y-auto pb-4" aria-label="Беседы">
        <div className="px-4 pb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Беседы
        </div>
        {conversations.isPending && (
          <div className="space-y-2 px-3">
            {[1, 2, 3].map((item) => (
              <div key={item} className="h-8 animate-pulse rounded-lg bg-muted" />
            ))}
          </div>
        )}
        {conversations.isError && (
          <p className="px-4 text-xs text-destructive">Не удалось загрузить беседы</p>
        )}
        {conversations.data?.length === 0 && (
          <div className="px-4 py-6 text-xs leading-5 text-muted-foreground">
            <MessageSquare className="mb-2 size-4" /> Здесь появятся ваши модели и обсуждения.
          </div>
        )}
        {conversations.data?.map((conversation) => (
          <ConversationRow
            key={conversation.id}
            conversation={conversation}
            active={pathname === `/chat/${conversation.id}`}
            onNavigate={onNavigate}
          />
        ))}
      </nav>
      <div className="border-t border-border p-3">
        <Link
          href="/models"
          onClick={onNavigate}
          className={cn(
            'mb-3 flex items-center gap-2 rounded-lg px-2 py-2 text-sm hover:bg-muted',
            pathname.startsWith('/models') && 'bg-secondary',
          )}
        >
          <Library className="size-4" /> Библиотека моделей
        </Link>
        <div className="flex items-center gap-2 px-1">
          <div className="grid size-8 shrink-0 place-items-center rounded-full bg-accent text-xs font-semibold text-accent-foreground">
            {user?.display_name.slice(0, 1).toUpperCase() || 'U'}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-xs font-medium">{user?.display_name}</div>
            <div className="truncate text-[11px] text-muted-foreground">{user?.email}</div>
          </div>
          <ThemeToggle />
          <LogoutButton />
        </div>
      </div>
    </div>
  )
}
