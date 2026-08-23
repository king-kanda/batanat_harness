import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, PlayCircle, Trash2, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '#/components/ui/alert-dialog'
import { Button } from '#/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { api } from '#/lib/api'

/** Plural labels for the ledger's entity types, in the order they read best. */
const LABELS: Array<[string, string, string]> = [
  ['email', 'email', 'emails'],
  ['tender', 'tender', 'tenders'],
  ['run', 'run', 'runs'],
  ['approval', 'approval', 'approvals'],
]

function describe(counts: Record<string, number>): string {
  const parts = LABELS.filter(([key]) => (counts[key] ?? 0) > 0).map(([key, one, many]) => {
    const n = counts[key] ?? 0
    return `${n} ${n === 1 ? one : many}`
  })
  if (parts.length === 0) return 'nothing'
  if (parts.length === 1) return parts[0]
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`
}

/**
 * Load a worked example, then take it away again.
 *
 * The point is walking someone through a system that has something in it —
 * empty screens explain nothing — and then handing them the same app, empty,
 * to put their own work into.
 *
 * Clearing is bounded by a ledger written when the data was seeded, so it can
 * only remove rows the seeder created. That is the whole reason this is safe to
 * put behind a button: matching on ids that look like fixtures would eventually
 * match something real, and this cannot.
 */
export function DemoData() {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)

  const demo = useQuery({ queryKey: ['demo'], queryFn: api.demo.status })

  const seed = useMutation({
    mutationFn: api.demo.seed,
    onSuccess: (state) => {
      // Sample data touches most screens, so refresh all of them.
      queryClient.invalidateQueries()
      toast.success(`Loaded ${describe(state.counts ?? {})}.`)
    },
    onError: (error: Error) => toast.error(error.message),
  })

  const clear = useMutation({
    mutationFn: api.demo.clear,
    onSuccess: () => {
      queryClient.invalidateQueries()
      setConfirming(false)
      toast.success('Sample data removed. The app is yours.')
    },
    onError: (error: Error) => {
      setConfirming(false)
      toast.error(error.message)
    },
  })

  const busy = seed.isPending || clear.isPending
  const loaded = demo.data?.loaded ?? false
  const counts = demo.data?.counts ?? {}

  return (
    <Card data-tour="demo-data">
      <CardHeader>
        <div>
          <CardTitle>Sample data</CardTitle>
          <CardDescription>
            {loaded
              ? 'A worked example is loaded. Clear it when you are ready to use your own.'
              : 'Fill the app with a realistic example — classified email, live tenders, a run you can open, and one write waiting for approval. Nothing leaves this machine.'}
          </CardDescription>
        </div>
      </CardHeader>

      <CardContent className="flex flex-col gap-3">
        {loaded && (
          <p className="text-muted-foreground text-xs">
            Currently loaded: <span className="text-foreground">{describe(counts)}</span>.
          </p>
        )}

        {loaded && demo.data?.crm_dry_run === false && (
          <p className="text-status-degraded flex items-start gap-1.5 text-xs">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            CRM dry run is off. Approving the sample approval would write a fictional company
            to your real Zoho — clear the sample data, or turn <span className="font-mono">
              CRM_DRY_RUN
            </span>{' '}
            back on first.
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => seed.mutate()} disabled={busy} variant={loaded ? 'outline' : 'default'}>
            {seed.isPending ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <PlayCircle className="size-4" aria-hidden />
            )}
            {loaded ? 'Reload sample data' : 'Load sample data'}
          </Button>

          {loaded && (
            <Button variant="outline" onClick={() => setConfirming(true)} disabled={busy}>
              {clear.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Trash2 className="size-4" aria-hidden />
              )}
              Clear sample data
            </Button>
          )}
        </div>
      </CardContent>

      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Clear the sample data?</AlertDialogTitle>
            <AlertDialogDescription>
              This deletes {describe(counts)} — only the rows loaded as samples. Anything you
              have connected, uploaded or written stays exactly as it is.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep it</AlertDialogCancel>
            <AlertDialogAction onClick={() => clear.mutate()}>Clear it</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}
