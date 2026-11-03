'use client'

import { ArrowUp } from 'lucide-react'
import type { FormEvent, KeyboardEvent } from 'react'

import { Button } from '@/fsd/shared/ui/button'
import { Textarea } from '@/fsd/shared/ui/textarea'

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  pending,
  contextual = false,
}: {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  pending: boolean
  contextual?: boolean
}) {
  const submit = (event?: FormEvent) => {
    event?.preventDefault()
    if (value.trim() && !pending) onSubmit()
  }
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }
  return (
    <form
      onSubmit={submit}
      className="rounded-2xl border border-input bg-card p-2 shadow-sm focus-within:border-ring"
    >
      <Textarea
        aria-label="Описание системы"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder={
          contextual
            ? 'Задайте вопрос о модели или опишите нужное изменение…'
            : 'Опишите систему, её запасы, потоки и обратные связи…'
        }
        className="max-h-56 min-h-20 border-0 bg-transparent px-3 py-2 shadow-none focus:border-0"
        maxLength={20000}
        rows={3}
      />
      <div className="flex items-center justify-between gap-3 px-2 pb-1">
        <span className="hidden text-[11px] text-muted-foreground sm:block">
          Enter — отправить · Shift+Enter — новая строка
        </span>
        <span className="text-[11px] text-muted-foreground sm:hidden">{value.length}/20000</span>
        <Button
          type="submit"
          size="icon"
          disabled={!value.trim() || pending}
          aria-label="Отправить описание"
        >
          <ArrowUp className="size-5" />
        </Button>
      </div>
    </form>
  )
}
