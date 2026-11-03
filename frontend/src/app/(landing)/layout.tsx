import type { Metadata } from 'next'
import type { ReactNode } from 'react'

import { RootShell } from '@/fsd/app/root-shell'

export const metadata: Metadata = {
  title: 'sdCloud — AI для системного моделирования',
  description:
    'Создавайте системно-динамические модели, CLD/SFD и численные симуляции из текстового описания.',
}

export default function Layout({ children }: { children: ReactNode }) {
  return <RootShell>{children}</RootShell>
}
