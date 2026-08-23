import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { FileText, Loader2, Trash2, Upload } from 'lucide-react'
import { useRef, useState } from 'react'

import { StatusBadge } from '#/components/status-badge'
import { Button } from '#/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '#/components/ui/tabs'
import { Empty } from '#/components/ui/empty'
import { api } from '#/lib/api'
import { humaniseShort } from '#/lib/labels'
import { cn } from '#/lib/utils'

export const Route = createFileRoute('/settings/knowledge')({ component: KnowledgeBase })

const TRUST_OPTIONS = [
  {
    value: 'user_asserted',
    label: 'Our own information',
    detail: 'Capability statements, past deals, company facts. Can inform the agent directly.',
  },
  {
    value: 'untrusted_external',
    label: 'Third-party document',
    detail: 'Tender documents, supplier PDFs. Retrievable, but only ever quoted as data.',
  },
] as const

function KnowledgeBase() {
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [trust, setTrust] = useState<string>('user_asserted')
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const documents = useQuery({ queryKey: ['knowledge'], queryFn: api.knowledge.list })

  const upload = useMutation({
    mutationFn: (file: File) => api.knowledge.upload(file, trust),
    onSuccess: () => {
      setError(null)
      queryClient.invalidateQueries({ queryKey: ['knowledge'] })
      queryClient.invalidateQueries({ queryKey: ['memories'] })
    },
    onError: (e: Error) => setError(e.message),
  })

  const remove = useMutation({
    mutationFn: api.knowledge.remove,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge'] })
      queryClient.invalidateQueries({ queryKey: ['memories'] })
    },
    onError: (e: Error) => setError(e.message),
  })

  const handleFiles = (files: FileList | null) => {
    if (!files?.length) return
    // One at a time: each upload embeds its chunks, and a serial queue keeps the
    // error message attached to the file that caused it.
    for (const file of Array.from(files)) upload.mutate(file)
  }

  return (
    <Tabs defaultValue="upload" className="space-y-4">
      <TabsList>
        <TabsTrigger value="upload">Upload</TabsTrigger>
        <TabsTrigger value="documents">
          Documents{documents.data?.length ? ` (${documents.data.length})` : ''}
        </TabsTrigger>
      </TabsList>

      <TabsContent value="upload">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Add to the knowledge base</CardTitle>
            <CardDescription>
              Documents the agent can draw on. Text is extracted, split and embedded so it can be
              retrieved by meaning rather than keyword.
            </CardDescription>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          <fieldset className="space-y-2">
            <legend className="text-muted-foreground mb-1.5 text-xs font-medium">
              How should the agent treat what is in this file?
            </legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {TRUST_OPTIONS.map((option) => (
                <label
                  key={option.value}
                  className={cn(
                    'cursor-pointer rounded-lg border p-3 text-xs transition-colors',
                    trust === option.value
                      ? 'border-ring bg-accent'
                      : 'border-border hover:border-muted-foreground/40',
                  )}
                >
                  <input
                    type="radio"
                    name="trust"
                    value={option.value}
                    checked={trust === option.value}
                    onChange={(e) => setTrust(e.target.value)}
                    className="sr-only"
                  />
                  <div className="font-medium">{option.label}</div>
                  <div className="text-muted-foreground mt-0.5 leading-relaxed">
                    {option.detail}
                  </div>
                </label>
              ))}
            </div>
          </fieldset>

          <div
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              handleFiles(e.dataTransfer.files)
            }}
            onClick={() => inputRef.current?.click()}
            data-tour="knowledge-upload"
            className={cn(
              'flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed px-6 py-10 text-center transition-colors',
              dragging ? 'border-ring bg-accent' : 'border-border hover:border-muted-foreground/40',
            )}
          >
            <input
              ref={inputRef}
              type="file"
              multiple
              accept=".pdf,.txt,.md,.csv,.json"
              className="hidden"
              onChange={(e) => handleFiles(e.target.files)}
            />
            {upload.isPending ? (
              <>
                <Loader2 className="text-muted-foreground size-5 animate-spin" aria-hidden />
                <p className="mt-2 text-sm font-medium">Extracting and embedding…</p>
                <p className="text-muted-foreground mt-0.5 text-xs">
                  A long PDF takes a few seconds.
                </p>
              </>
            ) : (
              <>
                <Upload className="text-muted-foreground size-5" aria-hidden />
                <p className="mt-2 text-sm font-medium">Drop a file, or click to choose</p>
                <p className="text-muted-foreground mt-0.5 text-xs">
                  PDF, TXT, MD, CSV or JSON · up to 10MB
                </p>
              </>
            )}
          </div>

          {error && <p className="text-status-down text-xs">{error}</p>}
          <p className="text-muted-foreground text-[11px]">
            Scanned PDFs will not work — there is no OCR, and a scan contains no extractable
            text.
          </p>
        </CardContent>
      </Card>
      </TabsContent>

      <TabsContent value="documents">
      <Card>
        <CardHeader>
          <CardTitle>Uploaded documents</CardTitle>
        </CardHeader>

        {documents.isPending && (
          <CardContent className="text-muted-foreground text-xs">Loading…</CardContent>
        )}
        {documents.data?.length === 0 && (
          <Empty title="Nothing uploaded yet">
            Company capability statements, past tender submissions and won-deal summaries are the
            most useful things to add — they are what makes relevance scoring specific to you.
          </Empty>
        )}

        <div>
          {documents.data?.map((doc) => (
            <div
              key={doc.document_id}
              className="border-border flex items-center gap-3 border-b px-6 py-3 last:border-b-0"
            >
              <FileText className="text-muted-foreground size-4 shrink-0" aria-hidden />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="min-w-0 truncate text-sm font-medium">{doc.filename}</span>
                  <StatusBadge tone={doc.trust_tag === 'user_asserted' ? 'ok' : 'degraded'}>
                    {humaniseShort(doc.trust_tag)}
                  </StatusBadge>
                </div>
                <p className="text-muted-foreground text-[11px]">
                  {doc.chunk_count} chunk{doc.chunk_count === 1 ? '' : 's'} ·{' '}
                  {doc.characters.toLocaleString()} characters ·{' '}
                  {new Date(doc.uploaded_at).toLocaleDateString()}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => remove.mutate(doc.document_id)}
                disabled={remove.isPending}
                aria-label={`Delete ${doc.filename}`}
              >
                <Trash2 className="size-3.5" aria-hidden />
              </Button>
            </div>
          ))}
        </div>
      </Card>
      </TabsContent>
    </Tabs>
  )
}
