import { useNavigate, useRouterState } from '@tanstack/react-router'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import { Button } from '#/components/ui/button'
import { TOUR, markTourSeen } from '#/lib/tour'
import type { AppRoute } from '#/lib/tour'
import { cn } from '#/lib/utils'

type Box = { top: number; left: number; width: number; height: number }

/** How often to re-measure the highlighted element while a step is on screen. */
const MEASURE_MS = 150

function sameBox(a: Box | null, b: Box | null): boolean {
  if (a === b) return true
  if (!a || !b) return false
  return a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height
}

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

  const navigate = useNavigate()
  const pathname = useRouterState({ select: (s) => s.location.pathname })

  // Where the user was when they started, so the tour puts them back.
  const origin = useRef<string | null>(null)
  // Last step we scrolled into view, so re-running the tour scrolls again.
  const scrolled = useRef<number | null>(null)

  const step = TOUR[index]
  const onRoute = !step?.route || pathname === step.route

  useEffect(() => {
    const open = () => {
      origin.current = window.location.pathname
      scrolled.current = null
      setIndex(0)
      setActive(true)
    }
    window.addEventListener('batanat:tour', open)
    return () => window.removeEventListener('batanat:tour', open)
  }, [])

  // Drive the router. The tour walks the app rather than pointing at menu
  // entries from wherever the user happened to be standing.
  useEffect(() => {
    const route = step?.route
    if (!active || !route || pathname === route) return
    navigate({ to: route })
  }, [active, step, pathname, navigate])

  const measure = useCallback(() => {
    const next = onRoute ? boxFor(step?.target) : null
    setBox((prev) => (sameBox(prev, next) ? prev : next))
  }, [onRoute, step])

  // Measure before paint when the step or the route changes, so arriving
  // somewhere highlights the target in the same frame rather than a tick later.
  // Deliberately not on every render: the interval below already re-measures,
  // and an unconditional layout effect would re-measure once more for each of
  // those, every 150ms, for as long as the tour is open.
  useLayoutEffect(() => {
    if (active) measure()
  }, [active, measure])

  // Then keep measuring for as long as the step is on screen. The page a step
  // lives on arrives asynchronously and its contents usually arrive later still
  // — /settings/sources renders its card about a second after the route
  // resolves, and nothing re-renders this component when it does — so a single
  // measurement, or a poll that gives up, races the thing it is pointing at.
  // This also keeps the highlight true when the page reflows underneath it.
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(measure, MEASURE_MS)
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
  }, [active, measure])

  // Bring the target into view once per step, not on every measurement — a
  // repeated smooth scroll would fight the user trying to look around.
  useEffect(() => {
    if (!active || !box || scrolled.current === index) return
    scrolled.current = index
    document
      .querySelector<HTMLElement>(`[data-tour="${step.target}"]`)
      ?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [active, box, index, step])

  const close = useCallback(() => {
    setActive(false)
    markTourSeen()
    // A path observed at runtime, so it cannot be typed the way step routes
    // are. If it is not a real route the router lands on the not-found route,
    // which is the same as any hand-typed URL.
    if (origin.current && origin.current !== window.location.pathname) {
      navigate({ to: origin.current as AppRoute })
    }
  }, [navigate])

  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
      if (e.key === 'ArrowRight') setIndex((i) => Math.min(i + 1, TOUR.length - 1))
      if (e.key === 'ArrowLeft') setIndex((i) => Math.max(i - 1, 0))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, close])

  if (!active || !step) return null

  const last = index === TOUR.length - 1
  const pad = 6

  // Place the card below the highlight, or above it when that would run off
  // the bottom of the viewport.
  const cardWidth = 320
  const cardHeight = 210
  const below = box ? box.top + box.height + 12 : 0
  const placeAbove = box ? below + cardHeight > window.innerHeight : false
  const cardTop = box
    ? placeAbove
      ? box.top - cardHeight
      : below
    : window.innerHeight / 2 - cardHeight / 2
  const cardLeft = box
    ? Math.min(Math.max(box.left, 12), window.innerWidth - cardWidth - 12)
    : window.innerWidth / 2 - cardWidth / 2

  return (
    <div className="fixed inset-0 z-[60]" role="dialog" aria-modal="true" aria-label="Product tour">
      {/* Dim everything, then cut a hole over the target with a huge shadow. */}
      <div className="absolute inset-0 bg-black/50" onClick={close} />
      {box && (
        <div
          className="ring-primary pointer-events-none absolute rounded-xl ring-2"
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
        className="bg-popover text-popover-foreground absolute rounded-xl border p-4 shadow-lg"
        style={{ top: Math.max(12, cardTop), left: cardLeft, width: cardWidth }}
      >
        <div className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">
          Step {index + 1} of {TOUR.length}
        </div>
        <h3 className="mt-1 text-sm font-semibold">{step.title}</h3>
        <p className="text-muted-foreground mt-1.5 text-xs leading-relaxed">{step.body}</p>

        <div className="mt-4 flex items-center gap-2">
          <div className="flex gap-1">
            {TOUR.map((_, i) => (
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
            {index > 0 && (
              <Button variant="ghost" size="sm" onClick={() => setIndex((i) => i - 1)}>
                Back
              </Button>
            )}
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
