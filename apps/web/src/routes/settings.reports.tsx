import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { Loader2, Mail, Plus, Save, SendHorizontal, Trash2, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Alert, AlertDescription } from '#/components/ui/alert'
import { Button } from '#/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { Empty } from '#/components/ui/empty'
import { Input } from '#/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '#/components/ui/table'
import { api } from '#/lib/api'
import { cn } from '#/lib/utils'

export const Route = createFileRoute('/settings/reports')({ component: ReportRecipients })

type Delivery = 'to' | 'cc'

type Row = {
  /** Local only. Rows are identified by position in the API's two strings. */
  id: string
  address: string
  delivery: Delivery
}

/** Mirrors `EMAIL_PATTERN` in the API — a typo check, not RFC validation. */
const LOOKS_LIKE_EMAIL = /^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$/

const newId = () => crypto.randomUUID()

function split(raw: string, delivery: Delivery): Row[] {
  return raw
    .split(/[,;]/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((address) => ({ id: newId(), address, delivery }))
}

function join(rows: Row[], delivery: Delivery): string {
  return rows
    .filter((row) => row.delivery === delivery && row.address.trim())
    .map((row) => row.address.trim())
    .join(', ')
}

function ReportRecipients() {
  const queryClient = useQueryClient()
  const current = useQuery({ queryKey: ['report-recipients'], queryFn: api.reports.recipients.get })

  const [rows, setRows] = useState<Row[]>([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  // Seed once. Re-seeding on every settle would discard what someone is typing.
  useEffect(() => {
    if (current.data && !loaded) {
      setRows([...split(current.data.to, 'to'), ...split(current.data.cc, 'cc')])
      setLoaded(true)
    }
  }, [current.data, loaded])

  const update = (id: string, patch: Partial<Row>) => {
    setSaved(false)
    setRows((previous) => previous.map((row) => (row.id === id ? { ...row, ...patch } : row)))
  }

  const remove = (id: string) => {
    setSaved(false)
    setRows((previous) => previous.filter((row) => row.id !== id))
  }

  const add = () => {
    setSaved(false)
    setRows((previous) => [...previous, { id: newId(), address: '', delivery: 'to' }])
  }

  const test = useMutation({ mutationFn: api.test.email })

  const save = useMutation({
    mutationFn: () =>
      api.reports.recipients.update({ to: join(rows, 'to'), cc: join(rows, 'cc') }),
    onSuccess: (view) => {
      setError(null)
      setSaved(true)
      queryClient.setQueryData(['report-recipients'], view)
      setRows([...split(view.to, 'to'), ...split(view.cc, 'cc')])
    },
    onError: (e: Error) => {
      setSaved(false)
      setError(e.message)
    },
  })

  const filled = rows.filter((row) => row.address.trim())
  const invalid = filled.filter((row) => !LOOKS_LIKE_EMAIL.test(row.address.trim()))
  const toCount = filled.filter((row) => row.delivery === 'to').length

  const dirty = current.data
    ? join(rows, 'to') !== current.data.to || join(rows, 'cc') !== current.data.cc
    : false

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start gap-3">
          <span className="bg-muted flex size-9 shrink-0 items-center justify-center rounded-xl">
            <Mail className="size-4" aria-hidden />
          </span>
          <div className="min-w-0">
            <CardTitle>Report recipients</CardTitle>
            <CardDescription>
              Who receives your tender reports. The sender address is set on the server; the
              destinations are yours to change. Everyone on <strong>To</strong> gets the report;{' '}
              <strong>Cc</strong> is copied in.
            </CardDescription>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {rows.length === 0 ? (
          <Empty title="No recipients yet">
            Reports cannot be delivered until at least one To address is set.
          </Empty>
        ) : (
          <div className="overflow-x-auto">
            <Table className="table-fixed">
              <TableHeader>
                <TableRow>
                  <TableHead>Address</TableHead>
                  <TableHead className="w-32">Delivery</TableHead>
                  <TableHead className="w-12 text-right">
                    <span className="sr-only">Remove</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => {
                  const bad = row.address.trim() !== '' && !LOOKS_LIKE_EMAIL.test(row.address.trim())
                  return (
                    <TableRow key={row.id}>
                      <TableCell className="min-w-0 align-middle">
                        <Input
                          type="email"
                          value={row.address}
                          placeholder="name@example.com"
                          aria-label="Recipient address"
                          aria-invalid={bad || undefined}
                          onChange={(e) => update(row.id, { address: e.target.value })}
                          className={cn('font-mono text-sm', bad && 'border-status-down')}
                        />
                      </TableCell>
                      <TableCell className="align-middle">
                        <div
                          role="group"
                          aria-label="Delivery"
                          className="bg-muted inline-flex rounded-lg p-0.5"
                        >
                          {(['to', 'cc'] as const).map((option) => (
                            <button
                              key={option}
                              type="button"
                              aria-pressed={row.delivery === option}
                              onClick={() => update(row.id, { delivery: option })}
                              className={cn(
                                'rounded-md px-2.5 py-1 text-xs font-medium capitalize transition-colors',
                                row.delivery === option
                                  ? 'bg-background shadow-sm'
                                  : 'text-muted-foreground hover:text-foreground',
                              )}
                            >
                              {option}
                            </button>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell className="text-right align-middle">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => remove(row.id)}
                          aria-label={`Remove ${row.address || 'recipient'}`}
                        >
                          <Trash2 className="size-3.5" aria-hidden />
                        </Button>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        )}

        <Button variant="outline" size="sm" onClick={add}>
          <Plus className="size-3.5" aria-hidden />
          Add recipient
        </Button>

        {invalid.length > 0 && (
          <Alert variant="destructive">
            <AlertDescription>
              {invalid.length === 1 ? 'This address does not' : 'These addresses do not'} look
              valid: {invalid.map((row) => row.address.trim()).join(', ')}
            </AlertDescription>
          </Alert>
        )}

        {filled.length > 0 && toCount === 0 && (
          <Alert>
            <TriangleAlert className="size-4" aria-hidden />
            <AlertDescription>
              Everyone here is on Cc, so there is nobody to send to. Set at least one address to To.
            </AlertDescription>
          </Alert>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {test.data && (
          <Alert variant={test.data.sent ? 'default' : 'destructive'}>
            <AlertDescription>
              {test.data.sent
                ? `Test email sent to ${test.data.target}. If it does not arrive, check spam — SendGrid accepted it.`
                : `Not sent: ${test.data.error}`}
            </AlertDescription>
          </Alert>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="text-muted-foreground text-xs">
            {saved
              ? 'Saved.'
              : dirty
                ? 'Unsaved changes.'
                : toCount > 0
                  ? `${toCount} recipient${toCount === 1 ? '' : 's'} on the next send.`
                  : 'No reports will be delivered.'}
          </div>
          <div className="flex items-center gap-2">
            {/* Sends for real. An unverified SendGrid sender only fails at send
                time, so nothing short of an actual send proves this works. */}
            <Button
              variant="outline"
              onClick={() => test.mutate()}
              disabled={test.isPending || dirty || toCount === 0}
              title={
                dirty
                  ? 'Save first — the test uses the saved recipients.'
                  : 'Sends a real email to the addresses above'
              }
            >
              {test.isPending ? (
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
              ) : (
                <SendHorizontal className="size-3.5" aria-hidden />
              )}
              Send test email
            </Button>
            <Button
              onClick={() => save.mutate()}
              disabled={!dirty || save.isPending || invalid.length > 0}
            >
              {save.isPending ? (
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
              ) : (
                <Save className="size-3.5" aria-hidden />
              )}
              Save
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
