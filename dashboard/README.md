# Earmark dashboard

The caregiver and family dashboard for Earmark (brief section 5.F).
It shows where household items are right now, lets family label items remotely (by hand or from one photo), tracks medication pickups against a schedule, lists recent events, and reports trial results.
It is a React + Vite + TypeScript app. The family pages talk only to Convex, through the function contract in `contracts/ts/convexFunctions.ts`. The `/room` page is separate: it talks to the Earmark hub (the local WebSocket bus) on the demo Mac and never uses Convex.

## Run

```bash
cd dashboard
npm install
VITE_CONVEX_URL="https://<deployment>.convex.cloud" npm run dev
```

Open http://localhost:5173.
For a local Convex backend, `npx convex dev` writes `CONVEX_URL` (for example `http://127.0.0.1:3210`) to the repo-root `.env.local`.
When `VITE_CONVEX_URL` is not set, `vite.config.ts` falls back to that root `CONVEX_URL`, so `npm run dev` needs no extra setup.
Only `CONVEX_URL` is read from the root file; Vite's `envPrefix` is not widened.

With no Convex URL at all, the dashboard shows an accessible "Not connected" page with a link to the demo.

## Demo mode

Add `?demo=1` to any URL, for example http://localhost:5173/?demo=1.
Demo mode uses in-memory fixtures typed with the contract (`src/data/fixtures.ts`, built from `config/space.json` and `config/objects.seed.json`).
Edits work and every page updates live, but nothing is saved and a reload starts over.
Every page shows a "Demo data" banner, and the Trials page says its example trials are made up.
Links keep `?demo=1` so you never fall out of the demo.

The demo household has: sugar on its spot, salt picked up, the medication bottle on its spot, pepper missing, keys roaming near the hub receiver, an unlabeled tag on the far left spot, yesterday's missed 8 PM dose, and six example trials.

## Pages

| Path | What it shows |
| - | - |
| `/` | Live map: a top-down drawing of the spots, a "Not on a spot" list, recent changes, and the same facts as a table (a stacked list on phones). Unlabeled tags link straight to labeling. Changes are announced through a polite live region. |
| `/items` | Every item with its other names, notes, description, home spot, tag, and fob. Edit inline, create (including for an unlabeled tag via `/items?label=<tag>`), delete with an in-page confirmation, or start from a photo. |
| `/medications` | Doses for one household-local day (`?date=YYYY-MM-DD`, date field, previous and next day) as taken, late, missed, or pending with times. Schedule editing (times and window) below. |
| `/timeline` | The latest 100 events from `events.recent`, grouped by household-local day. |
| `/room` | The live room view (3D map, guidance, status, simulated walking). It connects to the Earmark bus at `ws://<host>:8765` (set `VITE_BUS_URL` to use another address), so it only works on the demo Mac. On an https page without `VITE_BUS_URL` it uses `wss://`, and on a deployed host (https, not localhost) it shows a message that the room page only works on the demo Mac. |
| `/trials` | Per-mode raw counts (trials, found, testers, median time to find, wrong picks), a pilot label under 10 completed trials, and every trial in a table. |

## Test

```bash
npm test            # vitest + Testing Library + axe-core, jsdom
npm run typecheck   # tsc, app and config
npm run lint        # ESLint with typescript-eslint, react-hooks, jsx-a11y-x
npm run build       # production build into dist/
npm run e2e         # builds, then checks the real app in Playwright's Chromium
```

`npm test` renders the real app with `convex/react` replaced by `test/convexMock.ts`, which resolves contract function names to fixture data and records every mutation and action call.
It covers each page with contract-shaped data (the missed dose, the unknown tag, the roaming keys, trial stats and the pilot label), the photo flow (upload, suggestion, edit, confirm, and three error paths), axe-core on every page in both themes (and on `/room`, in the light theme it always uses, with the 3D scene not drawn because jsdom has no WebGL), keyboard focus behavior, and the contrast of every design token pair in both themes.

