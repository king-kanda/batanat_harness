import { Link, createFileRoute } from '@tanstack/react-router'
import { ArrowRight, Check, Circle } from 'lucide-react'

import { DemoData } from '#/components/demo-data'
import { Button } from '#/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { useOnboarding } from '#/lib/onboarding'
import { startTour } from '#/lib/tour'
import { cn } from '#/lib/utils'

export const Route = createFileRoute('/onboarding')({ component: Onboarding })

function Onboarding() {
  const { steps, done, total, complete, loading } = useOnboarding()

  return (
    <div className="mx-auto w-full max-w-2xl space-y-5">
      <div className="text-center">
        <h2 className="text-3xl font-extrabold tracking-tight text-balance">
          Let's get this <span className="text-italic-serif font-normal">working for you</span>
        </h2>
        <p className="text-muted-foreground mt-2 text-sm">
          Five things. None of them take long, and the first one matters most.
        </p>
      </div>

      <div className="flex items-center gap-3">
        <div className="bg-muted h-1.5 flex-1 overflow-hidden rounded-full">
          <div
            className="bg-primary h-full transition-all duration-500"
            style={{ width: `${(done / total) * 100}%` }}
          />
        </div>
        <span className="text-muted-foreground tabular text-xs">
          {loading ? '…' : `${done} of ${total}`}
        </span>
      </div>

      {complete && !loading && (
        <Card className="border-status-ok/30 bg-status-ok/5">
          <CardContent className="flex items-center gap-3 py-4 text-sm">
            <Check className="text-status-ok size-4 shrink-0" aria-hidden />
            <span>
              That's everything. The assistant has what it needs — head to{' '}
              <Link to="/" className="underline">
                chat
              </Link>{' '}
              and ask it something.
            </span>
          </CardContent>
        </Card>
      )}

      <div className="space-y-2">
        {steps.map((step, index) => (
          <Card key={step.id} className={cn('py-0', step.done && 'opacity-70')}>
            <CardContent className="flex items-start gap-3 p-4">
              <span
                className={cn(
                  'mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold',
                  step.done
                    ? 'bg-status-ok/15 text-status-ok'
                    : 'bg-muted text-muted-foreground',
                )}
              >
                {step.done ? <Check className="size-3" aria-hidden /> : index + 1}
              </span>

              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{step.title}</div>
                <p className="text-muted-foreground mt-0.5 text-xs leading-relaxed">
                  {step.blurb}
                </p>
              </div>

              <Link to={step.to as never} className="shrink-0">
                <Button variant={step.done ? 'outline' : 'default'} size="sm">
                  {step.done ? 'Review' : 'Start'}
                  <ArrowRight className="size-3.5" aria-hidden />
                </Button>
              </Link>
            </CardContent>
          </Card>
        ))}
      </div>

      <DemoData />

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Not sure what any of this does?</CardTitle>
            <CardDescription>
              A two-minute walk through the screens and what each one is for.
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={() => startTour()}>
            <Circle className="size-3.5" aria-hidden />
            Take the tour
          </Button>
        </CardHeader>
      </Card>
    </div>
  )
}
