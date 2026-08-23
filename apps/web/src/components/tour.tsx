import { useCallback, useEffect, useState } from 'react'

import { Button } from '#/components/ui/button'
import { TOUR, markTourSeen } from '#/lib/tour'
import { cn } from '#/lib/utils'

type Box = { top: number; left: number; width: number; height: number }

function boxFor(target?: string): Box | null {
  // Rendered on the server first, where there is no DOM. Without this guard the
  // whole app 500s on every route, because this runs during render.
  if (!target || typeof document === 'undefined') return null
  const el = document.querySelector<HTMLElement>(`[data-tour="${target}"]`)
  if (!el) return null
  const r = el.getBoundingClientRect()
  if (r.width === 0 && r.height === 0) return null
  return { top: r.top, left: r.left, width: r.width, height: r.height }
}

export function Tour() {
  const [active, setActive] = useState(false)
  const [index, setIndex] = useState(0)
  const [box, setBox] = useState<Box | null>(null)

  useEffect(() => {
    const open = () => {
      setIndex(0)
      setActive(true)
    }
    window.addEventListener('batanat:tour', open)
    return () => window.removeEventListener('batanat:tour', open)
  }, [])

  // Steps whose target is not on this screen are skipped rather than shown
  // pointing at nothing.
  const steps = active ? TOUR.filter((s) => !s.target || boxFor(s.target) !== null) : TOUR
  const step = steps[index]

  const reposition = useCallback(() => {
    if (!step) return
    setBox(boxFor(step.target))
    const el = step.target
      ? document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`)
      : null
    el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [step])

  useEffect(() => {
    if (!active) return
    reposition()
    window.addEventListener('resize', reposition)
    window.addEventListener('scroll', reposition, true)
    return () => {
      window.removeEventListener('resize', reposition)
      window.removeEventListener('scroll', reposition, true)
    }
  }, [active, reposition])

  const close = useCallback(() => {
    setActive(false)
    markTourSeen()
  }, [])

  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
      if (e.key === 'ArrowRight') setIndex((i) => Math.min(i + 1, steps.length - 1))
      if (e.key === 'ArrowLeft') setIndex((i) => Math.max(i - 1, 0))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, close, steps.length])

  if (!active || !step) return null

  const last = index === steps.length - 1
  const pad = 6

  // Place the card below the highlight, or above it when that would run off
  // the bottom of the viewport.
  const cardWidth = 320
  const below = box ? box.top + box.height + 12 : 0
  const placeAbove = box ? below + 190 > window.innerHeight : false
  const cardTop = box ? (placeAbove ? box.top - 190 : below) : window.innerHeight / 2 - 95
  const cardLeft = box
    ? Math.min(Math.max(box.left, 12), window.innerWidth - cardWidth - 12)
    : window.innerWidth / 2 - cardWidth / 2

  return (
    <div className="fixed inset-0 z-[60]" role="dialog" aria-modal="true" aria-label="Product tour">
      {/* Dim everything, then cut a hole over the target with a huge shadow. */}
      <div className="absolute inset-0 bg-black/50" onClick={close} />
      {box && (
        <div
          className="ring-primary pointer-events-none absolute rounded-sm ring-2"
          style={{
            top: box.top - pad,
            left: box.left - pad,
            width: box.width + pad * 2,
            height: box.height + pad * 2,
            boxShadow: '0 0 0 9999px rgba(0,0,0,0.5)',
          }}
        />
      )}

      <div
        className="bg-popover text-popover-foreground absolute rounded-sm border p-4 shadow-lg"
        style={{ top: Math.max(12, cardTop), left: cardLeft, width: cardWidth }}
      >
        <div className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">
          Step {index + 1} of {steps.length}
        </div>
        <h3 className="mt-1 text-sm font-semibold">{step.title}</h3>
        <p className="text-muted-foreground mt-1.5 text-xs leading-relaxed">{step.body}</p>

        <div className="mt-4 flex items-center gap-2">
          <div className="flex gap-1">
            {steps.map((_, i) => (
              <span
                key={i}
                className={cn(
                  'size-1.5 rounded-full transition-colors',
                  i === index ? 'bg-primary' : 'bg-muted-foreground/30',
                )}
              />
            ))}
          </div>
          <div className="ml-auto flex gap-2">
            <Button variant="ghost" size="sm" onClick={close}>
              {last ? 'Done' : 'Skip'}
            </Button>
            {!last && (
              <Button size="sm" onClick={() => setIndex((i) => i + 1)}>
                Next
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
