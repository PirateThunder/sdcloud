'use client'

import { useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { createConversation, sendMessage } from '@/fsd/entities/conversation/api/conversation-api'
import type { Message } from '@/fsd/entities/conversation/model/types'

export function useChatSubmit(conversationId?: string) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')

  const submit = async (content: string) => {
    const description = content.trim()
    if (!description || pending) return
    setPending(true)
    setError('')
    const key = crypto.randomUUID()
    try {
      const id = conversationId ?? (await createConversation()).id
      const optimistic: Message = {
        id: `optimistic-${key}`,
        role: 'user',
        content: description,
        status: 'done',
        created_at: new Date().toISOString(),
      }
      queryClient.setQueryData<Message[]>(['messages', id], (old = []) => [...old, optimistic])
      try {
        const accepted = await sendMessage(id, description, key)
        queryClient.setQueryData<Message[]>(['messages', id], (old = []) => [
          ...old.filter((message) => message.id !== optimistic.id),
          accepted.user_message,
          accepted.assistant_message,
        ])
        await queryClient.invalidateQueries({ queryKey: ['conversations'] })
        if (!conversationId) router.replace(`/chat/${id}`)
      } catch (reason) {
        queryClient.setQueryData<Message[]>(['messages', id], (old = []) =>
          old.filter((message) => message.id !== optimistic.id),
        )
        throw reason
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось отправить сообщение')
      throw reason
    } finally {
      setPending(false)
    }
  }

  return { submit, pending, error }
}
