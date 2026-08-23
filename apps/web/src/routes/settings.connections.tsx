import type { PairingCodeView } from '@batanat/schema'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, useSearch } from '@tanstack/react-router'
import { Check, Copy, Loader2, Smartphone, TriangleAlert, X } from 'lucide-react'
import { useState } from 'react'

import { ConnectionCard, PROVIDER_LABEL } from '#/components/connection-card'
import { StatusBadge } from '#/components/status-badge'
import { Button } from '#/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '#/components/ui/tabs'
import { api } from '#/lib/api'

type Search = { connected?: string; error?: string }

export const Route = createFileRoute('/settings/connections')({
  component: ConnectionsPage,
  validateSearch: (search: Record<string, unknown>): Search => ({
    connected: typeof search.connected === 'string' ? search.connected : undefined,
    error: typeof search.error === 'string' ? search.error : undefined,
  }),
})

const OAUTH_PROVIDERS = ['gmail', 'zoho'] as const

function ConnectionsPage() {
  const search = useSearch({ from: '/settings/connections' })
  const queryClient = useQueryClient()
  const [pairing, setPairing] = useState<PairingCodeView | null>(null)
  const [phoneInput, setPhoneInput] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)

  const page = useQuery({ queryKey: ['connections'], queryFn: api.connections.list })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['connections'] })
  const onError = (error: Error) => setActionError(error.message)

  // The browser must navigate to the provider, so the mutation returns a URL
  // rather than performing the redirect itself.
  const connect = useMutation({
    mutationFn: api.connections.authorize,
    onSuccess: ({ authorization_url }) => {
      window.location.href = authorization_url
    },
    onError,
  })

  const disconnect = useMutation({
    mutationFn: api.connections.disconnect,
    onSuccess: invalidate,
    onError,
  })

  const requestCode = useMutation({
    mutationFn: (phone: string) => api.connections.pairingCode(phone),
    onSuccess: (code) => {
      setPairing(code)
      setActionError(null)
    },
    onError,
  })

  const unlink = useMutation({
    mutationFn: api.connections.unlinkNumber,
    onSuccess: invalidate,
    onError,
  })

  const busy = connect.isPending || disconnect.isPending
  const data = page.data

  return (
    <div className="space-y-4">
      {search.connected && (
        <Banner tone="ok">
          {PROVIDER_LABEL[search.connected as keyof typeof PROVIDER_LABEL] ?? search.connected}{' '}
          connected.
        </Banner>
      )}
      {(search.error || actionError) && (
        <Banner tone="down">{actionError ?? search.error}</Banner>
      )}

      <Tabs defaultValue="providers" className="space-y-4">
      <TabsList data-tour="connections-panel">
        <TabsTrigger value="providers">Gmail &amp; Zoho</TabsTrigger>
        <TabsTrigger value="whatsapp">
          WhatsApp{data?.whatsapp_links.length ? ` (${data.whatsapp_links.length})` : ''}
        </TabsTrigger>
      </TabsList>

      <TabsContent value="providers">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Connections</CardTitle>
            <CardDescription>
              Accounts the agent may read. Nothing is written without your approval.
            </CardDescription>
          </div>
          {page.isFetching && (
            <Loader2 className="text-muted-foreground/80 size-3.5 animate-spin" aria-label="loading" />
          )}
        </CardHeader>

        {page.isPending && (
          <CardContent className="text-muted-foreground/80 text-xs">Loading connections…</CardContent>
        )}

        {page.isError && (
          <CardContent className="text-status-down text-xs">{page.error.message}</CardContent>
        )}

        {data && (
          <div>
            {OAUTH_PROVIDERS.map((provider) => (
              <ConnectionCard
                key={provider}
                provider={provider}
                status={data.providers.find((p) => p.provider === provider)}
                connection={data.connections.find((c) => c.provider === provider)}
                onConnect={() => connect.mutate(provider)}
                onDisconnect={() => {
                  const match = data.connections.find((c) => c.provider === provider)
                  if (match) disconnect.mutate(match.id)
                }}
                busy={busy}
              />
            ))}
          </div>
        )}
      </Card>
      </TabsContent>

      <TabsContent value="whatsapp">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>WhatsApp</CardTitle>
            <CardDescription>
              One shared business number. Linking proves you hold the handset.
            </CardDescription>
          </div>
          {data?.providers.find((p) => p.provider === 'whatsapp')?.configured ? (
            <StatusBadge tone="ok">configured</StatusBadge>
          ) : (
            <StatusBadge tone="degraded">not configured</StatusBadge>
          )}
        </CardHeader>

        {data && data.whatsapp_links.length > 0 && (
          <div>
            {data.whatsapp_links.map((link) => (
              <div
                key={link.id}
                className="border-border flex items-center justify-between border-b px-4 py-2.5 last:border-b-0"
              >
                <div className="flex items-center gap-2.5">
                  <Smartphone className="text-muted-foreground/80 size-3.5" aria-hidden />
                  <span className="text-foreground font-mono text-xs">{link.phone_e164}</span>
                  <span className="text-muted-foreground/80 text-[11px]">
                    linked {new Date(link.linked_at).toLocaleDateString()}
                  </span>
                </div>
                <Button variant="destructive" onClick={() => unlink.mutate(link.id)}>
                  <X className="size-3" aria-hidden />
                  Unlink
                </Button>
              </div>
            ))}
          </div>
        )}

        <CardContent className="space-y-3">
          {pairing ? (
            <PairingInstructions pairing={pairing} onDismiss={() => setPairing(null)} />
          ) : data?.whatsapp_business_number ? (
            <div className="space-y-2">
              <p className="text-muted-foreground text-xs">
                Enter the number you want to link. We will give you a code to text to{' '}
                <span className="text-foreground font-mono">{data.whatsapp_business_number}</span> from
                that handset.
              </p>
              <div className="flex gap-2">
                <input
                  value={phoneInput}
                  onChange={(e) => setPhoneInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && requestCode.mutate(phoneInput)}
                  placeholder="0712 345 678"
                  inputMode="tel"
                  className="bg-muted border-border text-foreground focus:border-ring w-48 rounded-lg border px-3 py-2 font-mono text-xs outline-none"
                />
                <Button
                  variant="default"
                  onClick={() => requestCode.mutate(phoneInput)}
                  disabled={requestCode.isPending || phoneInput.trim().length < 7}
                >
                  {requestCode.isPending && <Loader2 className="size-3 animate-spin" aria-hidden />}
                  Pair this number
                </Button>
              </div>
              <p className="text-muted-foreground/80 text-[11px]">
                The code only works from the number you enter here.
              </p>
            </div>
          ) : (
            <p className="text-muted-foreground text-xs">
              Set <span className="font-mono">WHATSAPP_BUSINESS_NUMBER</span> in{' '}
              <span className="font-mono">.env</span> to enable pairing.
            </p>
          )}
        </CardContent>
      </Card>
      </TabsContent>
      </Tabs>
    </div>
  )
}

