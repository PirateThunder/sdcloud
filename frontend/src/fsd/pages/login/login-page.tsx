'use client'

import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { useSession } from '@/fsd/entities/session/model/session-store'
import { EmailLoginForm } from '@/fsd/features/auth/email-login-form'
import { ThemeToggle } from '@/fsd/features/theme/theme-toggle'
import { Card } from '@/fsd/shared/ui/card'
import { Logo } from '@/fsd/shared/ui/logo'

export function LoginPage() {
  const router = useRouter()
  const status = useSession((state) => state.status)

  useEffect(() => {
    if (status === 'auth') router.replace('/chat')
  }, [router, status])

  return (
    <main className="relative grid min-h-dvh place-items-center overflow-hidden px-4 py-12">
      <div className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute left-1/2 top-[-18rem] size-[42rem] -translate-x-1/2 rounded-full bg-accent/55 blur-3xl" />
      </div>
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <div className="w-full max-w-md">
        <Logo className="mb-8 justify-center text-xl" />
        <Card className="p-6 shadow-sm sm:p-8">
          <div className="mb-7 text-center">
            <h1 className="text-2xl font-semibold tracking-tight">Добро пожаловать</h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              Войдите по коду из письма, чтобы создавать и исследовать системные модели.
            </p>
          </div>
          <EmailLoginForm />
        </Card>
        <p className="mt-6 text-center text-xs leading-5 text-muted-foreground">
          Системная динамика, CLD/SFD, симуляции и анализ — в одном рабочем пространстве.
        </p>
      </div>
    </main>
  )
}
