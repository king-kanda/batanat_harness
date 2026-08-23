import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { Check, History, Loader2, RotateCcw, Sparkles, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'

import { AssistantChat } from '#/components/rules-assistant'
import { StatusBadge } from '#/components/status-badge'
import { Button } from '#/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '#/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '#/components/ui/tabs'
import { api } from '#/lib/api'
import { cn } from '#/lib/utils'

export const Route = createFileRoute('/rules')({ component: Rules })

function Rules() {
  const queryClient = useQueryClient()
  const versions = useQuery({ queryKey: ['skill'], queryFn: api.skill.versions })
  const active = versions.data?.find((v) => v.is_active)

  const [draft, setDraft] = useState('')
  const [touched, setTouched] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [assistantWrote, setAssistantWrote] = useState(false)

  // Load the active version once, then leave the editor alone.
  useEffect(() => {
    if (active && !touched) setDraft(active.content)
  }, [active, touched])

  const validation = useQuery({
    queryKey: ['skill-validate', draft],
    queryFn: () => api.skill.validate(draft),
    enabled: draft.length > 0,
  })

  const publish = useMutation({
    mutationFn: () => api.skill.publish(draft),
    onSuccess: (version) => {
      setTouched(false)
      setMessage(`Published version ${version.version}.`)
      queryClient.invalidateQueries({ queryKey: ['skill'] })
    },
    onError: (error: Error) => setMessage(error.message),
  })

  const rollback = useMutation({
    mutationFn: (version: number) => api.skill.rollback(version),
    onSuccess: (version) => {
      setTouched(false)
      setMessage(`Rolled back — now version ${version.version}.`)
      queryClient.invalidateQueries({ queryKey: ['skill'] })
    },
    onError: (error: Error) => setMessage(error.message),
  })

  const dirty = touched && draft !== active?.content
  const blocked = validation.data?.ok === false

  return (
    <>
    <Tabs defaultValue="editor" className="space-y-4">
      <TabsList>
        <TabsTrigger value="editor">Editor</TabsTrigger>
        <TabsTrigger value="history">
          History{versions.data?.length ? ` (${versions.data.length})` : ''}
        </TabsTrigger>
      </TabsList>

      <TabsContent value="editor">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Rules — Skill.MD</CardTitle>
            <CardDescription>
              What counts as an opportunity, and what matters. Criteria only: security rules live
              in code, so nothing typed here can widen what the agent may do.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            {active && <StatusBadge tone="ok">v{active.version} active</StatusBadge>}
            <Button
              variant="outline"
              size="sm"
              onClick={() => setAssistantOpen(true)}
              data-tour="rules-assistant"
            >
              <Sparkles className="size-3.5" aria-hidden />
              Draft with assistant
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-3">
          <textarea
            data-tour="rules-editor"
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value)
              setTouched(true)
              setMessage(null)
            }}
            rows={22}
            spellCheck={false}
            placeholder="# Operating criteria…"
            className="bg-muted border-border text-foreground focus:border-ring w-full resize-y rounded-lg border p-3 font-mono text-xs leading-relaxed outline-none"
          />

          {assistantWrote && (
            <p className="text-primary-foreground bg-accent flex items-start gap-1.5 rounded-lg px-3 py-2 text-xs">
              <Sparkles className="text-primary mt-0.5 size-3.5 shrink-0" aria-hidden />
              The assistant wrote into the editor above. Read it, change anything you disagree
              with, then publish — nothing is live until you do.
            </p>
          )}

          {validation.data?.errors?.map((error) => (
            <p key={error} className="text-status-down flex items-start gap-1.5 text-xs">
              <TriangleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
              {error}
            </p>
          ))}
          {validation.data?.warnings?.map((warning) => (
            <p key={warning} className="text-status-degraded text-xs">
              {warning}
            </p>
          ))}
          {message && <p className="text-muted-foreground text-xs">{message}</p>}

          <div className="flex items-center gap-2">
            <Button
              variant="default"
              disabled={!dirty || blocked || publish.isPending}
              onClick={() => publish.mutate()}
              title={blocked ? 'Fix the errors above first' : undefined}
            >
              {publish.isPending ? (
                <Loader2 className="size-3 animate-spin" aria-hidden />
              ) : (
                <Check className="size-3" aria-hidden />
              )}
              Publish new version
            </Button>
            {dirty && (
              <Button
                onClick={() => {
                  setDraft(active?.content ?? '')
                  setTouched(false)
                }}
              >
                Discard changes
              </Button>
            )}
            <span className="text-muted-foreground/80 tabular ml-auto text-[11px]">
              {draft.length.toLocaleString()} characters
            </span>
          </div>
        </CardContent>
      </Card>
      </TabsContent>

      <TabsContent value="history">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Version history</CardTitle>
            <CardDescription>
              Versions are immutable — a rollback publishes the old text as a new version, so every
              run still traces to exactly what was live.
            </CardDescription>
          </div>
          <History className="text-muted-foreground/80 size-4" aria-hidden />
        </CardHeader>
        <div>
          {versions.data?.map((version) => (
            <div
              key={version.id}
              className={cn(
                'border-border flex items-baseline gap-3 border-b px-4 py-2 text-xs last:border-b-0',
                version.is_active && 'bg-muted',
              )}
            >
              <span className="text-foreground w-10 shrink-0 font-mono">v{version.version}</span>
              {version.is_active && <StatusBadge tone="ok">active</StatusBadge>}
              <span className="text-muted-foreground/80 truncate">
                {version.notes ?? `by ${version.created_by ?? 'unknown'}`}
              </span>
              <span className="text-muted-foreground/80 tabular ml-auto shrink-0">
                {new Date(version.created_at).toLocaleDateString()}
              </span>
              {!version.is_active && (
                <Button
                  onClick={() => rollback.mutate(version.version)}
                  disabled={rollback.isPending}
                >
                  <RotateCcw className="size-3" aria-hidden />
                  Roll back
                </Button>
              )}
            </div>
          ))}
        </div>
      </Card>
      </TabsContent>
    </Tabs>

    {/* A drawer rather than its own page: the document you are discussing stays
        where it is, and whatever the assistant writes lands in the editor you
        were already using — same validation, same Publish button, one path to
        production. */}
    <Sheet open={assistantOpen} onOpenChange={setAssistantOpen}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 sm:max-w-lg">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <Sparkles className="text-primary size-4" aria-hidden />
            Draft with assistant
          </SheetTitle>
          <SheetDescription>
            Describe your business and what you care about. It asks questions, then writes the
            criteria into the editor behind this panel. It has no tools and cannot act on
            anything — it only drafts text for you to approve.
          </SheetDescription>
        </SheetHeader>

        <div className="flex min-h-0 flex-1 flex-col px-4 pb-4">
          <AssistantChat
            currentContent={draft || active?.content}
            onDraft={(content) => {
              setDraft(content)
              setTouched(true)
              setAssistantWrote(true)
              setMessage(null)
            }}
          />
          {assistantWrote && (
            <Button
              variant="outline"
              className="mt-3"
              onClick={() => setAssistantOpen(false)}
            >
              <Check className="size-3.5" aria-hidden />
              Close and review the draft
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
    </>
  )
}
