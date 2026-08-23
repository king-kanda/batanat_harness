import type * as React from 'react'

/**
 * Empty states say what will appear here and when. A blank panel is
 * indistinguishable from a broken one.
 */
export function Empty({
  title,
  children,
  action,
}: {
  title: string
  children?: React.ReactNode
  action?: React.ReactNode
}) {
  return (
    <div className="px-4 py-8 text-center">
      <p className="text-ink text-sm font-medium">{title}</p>
      {children && <p className="text-ink-faint mx-auto mt-1.5 max-w-md text-xs">{children}</p>}
      {action && <div className="mt-3 flex justify-center">{action}</div>}
    </div>
  )
}