function PairingInstructions({
  pairing,
  onDismiss,
}: {
  pairing: PairingCodeView
  onDismiss: () => void
}) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    await navigator.clipboard.writeText(pairing.message)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const minutesLeft = Math.max(
    0,
    Math.round((new Date(pairing.expires_at).getTime() - Date.now()) / 60000),
  )

  return (
    <div className="space-y-3">
      <div className="min-w-0 flex-1 space-y-2">
        <ol className="text-muted-foreground list-inside list-decimal space-y-1 text-xs">
          <li>
            From <span className="text-foreground font-mono">{pairing.phone_e164}</span>, open WhatsApp
            and message <span className="text-foreground font-mono">{pairing.business_number}</span>.
          </li>
          <li>
            Send exactly: <span className="text-foreground font-mono">{pairing.message}</span>
          </li>
        </ol>

        <div className="flex flex-wrap items-center gap-2">
          <code className="bg-muted border-border text-foreground rounded-lg border px-2.5 py-1 font-mono text-base tracking-[0.2em]">
            {pairing.code}
          </code>
          <Button onClick={copy}>
            {copied ? <Check className="size-3" aria-hidden /> : <Copy className="size-3" aria-hidden />}
            {copied ? 'Copied' : 'Copy message'}
          </Button>
          <a href={pairing.wa_me_url} target="_blank" rel="noreferrer">
            <Button variant="default">Open in WhatsApp</Button>
          </a>
          <Button variant="ghost" onClick={onDismiss}>
            Done
          </Button>
        </div>

        <p className="text-muted-foreground/80 text-[11px]">
          Expires in {minutesLeft} min. Single use, and only from{' '}
          <span className="font-mono">{pairing.phone_e164}</span>.
        </p>
      </div>
    </div>
  )
}

function Banner({ tone, children }: { tone: 'ok' | 'down'; children: React.ReactNode }) {
  const isError = tone === 'down'
  return (
    <div
      className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-xs ${
        isError
          ? 'border-status-down/30 bg-status-down/10 text-status-down'
          : 'border-status-ok/30 bg-status-ok/10 text-status-ok'
      }`}
    >
      {isError ? (
        <TriangleAlert className="size-3.5 shrink-0 translate-y-px" aria-hidden />
      ) : (
        <Check className="size-3.5 shrink-0 translate-y-px" aria-hidden />
      )}
      <span>{children}</span>
    </div>
  )
}
