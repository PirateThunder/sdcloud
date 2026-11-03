import type { SelectHTMLAttributes } from 'react'

import { cn } from '@/fsd/shared/lib/utils'

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        'h-10 rounded-lg border border-input bg-card px-3 text-sm text-foreground outline-none focus:border-ring disabled:opacity-50',
        className,
      )}
      {...props}
    />
  )
}
