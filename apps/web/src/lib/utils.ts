import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** shadcn/ui's class merge helper: conditional classes, last-wins on conflicts. */
export function cn(...inputs: Array<ClassValue>) {
  return twMerge(clsx(inputs))
}
