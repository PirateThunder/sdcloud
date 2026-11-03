import type { TextareaHTMLAttributes } from 'react'

import { cn } from '@/fsd/shared/lib/utils'

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        'min-h-24 w-full resize-none rounded-lg border border-input bg-card px-3 py-2.5 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-ring disabled:opacity-50',
        className,
      )}
      {...props}
    />
  )
}
