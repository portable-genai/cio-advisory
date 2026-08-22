# Doc3 CIO Advisory Assistant : UI

A small React / Next.js console for the Doc3 backend. It lets a relationship manager pick a
client, build a suitability-checked advisory briefing, and read the personalised talking
points (each tagged with a suitability verdict and citations) and the portfolio alignment.

The whole surface is framed as **decision-support, not advice**: a persistent non-advice
banner, a "not advice" pill on every talking point, and a "requires human review" flag on
every briefing.

## Develop

```bash
cp .env.local.example .env.local   # point NEXT_PUBLIC_API_BASE at the backend (:8091)
npm install
npm run dev                        # http://localhost:3000
```

The backend CORS allows `localhost:3000`. Start the API with `make run-api` (or
`cio-advisory serve`).

## Source map

```
app/
  layout.tsx     root layout + metadata
  page.tsx       the console (pick client -> build briefing)
  globals.css    Tailwind base + thin scrollbars
components/
  ClientPanel    left rail: choose a client, run the briefing
  BriefingView   the not-advice banner, talking points, alignment
  TalkingPointView  one suitability-checked point (never advice)
  SuitabilityBadge  verdict pill + factors
  AlignmentPanel    in-line / gaps / overweights
  CitationCard      a single house-view or portfolio citation
  ui            shared primitives (Panel, Pill, banners)
lib/
  types.ts       TypeScript mirrors of the domain dataclasses
  api.ts         typed fetch client for the Doc3 endpoints
  csp.mjs        the ONE place the Content-Security-Policy is built
proxy.ts         the ONE place it is emitted (per-request script nonce)
scripts/
  assert-hydratable.mjs  starts the built server, proves the page hydrates
tests/
  csp.test.mjs   unit cover for csp.mjs (`npm test`)
```

## Gate

`make ui-check` (from the repo root) runs types, the CSP unit tests, a real build, and then
`assert-hydratable` against the artefact that build produced. The last step is the one that
matters: the console's `script-src` carries a per-request nonce, and Next can only stamp that
onto a dynamically rendered route, so `app/layout.tsx` sets `export const dynamic =
"force-dynamic"`. If that ever goes away the CSP header still looks perfect while every script
tag ships bare, the browser blocks them all, and the console renders as dead markup that
screenshots exactly like a working one. Only starting the server and reading the served HTML
can tell the two apart. See `docs/embedding-and-identity.md` section 3e.

Source only: `node_modules` and `.next` are gitignored and the Python gate (`make check`) does
not build the UI; `make ui-check` is the node half and needs node installed.
