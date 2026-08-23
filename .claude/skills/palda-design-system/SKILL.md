---
name: palda-design-system
description: The Palda UI/UX design system — colours, typography, icons, spacing, component recipes and voice. Use this when building any Palda interface (the marketing site or the main app) so it looks and feels like one product. Stack-agnostic tokens with copy-paste Tailwind v4 recipes.
---

# Palda Design System

Palda is a premium software suite for businesses in Kenya / East Africa. The look is
**light, calm and confident**: soft off-white surfaces, floating rounded cards, one
sharp lime-green accent, near-black "ink" text, and an italic serif used to emphasise
a few words inside otherwise sans-serif headlines.

> One-line brief: *airy off-white background, dark rounded icon chips with a lime glyph,
> pill buttons, floating cards with soft shadows, lime used as pops of highlight — never
> a full background flood.*

This document is self-contained: every token and component it describes is reproduced in
full in the **Appendix** at the end, so you can rebuild the system without the original
repo. The sections below are the practical summary; the appendix is the exact source.

---

## 1. Brand tokens (copy-paste)

Colours are defined in **oklch** (keep this format — the codebase requires it). Hex
values are *approximate*, for tools that can't take oklch.

### Core palette

| Token | oklch | ~hex | Role |
|---|---|---|---|
| `--lime` (lime-accent) | `oklch(0.92 0.2 122)` | `#C4F542` | The one accent. CTAs, badges, icon glyphs, highlight dots, focus ring. |
| `--lime-soft` | `oklch(0.95 0.09 122)` | `#E3F5B4` | Filled badges (`GreenBadge`) background. |
| `--lime-mist` | `oklch(0.975 0.045 124)` | `#F0FBDD` | Tinted panels, hover fills, hero glow, callout cards. |
| `--ink` | `oklch(0.21 0.008 145)` | `#1F241E` | Icon chips, logo mark, button text on lime, `::selection`. |
| `--background` | `oklch(0.982 0.004 106)` | `#FAFAF7` | Page background (warm off-white). |
| `--foreground` | `oklch(0.21 0.008 145)` | `#1F241E` | Primary text. |
| `--card` | `oklch(1 0 0)` | `#FFFFFF` | Card / surface. |
| `--muted-foreground` | `oklch(0.53 0.012 145)` | `#6E756B` | Secondary / body text. |
| `--secondary` | `oklch(0.96 0.005 106)` | `#F3F3F0` | Subtle chip / tile fills. |
| `--border` | `oklch(0.918 0.006 106)` | `#E7E7E2` | Hairline borders (used on almost every surface). |
| `--destructive` | `oklch(0.577 0.245 27.325)` | `#D84A3B` | Errors only. |

Semantic aliases (shadcn-style) also exist: `primary` = lime, `accent` = lime-mist,
`ring` = lime, `input`/`popover`/etc. The complete token file — light + dark, all
semantic and chart/sidebar tokens, and the custom utilities — is in **Appendix A**.

### Drop-in Tailwind v4 theme

```css
@theme {
  --font-sans: "Plus Jakarta Sans", ui-sans-serif, system-ui, -apple-system, sans-serif;
  --font-display: "Instrument Serif", Georgia, serif;
  --color-lime-accent: var(--lime);
  --color-lime-soft: var(--lime-soft);
  --color-lime-mist: var(--lime-mist);
  --color-ink: var(--ink);
  --shadow-float: 0 1px 2px rgb(20 22 20 / 0.04), 0 12px 32px -12px rgb(20 22 20 / 0.14);
  --shadow-lift: 0 2px 6px rgb(20 22 20 / 0.05), 0 28px 56px -20px rgb(20 22 20 / 0.2);
}

:root {
  --radius: 1rem;              /* 16px base */
  --lime: oklch(0.92 0.2 122);
  --lime-soft: oklch(0.95 0.09 122);
  --lime-mist: oklch(0.975 0.045 124);
  --ink: oklch(0.21 0.008 145);
  --background: oklch(0.982 0.004 106);
  --foreground: oklch(0.21 0.008 145);
  --card: oklch(1 0 0);
  --muted-foreground: oklch(0.53 0.012 145);
  --secondary: oklch(0.96 0.005 106);
  --border: oklch(0.918 0.006 106);
}
```

