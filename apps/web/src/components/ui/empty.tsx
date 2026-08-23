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
    <div className="px-6 py-10 text-center">
      <p className="text-sm font-medium">{title}</p>
      {children && (
        <p className="text-muted-foreground mx-auto mt-1.5 max-w-md text-xs leading-relaxed">
          {children}
        </p>
      )}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  )
}
