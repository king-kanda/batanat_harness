import { tanstackStart } from '@tanstack/react-start/plugin/vite'
import tailwindcss from '@tailwindcss/vite'
import viteReact from '@vitejs/plugin-react'
import { nitro } from 'nitro/vite'
import { defineConfig } from 'vite'

const config = defineConfig({
  // One .env for the whole monorepo, at the repo root. Only VITE_* vars are
  // exposed to the browser — server secrets in that file are never bundled.
  envDir: '../..',
  resolve: { tsconfigPaths: true },
  // ngrok rotates the subdomain on the free tier, and Vite's host check
  // rejects anything not in this list with a wall of text. `.ngrok-free.app`
  // matches any subdomain under that suffix.
  server: { allowedHosts: ['.ngrok-free.app', 'batanat.okandasteven.me'] },
  // Baked in so a running bundle can say which commit it is. CI passes these
  // as build args; locally they fall back to something honest rather than
  // pretending to be a release.
  define: {
    __BUILD_SHA__: JSON.stringify(process.env.BUILD_SHA ?? 'dev'),
    __BUILD_TIME__: JSON.stringify(process.env.BUILD_TIME ?? ''),
  },
  plugins: [
    // `preset` is pinned, not left to auto-detection. Nitro picks its target
    // from whatever runs the build, and the build stage is `oven/bun`, so it
    // emitted a bundle calling `Bun.serve`. The runtime stage is node:22, which
    // has no `Bun` global — the container crash-looped on
    // `ReferenceError: Bun is not defined` and nginx served 502s. Build tool and
    // runtime are deliberately different here; this is what keeps them apart.
    nitro({ preset: 'node', rollupConfig: { external: [/^@sentry\//] } }),
    tailwindcss(),
    tanstackStart(),
    viteReact(),
  ],
})

export default config