> **Dark mode:** the `.dark` block currently holds default shadcn slate/blue tokens — it
> is **not** brand-tuned. The product is designed and shipped in light mode. If the main
> app needs dark mode, re-derive it from ink + lime first; don't ship the default blues.

---

## 2. Typography

Two families, loaded from Google Fonts:

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link rel="stylesheet"
  href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" />
```

- **Plus Jakarta Sans** — everything. Weights 400–800; headings use **800 (extrabold)**.
- **Instrument Serif (italic)** — *accent only*. Used on 1–3 words inside a sans headline
  for emphasis. Never for body or full headings.

**The signature move:** a headline is sans-serif + extrabold + tight tracking, with one
phrase swapped to italic serif at `font-normal`:

```jsx
<h1 className="text-[2.6rem] font-extrabold leading-[1.02] tracking-tight sm:text-6xl lg:text-7xl">
  Your business is bigger{" "}
  <span className="text-italic-serif font-normal">than the tools</span> running it
</h1>
```

`text-italic-serif` utility = `font-family: var(--font-display); font-style: italic;
font-weight: 400; letter-spacing: -0.01em;`

### Type scale (exact classes)

| Use | Classes |
|---|---|
| Hero H1 | `text-[2.6rem] sm:text-6xl lg:text-7xl font-extrabold leading-[1.02] tracking-tight` |
| Section H2 | `text-4xl sm:text-5xl font-extrabold leading-[1.05] tracking-tight` |
| Sub/feature H2 | `text-3xl sm:text-4xl font-extrabold tracking-tight` |
| Card title H3 | `text-lg font-bold tracking-tight` |
| Body | `text-base leading-relaxed text-muted-foreground` |
| Lead/body-lg | `text-base sm:text-lg leading-relaxed text-muted-foreground` |
| Eyebrow / label | `text-xs font-semibold tracking-tight` (or uppercase `tracking-wide`) |
| Fine print | `text-xs text-muted-foreground` |

Headlines are always **tight** (`tracking-tight`, tight leading). Body is always
`leading-relaxed` and `muted-foreground`.

---

## 3. Layout, radius & elevation

- **Page container / section:** `mx-auto w-full max-w-6xl px-5 py-16 sm:py-24`
  (the `Section` primitive). Vertical rhythm comes from section padding; stack sections,
  occasionally `pt-0` to pull two together.
- **Content width:** hero/centred copy caps at `max-w-2xl`/`max-w-3xl`; long-form text at
  `max-w-3xl`.
- **Radius scale** (base `--radius: 1rem`): `rounded-lg` 16 · `rounded-xl` 20 ·
  `rounded-2xl` 24 · `rounded-3xl` 28. Big surfaces use literal `rounded-[32px]`;
  CTA banner `rounded-[36px]`. Buttons/pills/chips = `rounded-full`.
- **Shadows:** `shadow-float` (resting elevation on nearly every card) and `shadow-lift`
  (hover / popover / menus). No hard borders without a shadow; no shadow without a
  hairline `border-border`.
- **Grids:** feature/card rows `grid gap-4 md:grid-cols-3`; two-up `lg:grid-cols-2`.

---

## 4. Iconography

- Library: **lucide-react**, `strokeWidth={2}`.
- Primary treatment is the **IconChip**: a dark ink rounded square containing a lime
  glyph. This is the most recognisable Palda UI atom.

```jsx
// sizes: sm = size-9 rounded-xl · md = size-11 rounded-2xl · lg = size-14 rounded-2xl
<span className="inline-flex shrink-0 items-center justify-center bg-ink size-11 rounded-2xl">
  <Icon className="size-5 text-lime-accent" strokeWidth={2} />
</span>
```

- Inline icons in buttons/links are lucide at `size-4`, often `ArrowUpRight` /
  `ArrowRight` that nudges on hover.
- Highlight dots/squares: a tiny `bg-lime-accent` `rounded-full`/`rounded-[3px]` mark.
- Brand logo mark: ink `rounded-xl` square with a lime `rounded-[5px]` square inside
  (favicon SVG in **Appendix D**; the header/footer use the same mark in markup).

---

## 5. Component recipes

Copy the class strings; they are the shipped primitives.

### Primary button (CTA)
```jsx
<a className="group inline-flex items-center gap-2 rounded-full bg-lime-accent px-5 py-2.5
  text-sm font-semibold text-ink shadow-float transition-all
  hover:-translate-y-0.5 hover:brightness-105">
  Talk to Sales
  <ArrowUpRight className="size-4 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
