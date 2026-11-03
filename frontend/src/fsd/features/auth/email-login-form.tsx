'use client'

import { ArrowLeft, Mail } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { type FormEvent, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { authEmailRequest, authEmailVerify } from '@/fsd/entities/session/api/auth-api'
import { useSession } from '@/fsd/entities/session/model/session-store'
import { Button } from '@/fsd/shared/ui/button'
import { Input } from '@/fsd/shared/ui/input'

export function EmailLoginForm() {
  const router = useRouter()
  const [step, setStep] = useState<'email' | 'code'>('email')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [devCode, setDevCode] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [cooldown, setCooldown] = useState(0)
  const [error, setError] = useState('')
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(
    () => () => {
      if (timerRef.current) clearInterval(timerRef.current)
    },
    [],
  )

  const startCooldown = (seconds: number) => {
    setCooldown(seconds)
    if (timerRef.current) clearInterval(timerRef.current)
    timerRef.current = setInterval(() => {
      setCooldown((left) => {
        if (left <= 1 && timerRef.current) clearInterval(timerRef.current)
        return Math.max(0, left - 1)
      })
    }, 1000)
  }

  const requestCode = async (event: FormEvent) => {
    event.preventDefault()
    const normalized = email.trim()
    if (!normalized || pending) return
    setPending(true)
    setError('')
    try {
      const result = await authEmailRequest(normalized)
      setEmail(normalized)
      setStep('code')
      setDevCode(result.dev_code ?? null)
      startCooldown(result.retry_after)
      if (result.dev_code) setCode(result.dev_code)
      toast.success('Код отправлен — проверьте почту')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось отправить код')
    } finally {
      setPending(false)
    }
  }

  const verify = async (event: FormEvent) => {
    event.preventDefault()
    if (code.length !== 6 || pending) return
    setPending(true)
    setError('')
    try {
      const result = await authEmailVerify(email, code)
      useSession.getState().setSession(result.user, result.access_token, result.expires_in)
      router.replace('/chat')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Неверный код')
      setPending(false)
    }
  }

  if (step === 'code') {
    return (
      <form onSubmit={(event) => void verify(event)} className="space-y-4">
        <div>
          <label htmlFor="email-code" className="mb-2 block text-sm font-medium">
            Код из письма
          </label>
          <p className="mb-3 text-sm text-muted-foreground">
            Отправили шестизначный код на {email}
          </p>
          <Input
            id="email-code"
            value={code}
            onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
            placeholder="000000"
            inputMode="numeric"
            autoComplete="one-time-code"
            autoFocus
            className="text-center font-mono text-xl tracking-[0.45em]"
            maxLength={6}
          />
        </div>
        {devCode && (
          <button
            type="button"
            onClick={() => setCode(devCode)}
            className="w-full rounded-lg bg-accent p-3 text-left text-xs text-accent-foreground"
          >
            Локальный код: <span className="font-mono font-semibold">{devCode}</span>
            <span className="mt-1 block opacity-75">Нажмите, чтобы подставить</span>
          </button>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" size="lg" className="w-full" disabled={pending || code.length !== 6}>
          {pending ? 'Проверяем…' : 'Войти в sdCloud'}
        </Button>
        <div className="flex items-center justify-between gap-3 text-xs">
          <button
            type="button"
            onClick={() => {
              setStep('email')
              setCode('')
              setDevCode(null)
              setError('')
            }}
            className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-3.5" /> Изменить почту
          </button>
          <button
            type="button"
            disabled={cooldown > 0 || pending}
            onClick={(event) => void requestCode(event)}
            className="text-primary disabled:text-muted-foreground"
          >
            {cooldown > 0 ? `Отправить снова (${cooldown})` : 'Отправить снова'}
          </button>
        </div>
      </form>
    )
  }

  return (
    <form onSubmit={(event) => void requestCode(event)} className="space-y-4">
      <div>
        <label htmlFor="email-login" className="mb-2 block text-sm font-medium">
          Email
        </label>
        <Input
          id="email-login"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@example.com"
          autoComplete="email"
          maxLength={320}
          required
        />
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <Button type="submit" size="lg" className="w-full" disabled={pending || !email.trim()}>
        <Mail />
        {pending ? 'Отправляем…' : 'Получить код'}
      </Button>
      <p className="text-center text-xs leading-5 text-muted-foreground">
        Пароль не нужен. При первом входе аккаунт будет создан автоматически.
      </p>
    </form>
  )
}
