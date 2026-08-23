import { useMutation } from '@tanstack/react-query'
import { Loader2, Send, Sparkles, TriangleAlert } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '#/components/ui/button'
import { Textarea } from '#/components/ui/textarea'
import { api } from '#/lib/api'
import { cn } from '#/lib/utils'

export type Turn = { role: 'user' | 'assistant'; content: string }

const OPENERS = [
  'We do solar PV and transmission work across Kenya.',
  'Which procuring entities should I care about?',
  'What should count as urgent enough to buzz my phone?',
]

/**
 * The conversation half of the rules assistant.
 *
 * Lives on its own so the full-page version and the drawer on /rules are the
 * same code — two implementations of "talk to it about your criteria" would
 * drift, and the one in the drawer would be the one nobody noticed had broken.
 *
 * It deliberately does not own the document. Whoever mounts it decides where a
 * draft goes: the page puts it in a pane beside the chat, the drawer hands it
 * to the editor already on screen. Publishing is never this component's job.
 */
export function AssistantChat({
  currentContent,
  onDraft,
  className,
}: {
  currentContent?: string
  onDraft: (content: string) => void
  className?: string
}) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const log = useRef<HTMLDivElement>(null)

  const ask = useMutation({
    mutationFn: (history: Turn[]) => api.skill.draft(history, currentContent),
    onSuccess: (response) => {
      setError(null)
      setTurns((t) => [...t, { role: 'assistant', content: response.reply }])
      if (response.proposed_content) onDraft(response.proposed_content)
      if (response.validation && !response.validation.ok) {
        setError(
          'That draft was rejected by the same validation that guards the editor: ' +
            (response.validation.errors ?? []).join(' '),
        )
      }
    },
    onError: (e: Error) => setError(e.message),
  })

  // Follow the conversation as it grows.
  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight, behavior: 'smooth' })
  }, [turns.length, ask.isPending])

  const send = (text: string) => {
    const message = text.trim()
    if (!message || ask.isPending) return
    const history: Turn[] = [...turns, { role: 'user', content: message }]
    setTurns(history)
    setInput('')
    ask.mutate(history)
  }

  return (
    <div className={cn('flex min-h-0 flex-1 flex-col gap-3', className)}>
      <div ref={log} className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
        {turns.length === 0 && (
          <div className="flex flex-col gap-2">
            <p className="text-muted-foreground text-xs">Start with something like:</p>
            {OPENERS.map((opener) => (
              <button
                key={opener}
                type="button"
                onClick={() => send(opener)}
                className="border-border hover:border-ring block w-full rounded-lg border px-3 py-2 text-left text-xs transition-colors"
              >
                {opener}
              </button>
            ))}
          </div>
        )}

        {turns.map((turn, index) => (
          <div key={index}>
            <div className="text-muted-foreground mb-0.5 flex items-center gap-1.5 text-[11px] font-medium tracking-wide uppercase">
              {turn.role === 'assistant' && <Sparkles className="text-primary size-3" aria-hidden />}
              {turn.role === 'user' ? 'You' : 'Assistant'}
            </div>
            <div className="text-sm leading-relaxed whitespace-pre-wrap">{turn.content}</div>
          </div>
        ))}

        {ask.isPending && (
          <p className="text-muted-foreground flex items-center gap-2 text-xs">
            <Loader2 className="size-3.5 animate-spin" aria-hidden /> thinking…
          </p>
        )}

        {error && (
          <p className="text-status-down flex items-start gap-1.5 text-xs">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            {error}
          </p>
        )}
      </div>

      <div className="flex items-end gap-2">
        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send(input)
            }
          }}
          rows={2}
          placeholder="Tell it about your business…"
          className="min-h-[2.75rem] resize-none"
        />
        <Button onClick={() => send(input)} disabled={ask.isPending || !input.trim()} size="icon">
          <Send className="size-4" aria-hidden />
          <span className="sr-only">Send</span>
        </Button>
      </div>
    </div>
  )
}
