import { z } from 'zod'

import { api } from '@/fsd/shared/api/http'

import {
  type Conversation,
  conversationSchema,
  type Message,
  type MessageAccepted,
  messageAcceptedSchema,
  messageSchema,
} from '../model/types'

export async function listConversations(): Promise<Conversation[]> {
  const data = await api.get('conversations').json()
  return z.array(conversationSchema).parse(data)
}

export async function createConversation(title?: string): Promise<Conversation> {
  const data = await api.post('conversations', { json: { title: title || null } }).json()
  return conversationSchema.parse(data)
}

export async function renameConversation(id: string, title: string): Promise<Conversation> {
  const data = await api.patch(`conversations/${id}`, { json: { title } }).json()
  return conversationSchema.parse(data)
}

export async function deleteConversation(id: string): Promise<void> {
  await api.delete(`conversations/${id}`)
}

export async function listMessages(conversationId: string): Promise<Message[]> {
  const data = await api.get(`conversations/${conversationId}/messages`).json()
  return z.array(messageSchema).parse(data)
}

export async function sendMessage(
  conversationId: string,
  content: string,
  idempotencyKey: string,
): Promise<MessageAccepted> {
  const data = await api
    .post(`conversations/${conversationId}/messages`, {
      json: { content },
      headers: { 'Idempotency-Key': idempotencyKey },
    })
    .json()
  return messageAcceptedSchema.parse(data)
}
