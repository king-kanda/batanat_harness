import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate, useSearch } from '@tanstack/react-router'
import { Loader2, Send, SquarePen, TriangleAlert } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { ChatMessage, ChatThinking } from '#/components/chat-message'
import { Button } from '#/components/ui/button'
import { Card, CardContent } from '#/components/ui/card'
import { Textarea } from '#/components/ui/textarea'
import { ApiError, api } from '#/lib/api'
import { cn } from '#/lib/utils'

type Search = { c?: string }

export const Route = createFileRoute('/')({
  component: Home,
  validateSearch: (search: Record<string, unknown>): Search => ({
    c: typeof search.c === 'string' ? search.c : undefined,
  }),
})

type Turn = { role: 'you' | 'agent'; text: string; tools?: string[] }

/**
 * The thread this tab is in, when the URL does not name one.
 *
 * `?c=<id>` is the source of truth — it makes a conversation linkable and lets
 * the sidebar switch between them. sessionStorage only answers "which thread
 * was I in?" on a bare reload of `/`. Session rather than local storage
 * because a second tab is a second conversation.
 */
const THREAD_KEY = 'batanat.conversation'

const rememberedThread = () =>
  typeof sessionStorage === 'undefined' ? null : sessionStorage.getItem(THREAD_KEY)

/**
 * Chat is the front door to the harness.
 *
 * The stat strip is an opening gambit, not furniture: it answers "anything need
 * me?" at a glance and links straight to wherever that thing lives. The moment
 * someone starts typing it gets out of the way, because from then on the
 * conversation is the interface.
 */
function Home() {
  const { c: urlThread } = useSearch({ from: '/' })
  const navigate = useNavigate({ from: '/' })
  const queryClient = useQueryClient()

  const [input, setInput] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [error, setError] = useState<string | null>(null)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [restoring, setRestoring] = useState(false)

  // The URL names the thread; sessionStorage only answers a bare `/`.
  const wanted = urlThread ?? rememberedThread()

  // Load whenever the wanted thread changes, which is how clicking a different
  // conversation in the sidebar swaps the transcript.
  //
  // Failure is not surfaced: a thread that was deleted, or belongs to a
  // signed-out session, should quietly become a new chat rather than greet you
  // with an error you cannot act on.
  useEffect(() => {
    if (!wanted) {
      setConversationId(null)
      setTurns([])
      return
    }
    if (wanted === conversationId) return

    let cancelled = false
    setRestoring(true)
    api.conversations
      .get(wanted)
      .then((detail) => {
        if (cancelled) return
        setConversationId(detail.conversation.id)
        sessionStorage.setItem(THREAD_KEY, detail.conversation.id)
        setTurns(
          (detail.messages ?? []).map((m) => ({
            role: m.role === 'user' ? ('you' as const) : ('agent' as const),
            text: m.content,
          })),
        )
      })
      .catch(() => {
        if (cancelled) return
        sessionStorage.removeItem(THREAD_KEY)
        setConversationId(null)
        setTurns([])
      })
      .finally(() => {
        if (!cancelled) setRestoring(false)
      })

    return () => {
      cancelled = true
    }
    // `conversationId` is deliberately excluded: including it would re-run the
    // effect after a load and fight the state it just set.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wanted])

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

  // Starting a new thread is a fresh start, so the summary comes back. Keyed on
  // the thread rather than on `engaged`, because clearing the input box must
  // *not* bring it back — that is the flicker the comment above guards against.
  useEffect(() => {
    if (!wanted) setGreetingMounted(true)
  }, [wanted])

  const send = useMutation({
    mutationFn: (message: string) => api.chat(message, conversationId ?? undefined),
    onSuccess: (response) => {
      setConversationId(response.conversation_id)
      sessionStorage.setItem(THREAD_KEY, response.conversation_id)
      // Put the new thread in the URL so it is linkable and the sidebar can
      // highlight it. `replace` keeps Back meaning "the page before chat".
      if (urlThread !== response.conversation_id) {
        navigate({ search: { c: response.conversation_id }, replace: true })
      }
      // The first message of a thread creates it, and renames it on every
      // turn's `last_message_at` — the list has to hear about both.
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
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

  // Follow the thread as it grows. A reply that lands below the fold reads as
  // nothing having happened, and the send box is at the bottom of the page.
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (turns.length === 0) return
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns.length, send.isPending])

  const submit = () => {
    const message = input.trim()
    if (!message || send.isPending) return
    setTurns((t) => [...t, { role: 'you', text: message }])
    setInput('')
    send.mutate(message)
  }

  const startNewThread = () => {
    sessionStorage.removeItem(THREAD_KEY)
    setConversationId(null)
    setTurns([])
    setError(null)
    setGreetingMounted(true)
    navigate({ search: {}, replace: true })
  }

  const started = turns.length > 0

  return (
    // One viewport tall, in three bands: the thread's header, the only
    // scrolling region on the screen, and the composer pinned under it. The box
    // you type in must not drift down the page as the conversation grows.
    <div
      className={cn(
        'mx-auto flex min-h-0 w-full max-w-2xl flex-1 flex-col gap-4',
        // Nothing to scroll yet, so the greeting and the composer sit together
        // in the middle. pb-16 is the optical offset that keeps them off the
        // floor of the viewport.
        !started && 'justify-center pb-16',
      )}
    >
      {started && (
        <div className="flex shrink-0 items-center gap-3">
          <span className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">
            Conversation
          </span>
          <span className="bg-border h-px flex-1" aria-hidden />
          <Button variant="ghost" size="sm" onClick={startNewThread} disabled={send.isPending}>
            <SquarePen className="size-3.5" aria-hidden />
            New chat
          </Button>
        </div>
      )}

      <div
        className={cn(
          'flex flex-col gap-6',
          // overscroll-contain: reaching the top of the transcript should stop
          // there, not hand the gesture to whatever is behind it.
          started ? 'min-h-0 flex-1 overflow-y-auto overscroll-contain pb-2' : 'shrink-0',
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

        {restoring && !started && (
          <p className="text-muted-foreground flex items-center gap-2 text-sm">
            <Loader2 className="size-3.5 animate-spin" aria-hidden /> picking up where you left off…
          </p>
        )}

        {started && (
          /* A log rather than a list: replies arrive without the reader asking,
             so a screen reader should announce them where they land. */
          <div className="space-y-5" role="log" aria-live="polite" aria-label="Conversation">
            {turns.map((turn, index) => (
              <ChatMessage key={index} role={turn.role} text={turn.text} tools={turn.tools} />
            ))}
            {send.isPending && <ChatThinking />}
            <div ref={endRef} aria-hidden />
          </div>
        )}
      </div>

      {/* Pinned: everything you act with stays where you last saw it. */}
      <div className="flex shrink-0 flex-col gap-3">
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
              rows={4}
              placeholder="Ask about tenders, email or the CRM…"
              // Roomy enough to see a few lines of what you are writing, and it
              // grows from there rather than scrolling inside four fixed rows.
              className="max-h-64 min-h-[6.5rem] resize-none border-0 shadow-none focus-visible:ring-0"
            />
            <Button
              onClick={submit}
              disabled={send.isPending || !input.trim()}
              size="icon"
              className="mb-1"
            >
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
