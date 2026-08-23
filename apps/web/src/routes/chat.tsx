import { useMutation } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { Loader2, Send } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { api } from '#/lib/api'

export const Route = createFileRoute('/chat')({ component: Chat })

type Turn = { role: 'you' | 'agent'; text: string; tools?: string[]; runId?: string }

function Chat() {
  const [input, setInput] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [error, setError] = useState<string | null>(null)

  const send = useMutation({
    mutationFn: api.chat,
    onSuccess: (response) => {
      setTurns((t) => [
        ...t,
        {
          role: 'agent',
          text: response.reply ?? '(no reply)',
          tools: response.tool_calls?.map((c) => String(c.tool)) ?? [],
          runId: response.run_id,
        },
      ])
      setError(null)
    },
    onError: (e: Error) => setError(e.message),
  })

  const submit = () => {
    const message = input.trim()
    if (!message) return
    setTurns((t) => [...t, { role: 'you', text: message }])
    setInput('')
    send.mutate(message)
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Chat</CardTitle>
          <CardDescription>
            A trusted turn: the full toolbelt. CRM writes still queue for your approval.
          </CardDescription>
        </div>
        <Badge variant="ok">trusted</Badge>
      </CardHeader>

      <CardContent className="space-y-3">
        <div className="max-h-[26rem] space-y-3 overflow-y-auto">
          {turns.length === 0 && (
            <p className="text-ink-faint text-xs">
              Ask about tenders, email, or the CRM. For example: “which tenders close in the next
              two weeks?”
            </p>
          )}
          {turns.map((turn, index) => (
            <div key={index} className="text-xs">
              <div className="text-ink-faint mb-0.5 text-[11px]">{turn.role}</div>
              <div className="text-ink whitespace-pre-wrap">{turn.text}</div>
              {turn.tools && turn.tools.length > 0 && (
                <div className="text-ink-faint mt-1 font-mono text-[10px]">
                  used: {turn.tools.join(' · ')}
                </div>
              )}
            </div>
          ))}
          {send.isPending && (
            <p className="text-ink-faint flex items-center gap-1.5 text-xs">
              <Loader2 className="size-3 animate-spin" aria-hidden /> thinking…
            </p>
          )}
        </div>

        {error && <p className="text-status-down text-xs">{error}</p>}

        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && submit()}
            placeholder="Ask something…"
            className="bg-surface border-border-subtle text-ink focus:border-accent flex-1 rounded border px-3 py-2 text-xs outline-none"
          />
          <Button variant="primary" onClick={submit} disabled={send.isPending || !input.trim()}>
            <Send className="size-3" aria-hidden />
            Send
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
