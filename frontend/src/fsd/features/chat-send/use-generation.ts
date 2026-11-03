'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import { getGeneration } from '@/fsd/entities/generation/api/generation-api'

export function useGeneration(id: string | null | undefined, conversationId: string) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['generation', id],
    queryFn: () => getGeneration(id as string),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'submitted' || status === 'running' ? 1500 : false
    },
    refetchIntervalInBackground: false,
  })
  const status = query.data?.status
  useEffect(() => {
    if (status !== 'done' && status !== 'error') return
    void queryClient.invalidateQueries({ queryKey: ['messages', conversationId] })
    void queryClient.invalidateQueries({ queryKey: ['models'] })
  }, [conversationId, queryClient, status])
  return query
}
