import type { ComponentPropsWithoutRef, JSX } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkBreaks from 'remark-breaks'
import remarkGfm from 'remark-gfm'

import { cn } from '#/lib/utils'

/**
 * The agent answers in Markdown, so the transcript has to read it.
 *
 * Rendered as plain text, a ten-lead answer arrives as a wall of asterisks and
 * bracketed URLs — the structure the model went to the trouble of expressing is
 * exactly the structure the reader loses.
 *
 * **No raw HTML, ever.** Agent output can quote an email or a scraped page, so
 * it is untrusted by the same reasoning as everywhere else in this system.
 * `react-markdown` ignores embedded HTML unless a plugin opts in, and rewrites
 * dangerous URL schemes; images are dropped outright, because a remote `<img>`
 * in a quoted email is a tracking pixel that fires the moment you read the
 * reply. Nothing here should ever add `rehype-raw`.
 */

/** `node` is react-markdown's AST handle — it must not reach the DOM. */
type Props<T extends keyof JSX.IntrinsicElements> = ComponentPropsWithoutRef<T> & {
  node?: unknown
}

const components = {
  p: ({ node, className, ...props }: Props<'p'>) => (
    <p className={cn('leading-relaxed', className)} {...props} />
  ),

  // Lists are the whole point of this file: the padding is what turns a run of
  // hyphens into something you can scan, and the tight spacing keeps a
  // ten-item answer from becoming a page.
  ul: ({ node, className, ...props }: Props<'ul'>) => (
    <ul
      className={cn('marker:text-muted-foreground list-disc space-y-1 pl-5', className)}
      {...props}
    />
  ),
  ol: ({ node, className, ...props }: Props<'ol'>) => (
    <ol
      className={cn('marker:text-muted-foreground list-decimal space-y-2 pl-5', className)}
      {...props}
    />
  ),
  li: ({ node, className, ...props }: Props<'li'>) => (
    <li className={cn('leading-relaxed [&>p]:m-0', className)} {...props} />
  ),

  strong: ({ node, className, ...props }: Props<'strong'>) => (
    <strong className={cn('font-semibold', className)} {...props} />
  ),

  // Lime is the accent, not a text colour — at its lightness it is unreadable
  // as body text. The link keeps ink and wears the accent as its underline.
  a: ({ node, className, ...props }: Props<'a'>) => (
    <a
      className={cn(
        'decoration-primary font-medium break-words underline decoration-2 underline-offset-2',
        'hover:text-primary-foreground hover:bg-accent rounded-sm',
        className,
      )}
      target="_blank"
      rel="noreferrer noopener"
      {...props}
    />
  ),

  code: ({ node, className, ...props }: Props<'code'>) => (
    <code
      className={cn(
        'bg-muted rounded px-1 py-0.5 font-mono text-[0.85em] break-words',
        // Inside a fenced block the surface belongs to the <pre>, so the
        // inline chip styling has to come back off.
        'group-[.is-pre]/pre:bg-transparent group-[.is-pre]/pre:p-0',
        className,
      )}
      {...props}
    />
  ),
  pre: ({ node, className, ...props }: Props<'pre'>) => (
    <pre
      className={cn(
        'bg-muted group/pre is-pre overflow-x-auto rounded-lg p-3 text-[0.85em]',
        className,
      )}
      {...props}
    />
  ),

  h1: ({ node, className, ...props }: Props<'h1'>) => (
    <h1 className={cn('text-base font-semibold tracking-tight', className)} {...props} />
  ),
  h2: ({ node, className, ...props }: Props<'h2'>) => (
    <h2 className={cn('text-base font-semibold tracking-tight', className)} {...props} />
  ),
  h3: ({ node, className, ...props }: Props<'h3'>) => (
    <h3 className={cn('font-semibold tracking-tight', className)} {...props} />
  ),

  blockquote: ({ node, className, ...props }: Props<'blockquote'>) => (
    <blockquote
      className={cn('border-border text-muted-foreground border-l-2 pl-3', className)}
      {...props}
    />
  ),
  hr: ({ node, className, ...props }: Props<'hr'>) => (
    <hr className={cn('border-border border-t', className)} {...props} />
  ),

  // A wide table scrolls inside its own bubble rather than making the whole
  // transcript scroll sideways.
  table: ({ node, className, ...props }: Props<'table'>) => (
    <div className="-mx-1 overflow-x-auto px-1">
      <table className={cn('w-full text-left text-[0.9em]', className)} {...props} />
    </div>
  ),
  th: ({ node, className, ...props }: Props<'th'>) => (
    <th className={cn('border-border border-b px-2 py-1 font-semibold', className)} {...props} />
  ),
  td: ({ node, className, ...props }: Props<'td'>) => (
    <td className={cn('border-border border-b px-2 py-1 align-top', className)} {...props} />
  ),
}

export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    // space-y rather than margins on every element: one rule for the rhythm
    // between blocks, and nested lists stay tight against their parent item.
    <div className={cn('space-y-3 [&_li>ol]:mt-2 [&_li>ul]:mt-1.5', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks]}
        disallowedElements={['img']}
        unwrapDisallowed
        components={components}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
