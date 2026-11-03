import type { Metadata } from 'next'
import type { ReactNode } from 'react'

import { RootShell } from '@/fsd/app/root-shell'
import { AuthGate } from '@/fsd/features/auth/auth-gate'
import { AppChrome } from '@/fsd/widgets/app-chrome/app-chrome'

export const metadata: Metadata = { title: 'Рабочее пространство — sdCloud' }

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <RootShell>
      <AuthGate>
        <AppChrome>{children}</AppChrome>
      </AuthGate>
    </RootShell>
  )
}
