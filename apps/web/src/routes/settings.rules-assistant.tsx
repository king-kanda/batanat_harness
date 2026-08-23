import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Check, Loader2, Send, Sparkles, TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import { Button } from '#/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { Textarea } from '#/components/ui/textarea'
import { api } from '#/lib/api'

export const Route = createFileRoute('/settings/rules-assistant')({ component: RulesAssistant })

type Turn = { role: 'user' | 'assistant'; content: string }

const OPENERS = [
  'We do solar PV and transmission work across Kenya.',
  'Which procuring entities should I care about?',
  'What should count as urgent enough to buzz my phone?',
]

/**
 * Talk through the criteria, then edit what comes back.
 *
 * The assistant has no tools — it is a conversation about the business, not an
 * agent run. Nothing it writes takes effect until you publish it, and the same
 * validation applies as if you had typed it yourself.
 */
function RulesAssistant() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const versions = useQuery({ queryKey: ['skill'], queryFn: api.skill.versions })
  const active = versions.data?.find((v) => v.is_active)

  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [published, setPublished] = useState<number | null>(null)

  const ask = useMutation({
    mutationFn: (history: Turn[]) => api.skill.draft(history, draft ?? active?.content),
    onSuccess: (response) => {
      setError(null)
      setTurns((t) => [...t, { role: 'assistant', content: response.reply }])
      if (response.proposed_content) setDraft(response.proposed_content)
      if (response.validation && !response.validation.ok) {
        setError(
          `The draft was rejected by the same validation that guards the editor: ${(response.validation.errors ?? []).join(' ')}`,
        )
      }
    },
    onError: (e: Error) => setError(e.message),
  })

  const publish = useMutation({
    mutationFn: () => api.skill.publish(draft ?? '', 'Written with the rules assistant'),
    onSuccess: (version) => {
      setPublished(version.version)
      setError(null)
      queryClient.invalidateQueries({ queryKey: ['skill'] })
    },
    onError: (e: Error) => setError(e.message),
  })

  const send = (text: string) => {
    const message = text.trim()
    if (!message || ask.isPending) return
    const history: Turn[] = [...turns, { role: 'user', content: message }]
    setTurns(history)
    setInput('')
    ask.mutate(history)
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="flex flex-col">
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="text-primary size-4" aria-hidden />
              Talk it through
            </CardTitle>
            <CardDescription>
              Describe your business and what you care about. It asks questions, then writes the
              criteria for you.
            </CardDescription>
          </div>
        </CardHeader>

        <CardContent className="flex flex-1 flex-col gap-3">
          <div className="max-h-[24rem] min-h-[8rem] space-y-4 overflow-y-auto">
            {turns.length === 0 && (
              <div className="space-y-2">
                <p className="text-muted-foreground text-xs">Start with something like:</p>
                {OPENERS.map((opener) => (
                  <button
                    key={opener}
                    type="button"
                    onClick={() => send(opener)}
                    className="border-border hover:border-ring block w-full rounded-sm border px-3 py-2 text-left text-xs transition-colors"
                  >
                    {opener}
                  </button>
                ))}
              </div>
            )}

            {turns.map((turn, index) => (
              <div key={index}>
                <div className="text-muted-foreground mb-0.5 text-[11px] font-medium tracking-wide uppercase">
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
          </div>

          <div className="mt-auto flex items-end gap-2">
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
        </CardContent>
      </Card>

      <Card className="flex flex-col">
        <CardHeader className="flex-wrap gap-2">
          <div className="min-w-0">
            <CardTitle>The document</CardTitle>
            <CardDescription>
              {draft
                ? 'Edit freely before publishing. Nothing takes effect until you do.'
                : active
                  ? 'Your criteria as they stand. A draft will appear here.'
                  : 'No criteria yet.'}
            </CardDescription>
          </div>
          {published != null && (
            <span className="text-status-ok flex items-center gap-1 text-xs">
              <Check className="size-3.5" aria-hidden /> Published v{published}
            </span>
          )}
        </CardHeader>

        <CardContent className="flex flex-1 flex-col gap-3">
          <Textarea
            value={draft ?? active?.content ?? ''}
            onChange={(e) => {
              setDraft(e.target.value)
              setPublished(null)
            }}
            rows={20}
            spellCheck={false}
            className="min-h-[24rem] flex-1 font-mono text-xs leading-relaxed"
            placeholder="# Operating criteria…"
          />

          {error && (
            <p className="text-status-down flex items-start gap-1.5 text-xs">
              <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              {error}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button
              onClick={() => publish.mutate()}
              disabled={publish.isPending || !draft || draft === active?.content}
            >
              {publish.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Check className="size-4" aria-hidden />
              )}
              Publish these rules
            </Button>
            <Button variant="outline" onClick={() => navigate({ to: '/rules' })}>
              Full editor &amp; history
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
