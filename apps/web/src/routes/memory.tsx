import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { Trash2 } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { Empty } from '#/components/ui/empty'
import { api } from '#/lib/api'

export const Route = createFileRoute('/memory')({ component: MemoryScreen })

function MemoryScreen() {
  const [search, setSearch] = useState('')
  const queryClient = useQueryClient()
  const memories = useQuery({
    queryKey: ['memories', search],
    queryFn: () => api.memories.list(search || undefined),
  })
  const remove = useMutation({
    mutationFn: api.memories.remove,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['memories'] }),
  })

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Memory</CardTitle>
          <CardDescription>
            Anything tagged <span className="font-mono">untrusted_external</span> is only ever
            shown to the agent as quoted data — never as instruction.
          </CardDescription>
        </div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search…"
          className="bg-surface border-border-subtle text-ink w-40 rounded border px-2 py-1 text-xs outline-none"
        />
      </CardHeader>

      {memories.isPending && <CardContent className="text-ink-faint text-xs">Loading…</CardContent>}
      {memories.data?.length === 0 && (
        <Empty title="Nothing remembered yet">
          The nightly summariser condenses runs and classified email into memory. Semantic
          memories about the business are added as documents are uploaded.
        </Empty>
      )}

      <div>
        {memories.data?.map((memory) => (
          <div
            key={memory.id}
            className="border-border-subtle flex items-start gap-3 border-b px-4 py-2.5 last:border-b-0"
          >
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-2">
                <Badge>{memory.layer}</Badge>
                <Badge variant={memory.instruction_eligible ? 'ok' : 'degraded'}>
                  {memory.trust_tag}
                </Badge>
                {!memory.instruction_eligible && (
                  <span className="text-ink-faint text-[11px]">quoted as data only</span>
                )}
              </div>
              <p className="text-ink mt-1 text-xs">{memory.content}</p>
              <p className="text-ink-faint text-[11px]">
                {memory.source_ref} · {new Date(memory.created_at).toLocaleString()}
              </p>
            </div>
            <Button variant="danger" onClick={() => remove.mutate(memory.id)}>
              <Trash2 className="size-3" aria-hidden />
            </Button>
          </div>
        ))}
      </div>
    </Card>
  )
}
