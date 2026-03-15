import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(date: string | Date) {
  return new Date(date).toLocaleString('ru-RU', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Короткая дата для таблиц: 12 фев 2025 */
export function formatDateShort(date: string | Date) {
  return new Date(date).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

/**
 * Форматирует число для отображения. Безопасна к null/undefined/NaN — возвращает "—".
 */
export function formatNumber(num: number | null | undefined): string {
  if (num == null || !Number.isFinite(num)) return '—'
  return new Intl.NumberFormat('ru-RU').format(num)
}