</a>
```
Large form-submit variant: `px-6 py-3.5 font-bold`.

### Ghost / secondary button
```jsx
<a className="group inline-flex items-center gap-2 rounded-full border border-border bg-card
  px-5 py-2.5 text-sm font-semibold text-foreground transition-all
  hover:-translate-y-0.5 hover:shadow-float">…<ArrowUpRight className="size-4" /></a>
```

### Eyebrow (section kicker)
```jsx
<span className="inline-flex items-center gap-2 rounded-full border border-border bg-card
  px-4 py-1.5 text-xs font-semibold tracking-tight text-muted-foreground">
  <span className="size-1.5 rounded-full bg-lime-accent" /> Integrations
</span>
```

### Pill (tag)
```jsx
<span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card
  px-3.5 py-1.5 text-xs font-semibold tracking-tight text-foreground">…</span>
```

### GreenBadge (status)
```jsx
<span className="inline-flex items-center rounded-full bg-lime-soft px-2.5 py-1
  text-[11px] font-bold uppercase tracking-wide text-ink">New</span>
```

### Card (SoftCard)
```jsx
<div className="rounded-3xl border border-border bg-card p-6 shadow-float
  transition-all duration-300 hover:-translate-y-1.5 hover:shadow-lift">…</div>
```
Callout / tinted card: swap `bg-card` → `bg-lime-mist`, use `rounded-[32px] p-8`.

### CheckPill (list item)
```jsx
<li className="flex items-center gap-3 rounded-full border border-border bg-card px-4 py-2.5 text-sm font-medium">
  <span className="flex size-5 items-center justify-center rounded-full bg-lime-accent">
    <Check className="size-3 text-ink" strokeWidth={3} />
  </span>
  Offline-first tills
</li>
```

### Form field
```jsx
<input className="w-full rounded-2xl border border-border bg-card px-4 py-3 text-sm
  text-foreground outline-none transition-all placeholder:text-muted-foreground/70
  focus:border-lime-accent focus:ring-4 focus:ring-lime-mist" />
