import { ArrowRight, ChartLine, GitBranch, Sigma, Workflow } from 'lucide-react'
import Link from 'next/link'

import { ThemeToggle } from '@/fsd/features/theme/theme-toggle'
import { Button } from '@/fsd/shared/ui/button'
import { Card } from '@/fsd/shared/ui/card'
import { Logo } from '@/fsd/shared/ui/logo'

const features = [
  {
    icon: GitBranch,
    title: 'Структура системы',
    text: 'CLD, stocks, flows, обратные связи и уравнения из единой модели.',
  },
  {
    icon: ChartLine,
    title: 'Численные эксперименты',
    text: 'Симуляции с разными методами, параметрами и сохранённой историей.',
  },
  {
    icon: Sigma,
    title: 'Открытые форматы',
    text: 'Прозрачные уравнения и экспорт в Python, Vensim и XMILE.',
  },
]

export function LandingPage() {
  return (
    <div className="min-h-dvh">
      <header className="mx-auto flex h-18 max-w-6xl items-center justify-between px-5">
        <Logo />
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <Button render={<Link href="/login" />} variant="ghost">
            Войти
          </Button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-5 pb-20">
        <section className="grid items-center gap-12 py-16 sm:py-24 lg:grid-cols-[1.15fr_0.85fr]">
          <div>
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-xs font-medium text-muted-foreground">
              <Workflow className="size-3.5 text-primary" /> AI для системного мышления
            </div>
            <h1 className="max-w-3xl text-4xl font-semibold leading-[1.08] tracking-[-0.035em] sm:text-6xl">
              От описания системы — к работающей модели
            </h1>
            <p className="mt-6 max-w-2xl text-base leading-7 text-muted-foreground sm:text-lg">
              Опишите проблему текстом. sdCloud поможет построить системно-динамическую модель,
              проверить её поведение и понять, какие обратные связи управляют результатом.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button render={<Link href="/chat" />} size="lg">
                Создать модель <ArrowRight />
              </Button>
              <Button render={<Link href="/login" />} size="lg" variant="outline">
                Войти по email
              </Button>
            </div>
          </div>
          <Card className="relative overflow-hidden p-6 shadow-sm">
            <div className="absolute inset-x-0 top-0 h-1 bg-primary" />
            <div className="space-y-5">
              <div className="rounded-lg bg-muted p-4 text-sm leading-6 text-muted-foreground">
                «Кролики размножаются, лисы охотятся на кроликов. Покажи динамику популяций».
              </div>
              <div className="flex items-center justify-between rounded-lg border p-4">
                <div>
                  <div className="text-xs text-muted-foreground">STOCK</div>
                  <div className="mt-1 font-mono text-sm">population(t)</div>
                </div>
                <div className="rounded-full bg-accent px-3 py-1 font-mono text-xs text-accent-foreground">
                  dP/dt = births − predation
                </div>
              </div>
              <div className="grid grid-cols-3 gap-3 text-center text-xs">
                {['Уравнения', 'CLD + SFD', 'Симуляция'].map((item, index) => (
                  <div key={item} className="rounded-lg bg-accent/60 p-3 text-accent-foreground">
                    <div className="mx-auto mb-2 size-2 rounded-full bg-primary" />
                    {index + 1}. {item}
                  </div>
                ))}
              </div>
            </div>
          </Card>
        </section>
        <section className="grid gap-4 md:grid-cols-3">
          {features.map(({ icon: Icon, title, text }) => (
            <Card key={title} className="p-5 shadow-none">
              <Icon className="mb-4 size-5 text-primary" />
              <h2 className="font-semibold">{title}</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{text}</p>
            </Card>
          ))}
        </section>
      </main>
    </div>
  )
}
