'use client'

import { useQuery } from '@tanstack/react-query'
import { GitBranch, LineChart, PackageSearch, Rabbit } from 'lucide-react'
import { useState } from 'react'

import { listMessages } from '@/fsd/entities/conversation/api/conversation-api'
import { ChatComposer } from '@/fsd/features/chat-send/chat-composer'
import { MessageList } from '@/fsd/features/chat-send/message-list'
import { useChatSubmit } from '@/fsd/features/chat-send/use-chat-submit'
import { Badge } from '@/fsd/shared/ui/badge'
import { Card } from '@/fsd/shared/ui/card'
import { Spinner } from '@/fsd/shared/ui/spinner'

const examples = [
  {
    icon: Rabbit,
    title: 'Хищник–жертва',
    prompt:
      'Построй модель хищник–жертва: кролики размножаются, лисы охотятся на кроликов и умирают естественной смертностью.',
  },
  {
    icon: GitBranch,
    title: 'Распространение инфекции',
    prompt:
      'Создай SIR-модель эпидемии: восприимчивые заражаются при контакте с инфицированными, затем выздоравливают.',
  },
  {
    icon: PackageSearch,
    title: 'Склад и поставки',
    prompt:
      'Смоделируй склад: заказы пополняют запасы с задержкой поставки, продажи уменьшают запасы, дефицит влияет на сервис.',
  },
  {
    icon: LineChart,
    title: 'Логистический рост',
    prompt:
      'Создай модель логистического роста популяции с ограничением ёмкости среды и нелинейным замедлением роста.',
  },
]

export function ChatPage({ conversationId }: { conversationId?: string }) {
  const [input, setInput] = useState('')
  const { submit, pending, error } = useChatSubmit(conversationId)
  const messages = useQuery({
    queryKey: ['messages', conversationId],
    queryFn: () => listMessages(conversationId as string),
    enabled: Boolean(conversationId),
  })
  const empty = !conversationId || (messages.data?.length === 0 && !messages.isPending)

  const send = async () => {
    const content = input
    try {
      await submit(content)
      setInput('')
    } catch {
      // The hook preserves input and exposes the server error.
    }
  }

  return (
    <div className="flex min-h-full flex-col">
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-card px-4 sm:px-6">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">
            {conversationId ? 'Системная модель' : 'Новая модель'}
          </div>
          <div className="text-[11px] text-muted-foreground">
            Текст → структура → уравнения → эксперимент
          </div>
        </div>
        <div className="flex items-center gap-2">
          {process.env.NEXT_PUBLIC_LLM_PROVIDER === 'fixture' && (
            <Badge className="border border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300">
              Демо: fixture
            </Badge>
          )}
          <Badge className="bg-accent text-accent-foreground">System Dynamics</Badge>
        </div>
      </header>
      <div className="flex-1">
        {empty ? (
          <div className="mx-auto max-w-4xl px-4 py-10 sm:px-8 sm:py-16">
            <div className="mb-10 text-center">
              <div className="mb-4 inline-flex rounded-2xl bg-accent p-3 text-accent-foreground">
                <GitBranch className="size-7" />
              </div>
              <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
                Какую систему исследуем?
              </h1>
              <p className="mx-auto mt-3 max-w-xl text-sm leading-6 text-muted-foreground">
                Опишите поведение и взаимосвязи. Можно начать с примера или сформулировать задачу
                своими словами.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {examples.map(({ icon: Icon, title, prompt }) => (
                <button
                  key={title}
                  type="button"
                  onClick={() => setInput(prompt)}
                  className="text-left"
                >
                  <Card className="h-full p-4 transition-colors hover:border-ring hover:bg-accent/30">
                    <Icon className="mb-3 size-5 text-primary" />
                    <div className="text-sm font-medium">{title}</div>
                    <p className="mt-1.5 line-clamp-2 text-xs leading-5 text-muted-foreground">
                      {prompt}
                    </p>
                  </Card>
                </button>
              ))}
            </div>
          </div>
        ) : messages.isPending ? (
          <div className="grid min-h-48 place-items-center">
            <Spinner />
          </div>
        ) : messages.isError ? (
          <div className="p-8 text-center text-sm text-destructive">
            Не удалось загрузить сообщения
          </div>
        ) : (
          <MessageList messages={messages.data ?? []} conversationId={conversationId as string} />
        )}
      </div>
      <div className="sticky bottom-0 z-10 bg-gradient-to-t from-background via-background to-transparent px-4 pb-4 pt-6 sm:px-8">
        <div className="mx-auto max-w-3xl">
          {error && (
            <p role="alert" className="mb-2 text-sm text-destructive">
              {error}
            </p>
          )}
          <ChatComposer
            value={input}
            onChange={setInput}
            onSubmit={() => void send()}
            pending={pending}
            contextual={Boolean(conversationId)}
          />
        </div>
      </div>
    </div>
  )
}
