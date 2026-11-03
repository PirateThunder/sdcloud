import { Workflow } from 'lucide-react'
import Link from 'next/link'

import { cn } from '@/fsd/shared/lib/utils'

export function Logo({ href = '/', className }: { href?: string; className?: string }) {
  return (
    <Link href={href} className={cn('inline-flex items-center gap-2.5 font-semibold', className)}>
      <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
        <Workflow className="size-4.5" />
      </span>
      <span className="tracking-tight">sdCloud</span>
    </Link>
  )
}
