'use client'

import { useRouter } from 'next/navigation'
import { type ReactNode, useEffect } from 'react'

import { useSession } from '@/fsd/entities/session/model/session-store'
import { Spinner } from '@/fsd/shared/ui/spinner'

import { bootstrapSession } from './session-bootstrap'

export function AuthGate({ children }: { children: ReactNode }) {
  const router = useRouter()
  const status = useSession((state) => state.status)

  useEffect(() => {
    if (useSession.getState().status === 'unknown') void bootstrapSession()
  }, [])

  useEffect(() => {
    if (status === 'anonymous') router.replace('/login')
  }, [router, status])

  if (status === 'auth') return children
  return (
    <div className="grid min-h-dvh place-items-center">
      <Spinner className="size-8" />
    </div>
  )
}
