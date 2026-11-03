import { cn } from '@/fsd/shared/lib/utils'

export function Spinner({ className }: { className?: string }) {
  return (
    <output
      aria-label="Загрузка"
      className={cn(
        'inline-block size-5 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent',
        className,
      )}
    />
  )
}
