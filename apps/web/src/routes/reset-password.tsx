import { useMutation } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { Eye, EyeOff, Loader2, TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import { Button } from '#/components/ui/button'
import { Card, CardContent } from '#/components/ui/card'
import { Input } from '#/components/ui/input'
import { Label } from '#/components/ui/label'
import { api } from '#/lib/api'

export const Route = createFileRoute('/reset-password')({
  validateSearch: (search: Record<string, unknown>) => ({
    token: typeof search.token === 'string' ? search.token : '',
  }),
  component: ResetPassword,
})

function ResetPassword() {
  const { token } = Route.useSearch()
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const mismatch = confirmPassword.length > 0 && password !== confirmPassword

  const reset = useMutation({
    mutationFn: () => api.auth.resetPassword(token, password, confirmPassword),
    onSuccess: () => {
      setError(null)
      setDone(true)
      setTimeout(() => navigate({ to: '/login' }), 1200)
    },
    onError: (e: Error) => setError(e.message),
  })

  return (
    <div className="flex min-h-svh items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <h1 className="mb-8 text-center text-2xl font-extrabold tracking-tight">Choose a new password</h1>
        <Card>
          <CardContent className="pt-6">
            {done ? (
              <p className="text-sm">Password reset. Taking you to sign in...</p>
            ) : (
              <form
                onSubmit={(event) => {
                  event.preventDefault()
                  if (token && password.length >= 8 && !mismatch && !reset.isPending) reset.mutate()
                }}
                className="space-y-4"
              >
                {(['password', 'confirm-password'] as const).map((field) => {
                  const isConfirm = field === 'confirm-password'
                  const visible = isConfirm ? showConfirmPassword : showPassword
                  return (
                    <div className="space-y-1.5" key={field}>
                      <Label htmlFor={field}>{isConfirm ? 'Confirm password' : 'New password'}</Label>
                      <div className="relative">
                        <Input
                          id={field}
                          type={visible ? 'text' : 'password'}
                          autoComplete="new-password"
                          value={isConfirm ? confirmPassword : password}
                          onChange={(event) =>
                            isConfirm
                              ? setConfirmPassword(event.target.value)
                              : setPassword(event.target.value)
                          }
                          className="pr-10"
                          required
                        />
                        <button
                          type="button"
                          className="text-muted-foreground hover:text-foreground absolute inset-y-0 right-0 flex w-10 items-center justify-center"
                          onClick={() =>
                            isConfirm
                              ? setShowConfirmPassword((value) => !value)
                              : setShowPassword((value) => !value)
                          }
                          aria-label={visible ? 'Hide password' : 'Show password'}
                          title={visible ? 'Hide password' : 'Show password'}
                        >
                          {visible ? <EyeOff aria-hidden /> : <Eye aria-hidden />}
                        </button>
                      </div>
                    </div>
                  )
                })}
                {mismatch && <p className="text-status-down text-xs">The two passwords do not match.</p>}
                {error && (
                  <p className="text-status-down flex items-start gap-1.5 text-xs">
                    <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                    {error}
                  </p>
                )}
                <Button type="submit" className="w-full" disabled={reset.isPending || mismatch}>
                  {reset.isPending && <Loader2 className="size-4 animate-spin" aria-hidden />}
                  Reset password
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