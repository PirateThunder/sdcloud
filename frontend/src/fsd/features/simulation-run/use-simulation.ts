'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import { getSimulation } from '@/fsd/entities/simulation/api/simulation-api'

export function useSimulation(id: string | undefined, versionId: string) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['simulation', id],
    queryFn: () => getSimulation(id as string),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'submitted' || status === 'running' ? 1500 : false
    },
    refetchIntervalInBackground: false,
  })
  const status = query.data?.status
  useEffect(() => {
    if (status === 'done' || status === 'error') {
      void queryClient.invalidateQueries({ queryKey: ['simulations', versionId] })
    }
  }, [queryClient, status, versionId])
  return query
}
