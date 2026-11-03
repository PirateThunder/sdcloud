import type { Metadata } from 'next'
import type { ReactNode } from 'react'

import { RootShell } from '@/fsd/app/root-shell'

export const metadata: Metadata = { title: 'Вход — sdCloud' }

export default function Layout({ children }: { children: ReactNode }) {
  return <RootShell>{children}</RootShell>
}