```

### Floating nav bar
Sticky, centred, pill-shaped, translucent, blurred:
```jsx
<div className="rounded-full border border-border bg-card/90 px-4 py-2.5 shadow-float backdrop-blur-xl">…</div>
```

### Logo wall / marquee
Uniform tiles `h-24`, image `h-14 max-w-[190px] object-contain`. On marketing surfaces the
homepage marquee greys logos out (`grayscale opacity-60 hover:grayscale-0 hover:opacity-100`);
inside product/reference contexts show them **full colour**. Full component in **Appendix C**.

---

## 6. Motion

- **Scroll reveal** (`Reveal`): fade + 16px rise, `transition-[opacity,transform]
  duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]`, triggered by IntersectionObserver,
  with a small `transitionDelay` stagger (40/80/120/160ms). Respects
  `motion-reduce`. Keep staggers short (≤160ms) so above-the-fold copy appears fast.
- **Hover:** cards/buttons lift `-translate-y-0.5`…`-1.5` and gain `shadow-lift`;
  lime buttons `brightness-105`; arrows nudge. Everything `transition-all duration-300`.
- **Ambient:** `--animate-float-slow` (7s floaty) for hero mockups; `marquee` keyframe for
  logo strips (track duplicated, animates to `-50%`, pause on hover).
- Easing is consistently `cubic-bezier(0.22, 1, 0.36, 1)`.

---

## 7. Texture & depth

- **Dotted grid** behind heroes: `dotted-grid` utility (radial dots, 22px grid, ink @ 13%),
  as an absolutely-positioned `opacity-70` layer.
- **Lime glow:** a blurred `bg-lime-mist` blob behind hero headlines:
  `absolute … rounded-full bg-lime-mist blur-3xl`.
- Layer order: texture (behind) → content. Keep texture subtle; never let lime dominate.

### App-wide background (main app default)

The off-white **dotted canvas is the default background for the whole app**, not just
heroes — it's what ties the app to the site. Apply it once at the root so every screen
sits on it, then keep cards/panels on solid `bg-card` so content stays crisp on top.

The utility (also in Appendix A):
```css
@utility dotted-grid {
  background-image: radial-gradient(oklch(0.21 0.008 145 / 0.13) 1px, transparent 1px);
  background-size: 22px 22px;
}
```

Set it globally on `body` (off-white base + the dots). For app-wide use, soften the dot
alpha a touch (~`0.07`) so it reads as texture under dense UI rather than a pattern:
```css
body {
  background-color: var(--background); /* off-white #FAFAF7 */
  background-image: radial-gradient(oklch(0.21 0.008 145 / 0.07) 1px, transparent 1px);
  background-size: 22px 22px;
  background-attachment: fixed; /* dots stay put while content scrolls */
}
```

Or, in React, a single fixed layer behind the app shell (keeps it out of print / stacking
contexts and easy to toggle):
```jsx
<div aria-hidden className="pointer-events-none fixed inset-0 -z-10 bg-background dotted-grid opacity-60" />
```

Rules for app use:
- **One canvas.** The dotted background lives at the app root; don't repeat it per screen.
- **Content sits on solid surfaces.** Cards, tables, sidebars, modals use `bg-card`
  (white) with `border-border` + `shadow-float` — the dots show only in the gutters.
- **Sidebars / toolbars** can stay solid `bg-card`; the dotted canvas is the main content area.
- Keep it faint. If UI feels busy, drop the dot alpha, not the idea.

---

## 8. Voice & UX principles

Applies to any Palda surface, including in-app empty states, onboarding and marketing.

- **Lead with the customer's pain, then the fix, then the proof.** Name a specific,
  real pain ("You're reconciling M-Pesa by hand at 11pm"), show how Palda removes it in
  plain language, then list the capability as evidence — kept tight.
- **Voice:** confident, calm, direct. Short sentences. Speak to owners/operators, not
  developers. **No hype words** ("revolutionary", "game-changing", "seamless synergy").
- **Local reality:** examples use M-Pesa, WhatsApp, multi-branch retail, landlords/agencies,
  patchy connectivity. Kenya / East Africa first.
- **Consultative, not self-serve:** the primary CTA is **"Talk to Sales"** → `/contact`.
  No public pricing, no signup flows. Pricing is scoped in a conversation.
- **Scannable:** short headings with one italic-serif emphasis; benefits before features.

---

## 9. Quick do / don't

**Do** — off-white **dotted canvas** as the app-wide background · white cards with hairline
border + `shadow-float` on top · lime for one accent per view · ink icon chips · pill
buttons · italic-serif on 1–3 words · tight extrabold headings · relaxed muted body.

**Don't** — flood lime as a background · use gradients or heavy colour · square/hard-edged
cards · borders without shadow (or vice-versa) · italic serif for body or whole headings ·
hype language · self-serve/pricing CTAs · ship the default blue dark theme.

---

# Appendix — full source (self-contained)

Everything needed to reproduce the system, verbatim. Nothing here depends on the original
repo.

**Dependencies:** Tailwind CSS v4, [`tw-animate-css`](https://www.npmjs.com/package/tw-animate-css),
`clsx`, `tailwind-merge`, `lucide-react`, React. Fonts: **Instrument Serif** and
**Plus Jakarta Sans** (Google Fonts). Components are written for TanStack Router
(`import { Link } from "@tanstack/react-router"`) — swap `Link`/`to` for your router's
equivalent (e.g. Next's `next/link` + `href`) when porting.

## Appendix A — `styles.css` (tokens, theme, utilities)

The complete design-token source. Colours are oklch; light values in `:root`, dark in
`.dark`. The `@theme`/`@theme inline` blocks expose them as Tailwind utilities
(`bg-lime-accent`, `shadow-float`, `rounded-3xl`, …).

```css
@import "tailwindcss" source(none);
@source "../src";
@import "tw-animate-css";

@custom-variant dark (&:is(.dark *));

@theme {
  --font-sans:
    "Plus Jakarta Sans", ui-sans-serif, system-ui, -apple-system, sans-serif;
  --font-display: "Instrument Serif", Georgia, serif;
  --color-lime-accent: var(--lime);
  --color-lime-soft: var(--lime-soft);
  --color-lime-mist: var(--lime-mist);
  --color-ink: var(--ink);
  --shadow-float: 0 1px 2px rgb(20 22 20 / 0.04), 0 12px 32px -12px rgb(20 22 20 / 0.14);
  --shadow-lift: 0 2px 6px rgb(20 22 20 / 0.05), 0 28px 56px -20px rgb(20 22 20 / 0.2);
  --animate-rise: rise 0.7s cubic-bezier(0.22, 1, 0.36, 1) both;
  --animate-float-slow: floaty 7s ease-in-out infinite;
}

