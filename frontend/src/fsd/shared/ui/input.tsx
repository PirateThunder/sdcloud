import type { InputHTMLAttributes } from 'react'

import { cn } from '@/fsd/shared/lib/utils'

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        'h-10 w-full rounded-lg border border-input bg-card px-3 text-sm text-foreground shadow-none outline-none placeholder:text-muted-foreground focus:border-ring disabled:opacity-50',
        className,
      )}
      {...props}
    />
  )
}
