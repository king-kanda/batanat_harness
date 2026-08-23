import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Check, Loader2, Sparkles, TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import { AssistantChat } from '#/components/rules-assistant'
import { Button } from '#/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { Textarea } from '#/components/ui/textarea'
import { api } from '#/lib/api'

export const Route = createFileRoute('/settings/rules-assistant')({ component: RulesAssistant })

/**
 * The full-page version of the rules assistant: chat on the left, the document
 * it is writing on the right.
 *
 * The same conversation is available as a drawer on /rules, where the draft
 * lands in the editor already on screen. Both mount the same `AssistantChat`;
 * only the destination for a draft differs.
 */
function RulesAssistant() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const versions = useQuery({ queryKey: ['skill'], queryFn: api.skill.versions })
  const active = versions.data?.find((v) => v.is_active)

  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [published, setPublished] = useState<number | null>(null)

  const publish = useMutation({
    mutationFn: () => api.skill.publish(draft ?? '', 'Written with the rules assistant'),
    onSuccess: (version) => {
      setPublished(version.version)
      setError(null)
      queryClient.invalidateQueries({ queryKey: ['skill'] })
    },
    onError: (e: Error) => setError(e.message),
  })

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="flex max-h-[42rem] flex-col">
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

        <CardContent className="flex min-h-0 flex-1 flex-col">
          <AssistantChat
            currentContent={draft ?? active?.content}
            onDraft={(content) => {
              setDraft(content)
              setPublished(null)
            }}
          />
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
