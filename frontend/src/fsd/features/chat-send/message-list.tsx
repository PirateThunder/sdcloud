'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ArrowUpRight, Bot, User } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Message } from '@/fsd/entities/conversation/model/types'
import { retryGeneration } from '@/fsd/entities/generation/api/generation-api'
import { Button } from '@/fsd/shared/ui/button'
import { Card } from '@/fsd/shared/ui/card'
import { Spinner } from '@/fsd/shared/ui/spinner'

import { useGeneration } from './use-generation'

const stageNames: Record<string, string> = {
  queued: 'В очереди',
  submitted: 'Передаём в движок',
  pending: 'В очереди движка',
  running: 'Обрабатываем сообщение',
  message: 'Анализируем контекст и текущую модель',
  brief: 'Анализируем систему',
  structure: 'Определяем структуру',
  variables: 'Определяем переменные',
  expressions: 'Формируем уравнения',
  validation: 'Проверяем модель',
  repair: 'Исправляем найденные ошибки',
  graphs: 'Строим CLD и SFD',
  exports: 'Готовим форматы',
}

function AssistantMessage({
  message,
  conversationId,
}: {
  message: Message
  conversationId: string
}) {
  const queryClient = useQueryClient()
  const generation = useGeneration(message.generation_id, conversationId)
  const retry = useMutation({
    mutationFn: () => retryGeneration(message.generation_id as string),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['messages', conversationId] })
    },
  })
  const data = generation.data
  const status = data?.status ?? message.status
  const active = status === 'queued' || status === 'submitted' || status === 'running'
  const failed = status === 'error'

  return (
    <div className="flex gap-3 py-5 sm:gap-4">
      <div className="grid size-8 shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground">
        <Bot className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="mb-1.5 text-xs font-medium text-muted-foreground">sdCloud</div>
        {active ? (
          <div className="flex items-center gap-3 rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
            <Spinner />
            <div>
              <div className="font-medium text-foreground">Обрабатываю сообщение</div>
              <div className="mt-1 text-xs">
                {stageNames[data?.stage ?? status] ?? 'Формирую ответ'}
              </div>
            </div>
          </div>
        ) : failed ? (
          <Card className="border-destructive/30 p-4">
            <div className="flex gap-3 text-sm">
              <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" />
              <div>
                <div className="font-medium">Не удалось обработать сообщение</div>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {data?.error ?? 'Попробуйте повторить запрос.'}
                </p>
                <Button
                  size="sm"
                  variant="outline"
                  className="mt-3"
                  onClick={() => retry.mutate()}
                  disabled={retry.isPending}
                >
                  {retry.isPending ? 'Запускаем…' : 'Повторить запрос'}
                </Button>
              </div>
            </div>
          </Card>
        ) : (
          <>
            <div className="markdown-body text-sm">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
            </div>
            {message.model_version_id && data?.status === 'done' && (
              <Card className="mt-4 flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="text-xs font-medium text-primary">Модель готова</div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    Диаграммы, уравнения, версии и симуляции доступны в рабочей области.
                  </div>
                </div>
                <Button
                  render={<Link href={`/model-versions/${message.model_version_id}`} />}
                  size="sm"
                  variant="outline"
                >
                  Открыть модель <ArrowUpRight />
                </Button>
              </Card>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export function MessageList({
  messages,
  conversationId,
}: {
  messages: Message[]
  conversationId: string
}) {
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (messages.length > 0) bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages.length])
  return (
    <div className="mx-auto w-full max-w-4xl px-4 pb-8 sm:px-8">
      {messages.map((message) =>
        message.role === 'user' ? (
          <div key={message.id} className="flex justify-end gap-3 py-5">
            <div className="max-w-[85%] rounded-2xl rounded-tr-md bg-secondary px-4 py-3 text-sm leading-6 whitespace-pre-wrap sm:max-w-[75%]">
              {message.content}
            </div>
            <div className="grid size-8 shrink-0 place-items-center rounded-full bg-secondary text-secondary-foreground">
              <User className="size-4" />
            </div>
          </div>
        ) : (
          <AssistantMessage key={message.id} message={message} conversationId={conversationId} />
        ),
      )}
      <div ref={bottomRef} />
    </div>
  )
}
