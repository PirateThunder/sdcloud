import { ChatPage } from '@/fsd/pages/chat/chat-page'

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return <ChatPage conversationId={id} />
}
