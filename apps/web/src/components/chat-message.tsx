import { Loader2, Sparkles, User } from 'lucide-react'

import { Markdown } from '#/components/markdown'
import { Badge } from '#/components/ui/badge'
import { cn } from '#/lib/utils'

export type ChatRole = 'you' | 'agent'

/**
 * Who is speaking, spelled out.
 *
 * The name is the point. A transcript where the two voices are told apart by
 * tint alone stops working the moment you print it, read it in high contrast,
 * or hear it read aloud — so every turn is named, and side, avatar and surface
 * are the fast signals layered on top for an eye scanning back through it.
 */
const SPEAKER = {
  you: { label: 'You', icon: User },
  agent: { label: 'Agent', icon: Sparkles },
} as const satisfies Record<ChatRole, { label: string; icon: typeof User }>

/** Avatar and name, on the same side as the bubble it belongs to. */
function Byline({ role }: { role: ChatRole }) {
  const mine = role === 'you'
  const { label, icon: Icon } = SPEAKER[role]

  return (
    <div className={cn('flex items-center gap-2', mine && 'flex-row-reverse')}>
      <span
        aria-hidden
        className={cn(
          'grid size-6 shrink-0 place-items-center rounded-full border',
          mine
            ? 'border-primary/40 bg-accent text-foreground'
            : 'bg-primary text-primary-foreground border-transparent',
        )}
      >
        <Icon className="size-3.5" />
      </span>
      <span className="text-foreground/70 text-[11px] font-semibold tracking-wider uppercase">
        {label}
      </span>
    </div>
  )
}

/**
 * One turn in the transcript.
 *
 * Deliberately not a full-width block of text: the agent's answers are the long
 * ones, so they sit left on the card surface where a paragraph is comfortable
 * to read, and your own lines sit right on the accent tint, where they read as
 * the asides between them.
 */
export function ChatMessage({
  role,
  text,
  tools,
  className,
}: {
  role: ChatRole
  text: string
  /** Tools the agent reached for on this turn. Ignored on your own turns. */
  tools?: string[]
  className?: string
}) {
  const mine = role === 'you'
  const usedTools = !mine && tools && tools.length > 0

  return (
    <div
      className={cn(
        // items-start/end rather than the default stretch, so a one-line reply
        // is a one-line bubble instead of an 85%-wide box with a word in it.
        'flex w-full flex-col gap-1.5',
        mine ? 'items-end' : 'items-start',
        className,
      )}
      data-role={role}
    >
      <Byline role={role} />

      <div
        className={cn(
          'max-w-[85%] rounded-2xl border px-4 py-2.5 text-sm leading-relaxed break-words',
          // One squared corner points the bubble back at its byline, which is
          // what makes the side readable without reading the label again.
          mine
            ? 'border-primary/40 bg-accent text-accent-foreground rounded-tr-sm whitespace-pre-wrap'
            : 'border-border bg-card text-card-foreground rounded-tl-sm shadow-sm',
        )}
      >
        {/* Only the agent writes Markdown. What you typed is shown back to you
            exactly as you typed it — an asterisk in your own message is an
            asterisk, not emphasis you did not ask for. */}
        {mine ? text : <Markdown>{text}</Markdown>}
      </div>

      {usedTools && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-muted-foreground text-[10px] tracking-wide uppercase">used</span>
          {/* Keyed by position: one turn can call the same tool twice. */}
          {tools.map((tool, index) => (
            <Badge
              key={`${tool}-${index}`}
              variant="outline"
              className="font-mono text-[10px] font-normal"
            >
              {tool}
            </Badge>
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * The agent's turn before it has anything to say.
 *
 * Shaped like a real agent turn rather than a line of status text, so the reply
 * lands where the placeholder was instead of shoving the thread down.
 */
export function ChatThinking({ label = 'thinking…' }: { label?: string }) {
  return (
    <div className="flex w-full flex-col items-start gap-1.5">
      <Byline role="agent" />
      <div className="border-border bg-card text-muted-foreground flex w-fit items-center gap-2 rounded-2xl rounded-tl-sm border px-4 py-2.5 text-sm shadow-sm">
        <Loader2 className="size-3.5 animate-spin" aria-hidden />
        {label}
      </div>
    </div>
  )
}