`npm run e2e` (`e2e/check.mjs`) serves `dist/` and, in both color schemes, runs axe-core (WCAG 2.2 A and AA plus best practices, with real color contrast) on every family page (not `/room`) at desktop and phone sizes.
It also checks for horizontal overflow at 320 CSS px and at 200% zoom, runs the photo flow and the remote labeling journey (label the map's new tag, then see it on the map), checks that the theme choice survives a reload, and writes the screenshots in `docs/screenshots/`.
It needs Playwright's Chromium once: `npx playwright install chromium`.

## Build and deploy to Azure Static Web Apps

`public/staticwebapp.config.json` rewrites client routes to `index.html` (see `docs/sponsors/vendor-notes/azure.md` section 4).
The Convex URL is baked in at build time and is public by design; never put a secret in a `VITE_` variable.

```bash
cd dashboard
npm ci
VITE_CONVEX_URL="https://<deployment>.convex.cloud" npm run build

az staticwebapp create --name $SWA_NAME --resource-group $RG --location $LOCATION --sku Free
export SWA_CLI_DEPLOYMENT_TOKEN=$(az staticwebapp secrets list --name $SWA_NAME --query "properties.apiKey" -o tsv)
npm install -g @azure/static-web-apps-cli
swa deploy ./dist --env production
az staticwebapp show --name $SWA_NAME --resource-group $RG --query defaultHostname -o tsv
```

If the subscription's region policy blocks Static Web Apps, use the Azure Storage static website fallback in `docs/sponsors/vendor-notes/azure.md` section 4.5.
Remote labeling from a phone needs a cloud Convex deployment; a local anonymous deployment is only reachable from this Mac.

## Environment

| Variable | Where | Meaning |
| - | - | - |
| `VITE_CONVEX_URL` | shell or `dashboard/.env.local`, at build time | Convex deployment URL, for example `https://<deployment>.convex.cloud` |
| `VITE_BUS_URL` | shell or `dashboard/.env.local`, at build time | Optional. Full WebSocket URL of the Earmark hub for `/room`, for example `wss://<host>:8765`. Without it the page uses `ws://` (or `wss://` on https) on port 8765 of the page's host |
| `CONVEX_URL` | repo-root `.env.local` (written by `npx convex dev`) | Fallback for `VITE_CONVEX_URL` in dev and build |

## Accessibility

Accessibility is a requirement here (brief rule 7), and each item below is tested.
- Landmarks: banner, main navigation, main, and footer; a skip link is the first focusable element; one `h1` per page and headings in order.
- After a client-side navigation, focus moves to the new page's `h1` and the document title changes.
- Every status is a word plus a distinct icon shape (filled disc, arrow, question mark, signal arcs, check, clock, octagon, dashed circle), never color alone; missed doses also get a strong left bar and tinted row.
- The map is a `role="img"` SVG with a title and a generated description of every spot, and it is never the only source: the table (or the stacked list on phones) carries the same facts.
- Live map changes are announced politely ("Salt picked up from the center left spot.") and listed under "Recent changes".
- All controls are native elements with visible labels and hints tied by `aria-describedby`; errors use `aria-invalid`, sit next to the field, and move focus to it.
- Deleting asks for confirmation inside the page, with focus moved to the confirmation; no browser dialogs.
- Contrast: all text tokens meet 7:1 (AAA) in both themes, and control borders meet 3:1; `test/tokens.test.ts` enforces it, and the Chromium run found nothing below AAA.
- Light and dark themes follow the system setting; the System / Light / Dark switch persists in `localStorage` and is applied before first paint.
- `prefers-reduced-motion` turns off the only animation (one pulse on a spot that changed), and forced-colors mode keeps the map visible.
- Text is set in Atkinson Hyperlegible Next, designed by the Braille Institute for low-vision readers, at an 18 px base size; tag IDs use Atkinson Hyperlegible Mono so 0 and O differ.
- Layout reflows at 320 CSS px and at 200% zoom without horizontal scrolling, and touch targets are at least 40 px tall (48 px for main buttons).

## What is mocked

- Demo mode (`?demo=1`) mocks the whole backend in memory, including the photo suggestion (it returns a canned "honey" suggestion and names itself "demo fixture (no model was called)").
- The demo applies its own copy of the adherence rule from `contracts/README.md` so doses look right at any time of day; the real rule runs in Convex.
- Tests mock `convex/react` and the photo shrinker (jsdom has no canvas); the Chromium run exercises the real shrinker.
- `e2e/live.mjs` has been run against the real Convex backend (screenshots are in `docs/screenshots/live/`). The unit tests and `npm run e2e` still use mocks and demo data.
- `/room` is tested with a fake WebSocket; it has not been checked against the real hub in an automated test, and the 3D scene is not drawn in jsdom.

## Decisions

- One data interface (`src/data/backend.tsx`) with two implementations, real Convex and demo fixtures, chosen once at startup; pages never know which one they have.
- `wouter` for routing (small, hooks-based) and plain CSS with design tokens; no UI framework.
- The contract's `fn` references are imported from `../contracts/ts` through the `@contracts` alias, and Vite's `resolve.dedupe` makes `convex/server` resolve to this package's copy, so only one `convex` is bundled.
- Colors use CSS `light-dark()` with `color-scheme`, so each token is defined once for both themes.
- The palette is cool porcelain and deep slate with a damson plum accent, chosen to be calm and to stay clear of the status colors (green, amber, red).
- The map draws text in screen pixels, wraps labels to the space between spots, and pushes labels apart until nothing overlaps, so it stays readable on a phone.
- Roaming items are drawn at the position the hub resolved (the receiver's position) with a dashed outline and a range word, not a ring of made-up radius, because proximity is coarse.
- Household-local time (`household.timezone`) is used for every displayed time, and the time zone is named on the page, since a caregiver may live elsewhere.
- Edits send only the changed fields to `objects.update`, so two family members editing different fields don't overwrite each other.
- The photo flow offers two buttons: "Take a photo" (`capture="environment"`) and "Choose a photo" (no capture), because `capture` alone hides the photo library on phones.
- Photos are shrunk on the device to a JPEG under about 950 KB (longest edge 1600 px or less) before upload.
- The photo flow claims "Photo deleted" only when the action returns `photoDeleted: true`; on errors it says only that nothing was saved, because the dashboard cannot know the server's cleanup state.
- The pilot label uses the total of completed trials across both modes (under 10), and the page shows counts and medians side by side without computing ratios or percentages.
- ESLint 10 with `eslint-plugin-jsx-a11y-x` (the maintained ESLint 10 fork of jsx-a11y) and TypeScript 5.9 (to match `contracts/ts` and typescript-eslint's supported range).
- Medication schedule windows are limited to 5 to 240 minutes in the form.

## Files

- `src/main.tsx` picks the mode (Convex, demo, or not connected) and renders `src/App.tsx`.
- `src/data/` holds the backend interface, the Convex adapter, the demo backend, and the fixtures.
- `src/room/` holds the `/room` page: `RoomPage.tsx`, the bus hook `useBus.ts`, the state model `model.ts`, the three.js scene `scene3d.ts`, and `room.css`.
- `src/pages/` holds one file per page, plus `MapField.tsx` (the SVG map), `ItemForm.tsx`, and `PhotoLabel.tsx`.
- `src/lib/` holds time formatting, wording, change descriptions, error messages, photo shrinking, and the theme switch.
- `src/styles/tokens.css` and `src/styles/app.css` hold all styling.
- `test/` holds the vitest suite; `e2e/check.mjs` holds the Chromium check; `e2e/live.mjs` screenshots every page against a real Convex deployment (`node e2e/live.mjs [baseUrl] [outDir]`); `docs/screenshots/` holds their output.
