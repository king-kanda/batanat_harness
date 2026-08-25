import { useMutation } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate, useRouter } from '@tanstack/react-router'
import { Loader2, TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import { Button } from '#/components/ui/button'
import { Card, CardContent } from '#/components/ui/card'
import { Input } from '#/components/ui/input'
import { Label } from '#/components/ui/label'
import { api } from '#/lib/api'

export const Route = createFileRoute('/register')({ component: Register })

/** Mirrors `MIN_PASSWORD_LENGTH` in the API. Checked there too — this is only
 * so the mismatch is caught before a round trip. */
const MIN_PASSWORD_LENGTH = 8

function Register() {
  const navigate = useNavigate()
  const router = useRouter()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  const createAccount = useMutation({
    mutationFn: () => api.auth.register(email, password, confirmPassword),
    onSuccess: async () => {
      setError(null)
      // Registration signs you in, so the guard has to re-read the session
      // before we navigate or it bounces straight back to /login.
      await router.invalidate()
      navigate({ to: '/' })
    },
    onError: (e: Error) => setError(e.message),
  })

  // Only once they have typed something, so the form does not open shouting.
  const mismatch = confirmPassword.length > 0 && password !== confirmPassword
  const tooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    if (!email || !password || !confirmPassword) return
    if (mismatch || tooShort || createAccount.isPending) return
    createAccount.mutate()
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
            <p className="text-muted-foreground mt-1 text-sm">Create an account.</p>
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
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                {tooShort && (
                  <p className="text-muted-foreground text-xs">
                    At least {MIN_PASSWORD_LENGTH} characters.
                  </p>
                )}
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="confirm-password">Confirm password</Label>
                <Input
                  id="confirm-password"
                  type="password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  aria-invalid={mismatch}
                  required
                />
                {mismatch && (
                  <p className="text-status-down text-xs">The two passwords do not match.</p>
                )}
              </div>

              {error && (
                <p className="text-status-down flex items-start gap-1.5 text-xs">
                  <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                  {error}
                </p>
              )}

              <Button
                type="submit"
                className="w-full"
                disabled={createAccount.isPending || mismatch || tooShort}
              >
                {createAccount.isPending && <Loader2 className="size-4 animate-spin" aria-hidden />}
                Create account
              </Button>
            </form>
          </CardContent>
        </Card>

        <p className="text-muted-foreground mt-4 text-center text-sm">
          Already have an account?{' '}
          <Link to="/login" className="text-foreground font-medium underline underline-offset-4">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
