import { useMutation } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import { Loader2, TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import { Button } from '#/components/ui/button'
import { Card, CardContent } from '#/components/ui/card'
import { Input } from '#/components/ui/input'
import { Label } from '#/components/ui/label'
import { api } from '#/lib/api'

export const Route = createFileRoute('/forgot-password')({ component: ForgotPassword })

function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState(false)

  const requestReset = useMutation({
    mutationFn: () => api.auth.forgotPassword(email),
    onSuccess: () => {
      setError(null)
      setSent(true)
    },
    onError: (e: Error) => setError(e.message),
  })

  return (
    <div className="flex min-h-svh items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-extrabold tracking-tight">Reset your password</h1>
          <p className="text-muted-foreground mt-2 text-sm">
            Enter your email and we will send a reset link.
          </p>
        </div>
        <Card>
          <CardContent className="pt-6">
            {sent ? (
              <p className="text-sm leading-relaxed">
                If an account exists for that email, a reset link has been sent. Check your inbox
                and spam folder.
              </p>
            ) : (
              <form
                onSubmit={(event) => {
                  event.preventDefault()
                  if (email && !requestReset.isPending) requestReset.mutate()
                }}
                className="space-y-4"
              >
                <div className="space-y-1.5">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    autoComplete="email"
                    autoFocus
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    required
                  />
                </div>
                {error && (
                  <p className="text-status-down flex items-start gap-1.5 text-xs">
                    <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                    {error}
                  </p>
                )}
                <Button type="submit" className="w-full" disabled={requestReset.isPending}>
                  {requestReset.isPending && <Loader2 className="size-4 animate-spin" aria-hidden />}
                  Send reset link
                </Button>
              </form>
            )}
          </CardContent>
        </Card>
        <p className="text-muted-foreground mt-4 text-center text-sm">
          <Link to="/login" className="text-foreground font-medium underline underline-offset-4">
            Back to sign in
          </Link>
        </p>
      </div>
    </div>
  )
}