@keyframes rise {
  from { opacity: 0; transform: translateY(18px); }
  to { opacity: 1; transform: none; }
}

@keyframes floaty {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-10px); }
}

/* Continuous logo marquee. Track holds the list twice, so -50% is one full loop. */
@keyframes marquee {
  from { transform: translateX(0); }
  to { transform: translateX(-50%); }
}

@theme inline {
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);
  --radius-2xl: calc(var(--radius) + 8px);
  --radius-3xl: calc(var(--radius) + 12px);
  --radius-4xl: calc(var(--radius) + 16px);
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-ring-offset-background: var(--background);
  --color-chart-1: var(--chart-1);
  --color-chart-2: var(--chart-2);
  --color-chart-3: var(--chart-3);
  --color-chart-4: var(--chart-4);
  --color-chart-5: var(--chart-5);
  --color-sidebar: var(--sidebar);
  --color-sidebar-foreground: var(--sidebar-foreground);
  --color-sidebar-primary: var(--sidebar-primary);
  --color-sidebar-primary-foreground: var(--sidebar-primary-foreground);
  --color-sidebar-accent: var(--sidebar-accent);
  --color-sidebar-accent-foreground: var(--sidebar-accent-foreground);
  --color-sidebar-border: var(--sidebar-border);
  --color-sidebar-ring: var(--sidebar-ring);
}

:root {
  --radius: 1rem;
  --lime: oklch(0.92 0.2 122);
  --lime-soft: oklch(0.95 0.09 122);
  --lime-mist: oklch(0.975 0.045 124);
  --ink: oklch(0.21 0.008 145);
  --background: oklch(0.982 0.004 106);
  --foreground: oklch(0.21 0.008 145);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.21 0.008 145);
  --popover: oklch(1 0 0);
  --popover-foreground: oklch(0.21 0.008 145);
  --primary: oklch(0.92 0.2 122);
  --primary-foreground: oklch(0.21 0.008 145);
  --secondary: oklch(0.96 0.005 106);
  --secondary-foreground: oklch(0.21 0.008 145);
  --muted: oklch(0.955 0.005 106);
  --muted-foreground: oklch(0.53 0.012 145);
  --accent: oklch(0.975 0.045 124);
  --accent-foreground: oklch(0.21 0.008 145);
  --destructive: oklch(0.577 0.245 27.325);
  --destructive-foreground: oklch(0.984 0.003 247.858);
  --border: oklch(0.918 0.006 106);
  --input: oklch(0.918 0.006 106);
  --ring: oklch(0.92 0.2 122);
  --chart-1: oklch(0.646 0.222 41.116);
  --chart-2: oklch(0.6 0.118 184.704);
  --chart-3: oklch(0.398 0.07 227.392);
  --chart-4: oklch(0.828 0.189 84.429);
  --chart-5: oklch(0.769 0.188 70.08);
  --sidebar: oklch(0.984 0.003 247.858);
  --sidebar-foreground: oklch(0.129 0.042 264.695);
  --sidebar-primary: oklch(0.208 0.042 265.755);
  --sidebar-primary-foreground: oklch(0.984 0.003 247.858);
  --sidebar-accent: oklch(0.968 0.007 247.896);
  --sidebar-accent-foreground: oklch(0.208 0.042 265.755);
  --sidebar-border: oklch(0.929 0.013 255.508);
  --sidebar-ring: oklch(0.704 0.04 256.788);
}

