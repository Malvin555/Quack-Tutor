# Quack landing page (Astro)

Static one-page site for the CLI. No UI framework, no 3D library: Astro, one CSS file, ~250 lines of vanilla TypeScript.

```bash
cd web
npm install
npm run dev        # http://localhost:4321
npm run build      # static site in dist/ (host anywhere, e.g. a .tech domain)
```

Needs Node >= 22.22 (Astro 7).

Set your repo link before publishing: `cp .env.example .env` and fill `PUBLIC_REPO_URL`.
Without it the page shows `<repo-url>` in the install step and hides the "source" link.

## What's on it

- **Margin duck**: an original mascot that walks down the notebook margin a little behind your scroll (slow and steady), leaving a yellow trail. Click any duck for a tip. Eyes follow the pointer.
- **01 ask**: an example session types itself out; hover the callouts to highlight the matching lines.
- **02 how**: the pipeline lights up as you reach each step; only one of six steps uses the model.
- **03 read-only**: type any path. The page runs the same rule as `quack.safety.assert_writable`.
- **04 budget**: a depth slider; lines read and token target come from the build spec.
- **05 models**: local vs remote, opt-in flow, provider chips.

Reduced-motion users get no reveal, typing, or lagging duck. With JS off the content is all visible.

## Honest notes

- The terminal output is **illustrative** (labelled on the page). Replace it with a real capture from `scripts/make_demo.sh` if you want.
- Token numbers are the spec's targets, not measurements.

## Files

`src/pages/index.astro` (content) · `src/components/Duck.astro` (mascot, moods: idle/happy/think/no) ·
`src/scripts/main.ts` (all motion) · `src/styles/global.css` (tokens, light/dark) · `public/favicon.svg`.
