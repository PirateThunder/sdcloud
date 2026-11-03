import type { LucideIcon } from 'lucide-react'

import { Card } from './card'

export function EmptyState({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon
  title: string
  description: string
}) {
  return (
    <Card className="flex min-h-48 flex-col items-center justify-center gap-3 p-8 text-center shadow-none">
      <div className="rounded-xl bg-accent p-3 text-accent-foreground">
        <Icon className="size-6" />
      </div>
      <h3 className="font-semibold">{title}</h3>
      <p className="max-w-md text-sm leading-6 text-muted-foreground">{description}</p>
    </Card>
  )
}