.dark {
  /* NOTE: default shadcn slate/blue — NOT brand-tuned. Re-derive from ink + lime
     before using dark mode in the product. */
  --background: oklch(0.129 0.042 264.695);
  --foreground: oklch(0.984 0.003 247.858);
  --card: oklch(0.208 0.042 265.755);
  --card-foreground: oklch(0.984 0.003 247.858);
  --popover: oklch(0.208 0.042 265.755);
  --popover-foreground: oklch(0.984 0.003 247.858);
  --primary: oklch(0.929 0.013 255.508);
  --primary-foreground: oklch(0.208 0.042 265.755);
  --secondary: oklch(0.279 0.041 260.031);
  --secondary-foreground: oklch(0.984 0.003 247.858);
  --muted: oklch(0.279 0.041 260.031);
  --muted-foreground: oklch(0.704 0.04 256.788);
  --accent: oklch(0.279 0.041 260.031);
  --accent-foreground: oklch(0.984 0.003 247.858);
  --destructive: oklch(0.704 0.191 22.216);
  --destructive-foreground: oklch(0.984 0.003 247.858);
  --border: oklch(1 0 0 / 10%);
  --input: oklch(1 0 0 / 15%);
  --ring: oklch(0.551 0.027 264.364);
  --chart-1: oklch(0.488 0.243 264.376);
  --chart-2: oklch(0.696 0.17 162.48);
  --chart-3: oklch(0.769 0.188 70.08);
  --chart-4: oklch(0.627 0.265 303.9);
  --chart-5: oklch(0.645 0.246 16.439);
  --sidebar: oklch(0.208 0.042 265.755);
  --sidebar-foreground: oklch(0.984 0.003 247.858);
  --sidebar-primary: oklch(0.488 0.243 264.376);
  --sidebar-primary-foreground: oklch(0.984 0.003 247.858);
  --sidebar-accent: oklch(0.279 0.041 260.031);
  --sidebar-accent-foreground: oklch(0.984 0.003 247.858);
  --sidebar-border: oklch(1 0 0 / 10%);
  --sidebar-ring: oklch(0.551 0.027 264.364);
}

@layer base {
  * { border-color: var(--color-border); }

  body {
    background-color: var(--color-background);
    color: var(--color-foreground);
    -webkit-font-smoothing: antialiased;
    font-family: var(--font-sans);
  }

  ::selection { background: var(--lime); color: var(--ink); }
}

@utility dotted-grid {
  background-image: radial-gradient(oklch(0.21 0.008 145 / 0.13) 1px, transparent 1px);
  background-size: 22px 22px;
}

@utility text-italic-serif {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 400;
  letter-spacing: -0.01em;
}
```

## Appendix B — primitives & the `cn` helper

`cn` (class merge) — every component below imports it:

```ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

`primitives.tsx` — the shared building blocks (Pill, GreenBadge, IconChip, TalkToSales,
GhostLink, CheckPill, SoftCard, Eyebrow, Section):

```tsx
import { Link } from "@tanstack/react-router";
import type { LucideIcon } from "lucide-react";
import { Check, ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

export function Pill({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3.5 py-1.5 text-xs font-semibold tracking-tight text-foreground",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function GreenBadge({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full bg-lime-soft px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide text-ink">
      {children}
    </span>
  );
}

export function IconChip({
  icon: Icon,
  size = "md",
}: {
  icon: LucideIcon;
  size?: "sm" | "md" | "lg";
}) {
  const s = size === "sm" ? "size-9 rounded-xl" : size === "lg" ? "size-14 rounded-2xl" : "size-11 rounded-2xl";
  const i = size === "sm" ? "size-4" : size === "lg" ? "size-6" : "size-5";
  return (
    <span className={cn("inline-flex shrink-0 items-center justify-center bg-ink", s)}>
      <Icon className={cn(i, "text-lime-accent")} strokeWidth={2} />
    </span>
  );
}

export function TalkToSales({
  className,
  label = "Talk to Sales",
}: {
  className?: string;
  label?: string;
}) {
  return (
    <Link
      to="/contact"
      className={cn(
        "group inline-flex items-center gap-2 rounded-full bg-lime-accent px-5 py-2.5 text-sm font-semibold text-ink shadow-float transition-all hover:-translate-y-0.5 hover:brightness-105",
        className,
      )}
    >
      {label}
      <ArrowUpRight className="size-4 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
    </Link>
  );
}

export function GhostLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link
      to={to as never}
      className="group inline-flex items-center gap-2 rounded-full border border-border bg-card px-5 py-2.5 text-sm font-semibold text-foreground transition-all hover:-translate-y-0.5 hover:shadow-float"
    >
      {children}
      <ArrowUpRight className="size-4 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
    </Link>
  );
}

export function CheckPill({ children }: { children: ReactNode }) {
  return (
    <li className="flex items-center gap-3 rounded-full border border-border bg-card px-4 py-2.5 text-sm font-medium text-foreground">
      <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-lime-accent">
        <Check className="size-3 text-ink" strokeWidth={3} />
      </span>
      {children}
    </li>
  );
}

export function SoftCard({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "rounded-3xl border border-border bg-card p-6 shadow-float transition-all duration-300 hover:-translate-y-1.5 hover:shadow-lift",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-4 py-1.5 text-xs font-semibold tracking-tight text-muted-foreground">
      <span className="size-1.5 rounded-full bg-lime-accent" />
      {children}
    </span>
  );
}

export function Section({
  children,
  className,
  id,
}: {
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={cn("mx-auto w-full max-w-6xl px-5 py-16 sm:py-24", className)}>
      {children}
    </section>
  );
}
```

