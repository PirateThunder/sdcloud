import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru', { day: 'numeric', month: 'short', year: 'numeric' }).format(
    new Date(value),
  )
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat('ru', { maximumSignificantDigits: 6 }).format(value)
}
