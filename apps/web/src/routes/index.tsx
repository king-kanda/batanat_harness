import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import { Loader2, Send, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Button } from '#/components/ui/button'
import { Card, CardContent } from '#/components/ui/card'
import { Textarea } from '#/components/ui/textarea'
import { ApiError, api } from '#/lib/api'
import { cn } from '#/lib/utils'

export const Route = createFileRoute('/')({ component: Home })

type Turn = { role: 'you' | 'agent'; text: string; tools?: string[] }

/**
 * Chat is the front door to the harness.
 *
 * The stat strip is an opening gambit, not furniture: it answers "anything need
 * me?" at a glance and links straight to wherever that thing lives. The moment
 * someone starts typing it gets out of the way, because from then on the
 * conversation is the interface.
 */
function Home() {
  const [input, setInput] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [error, setError] = useState<string | null>(null)

  // Once you have engaged, the summary is noise. It does not come back on
  // clearing the box — that would make it flicker while you edit.
  const engaged = turns.length > 0 || input.length > 0

  // Unmount on a timer rather than relying on the CSS transition to finish.
  // A collapsed-but-present element depends on animation actually running, and
  // it does not under prefers-reduced-motion or in a throttled/background tab —
  // which would leave the strip sitting there forever.
  const [greetingMounted, setGreetingMounted] = useState(true)
  useEffect(() => {
    if (!engaged) return
    const timer = setTimeout(() => setGreetingMounted(false), 320)
    return () => clearTimeout(timer)
  }, [engaged])

  const send = useMutation({
    mutationFn: api.chat,
    onSuccess: (response) => {
      setTurns((t) => [
        ...t,
        {
          role: 'agent',
          text: response.reply ?? '(no reply)',
          tools: response.tool_calls?.map((c) => String(c.tool)) ?? [],
        },
      ])
      setError(null)
    },
    onError: (e: Error) => setError(e instanceof ApiError ? e.message : 'Unexpected error'),
  })

  const submit = () => {
    const message = input.trim()
    if (!message || send.isPending) return
    setTurns((t) => [...t, { role: 'you', text: message }])
    setInput('')
    send.mutate(message)
  }

  return (
    <div
      className={cn(
        'mx-auto flex w-full max-w-2xl flex-col gap-6',
        // Empty state sits in the middle of the viewport; once there is a
        // transcript it anchors to the top so replies grow downward.
        turns.length === 0 && 'min-h-[calc(100svh-9rem)] justify-center pb-16',
      )}
    >
      {greetingMounted && (
        <div
          className={cn(
            'overflow-hidden transition-all duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none',
            engaged
              ? 'pointer-events-none max-h-0 -translate-y-2 opacity-0'
              : 'max-h-96 translate-y-0 opacity-100',
          )}
          aria-hidden={engaged}
        >
          <Greeting />
        </div>
      )}

      {turns.length > 0 && (
        <div className="space-y-5">
          {turns.map((turn, index) => (
            <div key={index}>
              <div className="text-muted-foreground mb-1 text-[11px] font-medium tracking-wide uppercase">
                {turn.role}
              </div>
              <div className="text-sm leading-relaxed whitespace-pre-wrap">{turn.text}</div>
              {turn.tools && turn.tools.length > 0 && (
                <div className="text-muted-foreground mt-1.5 font-mono text-[10px]">
                  used: {turn.tools.join(' · ')}
                </div>
              )}
            </div>
          ))}
          {send.isPending && (
            <p className="text-muted-foreground flex items-center gap-2 text-sm">
              <Loader2 className="size-3.5 animate-spin" aria-hidden /> thinking…
            </p>
          )}
        </div>
      )}

      {error && (
        <div className="border-status-down/30 bg-status-down/10 text-status-down flex items-start gap-2 rounded-lg border px-3 py-2 text-xs">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {error}
        </div>
      )}

      <Card className="py-0 shadow-sm" data-tour="chat-input">
        <CardContent className="flex items-end gap-2 p-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit()
              }
            }}
            rows={2}
            placeholder="Ask about tenders, email or the CRM…"
            className="min-h-[3rem] resize-none border-0 shadow-none focus-visible:ring-0"
          />
          <Button onClick={submit} disabled={send.isPending || !input.trim()} size="icon">
            <Send className="size-4" aria-hidden />
            <span className="sr-only">Send</span>
          </Button>
        </CardContent>
      </Card>

      {!engaged && (
        <p className="text-muted-foreground text-center text-xs">
          Writes to the CRM are queued for your approval, never made directly.
        </p>
      )}
    </div>
  )
}

/** The opening summary: what is waiting, and where it lives. */
function Greeting() {
  const dashboard = useQuery({ queryKey: ['dashboard'], queryFn: api.dashboard })
  const data = dashboard.data

  // Typed so every card may carry a tone; `as const` alone narrows each object
  // to only the keys it happens to set.
  const cards: Array<{
    label: string
    value: number | string
    hint: string
    to: string
    tone?: 'degraded' | 'down'
  }> = [
    {
      label: 'Opportunities',
      value: data?.opportunities_today ?? 0,
      hint: 'last 24h',
      to: '/opportunities',
    },
    { label: 'Tenders', value: data?.tenders_today ?? 0, hint: 'last 24h', to: '/opportunities' },
    {
      label: 'Approvals',
      value: data?.pending_approvals ?? 0,
      hint: 'awaiting you',
      to: '/approvals',
      tone: (data?.pending_approvals ?? 0) > 0 ? 'degraded' : undefined,
    },
    {
      label: 'Connections',
      value: `${data?.connections_healthy ?? 0}/${data?.connections_total ?? 0}`,
      hint: data?.connections_needing_attention?.length
        ? data.connections_needing_attention.join(', ')
        : 'all healthy',
      to: '/settings/connections',
      tone: data?.connections_needing_attention?.length ? 'down' : undefined,
    },
  ]

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h2 className="text-3xl font-extrabold tracking-tight text-balance sm:text-4xl">
          What do you need to{' '}
          <span className="text-italic-serif font-normal">know today</span>?
        </h2>
        <p className="text-muted-foreground mt-2 text-sm">
          Ask below, or pick up whatever is waiting.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {cards.map((card) => (
          <Link
            key={card.label}
            to={card.to as never}
            className="group border-border bg-card hover:border-ring min-w-0 rounded-xl border p-3 transition-all hover:-translate-y-0.5 hover:shadow-md"
          >
            <div className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">
              {card.label}
            </div>
            <div
              className={cn(
                'tabular mt-1 text-2xl font-bold tracking-tight',
                card.tone === 'degraded' && 'text-status-degraded',
                card.tone === 'down' && 'text-status-down',
              )}
            >
              {dashboard.isPending ? '—' : card.value}
            </div>
            <div className="text-muted-foreground mt-0.5 truncate text-[11px]">{card.hint}</div>
          </Link>
        ))}
      </div>
    </div>
  )
}