`Reveal.tsx` — the scroll-reveal wrapper:

```tsx
import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      setShown(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setShown(true);
          io.disconnect();
        }
      },
      { rootMargin: "0px 0px 0px 0px", threshold: 0 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      style={{ transitionDelay: `${delay}ms` }}
      className={cn(
        "transition-[opacity,transform] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none",
        shown ? "translate-y-0 opacity-100" : "translate-y-4 opacity-0",
        className,
      )}
    >
      {children}
    </div>
  );
}
```

## Appendix C — logo wall (`LogoMarquee.tsx` + data type)

```ts
// integrations-data.ts — shape + example set
export type Integration = { name: string; src: string };

export const integrations: Integration[] = [
  { name: "M-Pesa", src: "/integrations/mpesa.jpg" },
  { name: "Stripe", src: "/integrations/stripe.svg" },
  { name: "Paystack", src: "/integrations/paystack.png" },
  // …one shared set, each usable across every product
];
```

```tsx
import { cn } from "@/lib/utils";
import type { Integration } from "./integrations-data";

/** A single logo in a uniform tile. Full colour by default; pass `grayscale` for
 *  the greyed-until-hover marquee treatment. */
export function LogoTile({
  name,
  src,
  grayscale = false,
}: Integration & { grayscale?: boolean }) {
  return (
    <div className="flex h-24 items-center justify-center rounded-2xl border border-border bg-card px-5 shadow-float">
      <img
        src={src}
        alt={`${name} logo`}
        loading="lazy"
        width={190}
        height={56}
        className={cn(
          "h-14 w-auto max-w-[190px] object-contain transition-all duration-300",
          grayscale && "grayscale opacity-60 hover:grayscale-0 hover:opacity-100",
        )}
      />
    </div>
  );
}

/** Infinite horizontal marquee (greyscale, colour on hover). Track renders the list
 *  twice and animates to -50% for a seamless loop; hover pauses; reduced-motion wraps. */
export function LogoMarquee({
  items,
  reverse = false,
  speed = 40,
}: {
  items: Integration[];
  reverse?: boolean;
  speed?: number;
}) {
  const row = [...items, ...items];
  return (
    <div className="group relative overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_6%,black_94%,transparent)]">
      <ul
        className={cn(
          "flex w-max items-center gap-4 motion-reduce:w-full motion-reduce:flex-wrap motion-reduce:justify-center",
          "[animation:marquee_linear_infinite] group-hover:[animation-play-state:paused] motion-reduce:[animation:none]",
          reverse && "[animation-direction:reverse]",
        )}
        style={{ animationDuration: `${speed}s` }}
      >
        {row.map((it, i) => (
          <li key={`${it.name}-${i}`} className="w-60 shrink-0">
            <LogoTile {...it} grayscale />
          </li>
        ))}
      </ul>
    </div>
  );
}
```

## Appendix D — brand logo mark (`favicon.svg`)

Ink rounded square with a lime rounded square inside. Reused at every size (favicon,
header, footer, app rail).

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Palda">
  <rect width="64" height="64" rx="16" fill="#1b1f19" />
  <rect x="19" y="19" width="26" height="26" rx="8" fill="#c4f542" />
</svg>
```

As markup (header/footer), the same mark is:

```jsx
<span className="flex size-8 items-center justify-center rounded-xl bg-ink">
  <span className="size-3 rounded-[5px] bg-lime-accent" />
</span>
```
