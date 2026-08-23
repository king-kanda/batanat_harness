import { useMutation } from '@tanstack/react-query'
import { createFileRoute, useNavigate, useRouter } from '@tanstack/react-router'
import { Loader2, TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import { Button } from '#/components/ui/button'
import { Card, CardContent } from '#/components/ui/card'
import { Input } from '#/components/ui/input'
import { Label } from '#/components/ui/label'
import { api } from '#/lib/api'

export const Route = createFileRoute('/login')({ component: Login })

function Login() {
  const navigate = useNavigate()
  const router = useRouter()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  const signIn = useMutation({
    mutationFn: () => api.auth.login(email, password),
    onSuccess: async () => {
      setError(null)
      // Re-run the root loader so the guard sees the new session before we land.
      await router.invalidate()
      navigate({ to: '/' })
    },
    onError: (e: Error) => setError(e.message),
  })

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    if (!email || !password || signIn.isPending) return
    signIn.mutate()
  }

  return (
    <div className="flex min-h-svh items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <span className="bg-ink flex size-11 items-center justify-center rounded-2xl">
            <span className="bg-lime-accent size-4 rounded-[6px]" />
          </span>
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight">
              Batanat <span className="text-italic-serif font-normal">Harness</span>
            </h1>
            <p className="text-muted-foreground mt-1 text-sm">Sign in to continue.</p>
          </div>
        </div>

        <Card>
          <CardContent className="pt-6">
            <form onSubmit={submit} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="username"
                  autoFocus
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@batanat.co.ke"
                  required
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>

              {error && (
                <p className="text-status-down flex items-start gap-1.5 text-xs">
                  <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  {error}
                </p>
              )}

              <Button type="submit" className="w-full" disabled={signIn.isPending}>
                {signIn.isPending && <Loader2 className="size-4 animate-spin" aria-hidden />}
                Sign in
              </Button>
            </form>
          </CardContent>
        </Card>

        {import.meta.env.DEV && (
          <div className="border-border bg-card text-muted-foreground mt-4 rounded-lg border p-3 text-xs">
            <p className="text-foreground font-medium">Development sign-in</p>
            <p className="mt-1 font-mono text-[11px]">
              martin@batanat.co.ke / batanat-dev
            </p>
            <p className="mt-1.5 leading-relaxed">
              Seeded by <span className="font-mono">make seed</span>. The API refuses to start
              with this password when <span className="font-mono">APP_ENV</span> is not{' '}
              <span className="font-mono">local</span>.
            </p>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className="mt-2 w-full"
              onClick={() => {
                setEmail('martin@batanat.co.ke')
                setPassword('batanat-dev')
              }}
            >
              Fill them in
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
