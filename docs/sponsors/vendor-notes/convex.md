# Convex vendor notes

Verified 2026-10-24 against docs.convex.dev (index: https://docs.convex.dev/llms.txt; every page is also served as Markdown by appending `.md`), the `convex` 1.48.0 npm package source, PyPI, and the convex-esp32 README.
I also exercised the local, account-free flow end to end in a throwaway project outside the repo (convex 1.48.0, Node 26.10.0, macOS): anonymous deployment, HTTP action with a secret header, env vars, typed `env`, an interval cron, `npx convex run`, `npx convex import`, `ai-files install`, convex-test with Vitest 5, and the Python client.
Anything marked "observed" comes from that run; anything marked UNVERIFIED is an inference or a gap in the docs.
Hackathon details (prize, workshop, the home-page agent prompt) are in `docs/sponsors/sponsor-packs/convex.md`.
The official AI guidelines are copied verbatim in `docs/sponsors/vendor-notes/convex-ai-guidelines.md`; read them before writing any Convex code.

## Quick reference for Earmark

| Item | Value | Source |
| - | - | - |
| npm `convex` | 1.48.0 (published 2026-10-22) | `npm view convex version` |
| Guidelines target | Convex `^1.44.0` | `convex/_generated/ai/guidelines.md` line 3 |
| `convex-test` / `vitest` / `@edge-runtime/vm` | 0.0.65 / 5.0.5 / 5.0.0 (observed working together) | `npm view` |
| PyPI `convex` | 0.8.1 (2026-09-14), Python >= 3.10 | https://pypi.org/project/convex/ |
| AI files | `npx convex ai-files install` | https://docs.convex.dev/cli/reference/ai-files |
| No-account dev | `CONVEX_AGENT_MODE=anonymous npx convex dev --once`, then keep `npx convex dev` running | https://docs.convex.dev/cli/agent-mode |
| Local client URL | `http://127.0.0.1:3210` (`CONVEX_URL`) | observed |
| Local HTTP actions URL | `http://127.0.0.1:3211` (`CONVEX_SITE_URL`) | observed |
| Local dashboard | `http://127.0.0.1:6790/` via `npx convex dashboard` (not Safari) | observed; https://docs.convex.dev/cli/local-deployments |
| Cloud client URL | `https://<deployment>.convex.cloud` | https://docs.convex.dev/production/environment-variables |
| Cloud HTTP actions URL | `https://<deployment>.convex.site` | https://docs.convex.dev/functions/http-actions |
| Node actions | Node 22 or 24 only; local deployments use the `node` on PATH | https://docs.convex.dev/config/convex.json |

## 1. AI guidelines install procedure (do this first)

The home-page prompt (verbatim in the sponsor pack) says that for "any other project" you run `npm install convex`, add an empty `convex/schema.ts` and a `convex dev` script, then run `npx convex ai-files install`, and never run `npm create convex` in an existing folder (https://www.convex.dev).
The CLI reference documents the same command and its siblings `status`, `update`, `disable`, `enable`, and `remove` (https://docs.convex.dev/cli/reference/ai-files).
`npx convex dev` does not install the AI files on its own in a non-interactive shell; it only prints "Convex AI files are not installed. Run npx convex ai-files install" (observed).

What `npx convex ai-files install` wrote in the scratch project (observed):
- `convex/_generated/ai/guidelines.md`, downloaded from `https://version.convex.dev/v1/guidelines` (CLI source `dist/esm/cli/lib/versionApi.js`).
  It is byte-identical to the rules file linked from https://docs.convex.dev/ai (https://convex.link/convex_rules.txt).
- `convex/_generated/ai/ai-files.state.json` (content hashes).
- `AGENTS.md` and `CLAUDE.md` at the project root, each with a Convex-managed section between `<!-- convex-ai-start -->` and `<!-- convex-ai-end -->` that says to read `convex/_generated/ai/guidelines.md` first.
  If those files already exist, only the managed section is added or refreshed (https://docs.convex.dev/cli/reference/ai-files).
- 33 skills copied to `.claude/skills/convex*/` (Claude Code) and the same 33 to `.agents/skills/convex*/` (Codex), plus `skills-lock.json`.
  The CLI does this by running `npx skills add convex/agent-skills --yes --copy --agent claude-code --agent codex` (CLI source `lib/aiFiles/skills.js`).
  The agent list comes from `convex.json` `aiFiles.skills.agents`, default `["claude-code", "codex"]` (https://docs.convex.dev/ai/overview).

For Earmark, run it from the directory whose `package.json` lists `convex` (the repo root, see section 9), because that is where `AGENTS.md`, `CLAUDE.md`, `.claude/skills/`, and `.agents/skills/` land.
The existing `.claude/agents/` directory is not touched.
The prompt warns that the command exits 0 even when downloads fail, so check that `convex/_generated/ai/guidelines.md` and `.agents/skills` exist afterwards.
Convex says to commit everything in `convex/_generated/` (https://docs.convex.dev/understanding/workflow), and the current `.gitignore` does not exclude any of these files.

The prompt also asks the agent to install the Convex plugin with `claude plugin marketplace add anthropics/claude-plugins-official` then `claude plugin install convex@claude-plugins-official --scope user` (and the Codex equivalent).
That changes the human's user-level agent configuration, so it is an orchestrator or human decision; I did not run it.
The plugin bundles the same rules plus MCP tools and hooks (https://docs.convex.dev/ai/using-claude-code).

## 2. Running without a Convex account

### How it works

- In a non-interactive shell with no deployment configured and no `CONVEX_DEPLOY_KEY`, `npx convex` never prompts for login and provisions a local deployment automatically (https://docs.convex.dev/cli/agent-mode).
- `CONVEX_AGENT_MODE=anonymous` forces that path even in a TTY and names the deployment `anonymous-agent` (CLI source `lib/localDeployment/anonymous.js`; it prints "CONVEX_AGENT_MODE=anonymous mode is in beta").
- The first run downloads the backend binary (about 190 MB into `~/.cache/convex/`, observed), so it needs real internet once.
  That download is already done on this machine (`precompiled-2026-10-10-72ce13c`).
- Local deployments are a beta feature (https://docs.convex.dev/cli/local-deployments).

### Exact commands (observed)

```sh
# One-shot: configure the local deployment, codegen, typecheck, push functions, exit.
CONVEX_AGENT_MODE=anonymous npx convex dev --once

# Long-running: the local backend lives only while this runs. Hub, dashboard, and agents need it.
CONVEX_AGENT_MODE=anonymous npx convex dev
```

`--once` printed:

```
✔ Configured a local deployment for http://127.0.0.1:3210 and saved its:
    name as CONVEX_DEPLOYMENT
    client URL as CONVEX_URL
    HTTP actions URL as CONVEX_SITE_URL
 to .env.local
  Added ".env.local" to .gitignore
▌ [Local] Port 3210 • No Convex account (run npx convex login to link to a project)
```

The resulting `.env.local` (observed, verbatim):

```
# Deployment used by `npx convex dev`
CONVEX_DEPLOYMENT=anonymous:anonymous-agent

CONVEX_URL=http://127.0.0.1:3210

CONVEX_SITE_URL=http://127.0.0.1:3211
```

- Ports start at 3210 (client) and 3211 (HTTP actions) and move up if taken (CLI source `lib/localDeployment/utils.js`).
- State lives in `.convex/local/default/` (SQLite plus file storage), which the repo `.gitignore` already excludes.
- The URL variable names depend on the framework detected from the `package.json` next to `convex/`: plain `CONVEX_URL`/`CONVEX_SITE_URL` with no framework, `VITE_CONVEX_URL`/`VITE_CONVEX_SITE_URL` if `vite` is a dependency (CLI source `lib/envvars.js`).
  The CLI keeps exactly one of the known names per file and refuses to edit if it finds two.
- `.env.local` only tells the CLI and clients which deployment to use; backend functions never read it (https://docs.convex.dev/client/react/deployment-urls).

### Gotchas (observed unless linked)

- `npx convex dev --once` fails while another `npx convex dev` holds the backend: "A local backend is still running on port 3210. Please stop it and run this command again."
  With the watcher running, just save files; it re-pushes on change.
- `npx convex run` worked with no `npx convex dev` running (it started the backend transiently), but `npx convex export` failed with "Local backend isn't running".
  The docs say a `convex dev` must be running for such commands (https://docs.convex.dev/cli/local-deployments), so scripts should assume it is.
- No public URL: local deployments only listen on this Mac (https://docs.convex.dev/cli/local-deployments, "Limitations").
  This breaks, until there is a cloud deployment or a tunnel such as ngrok: a family member labeling from their own phone (5.F), a dashboard hosted on Azure (6.1), a memory agent hosted off this Mac calling the read endpoints (5.G), and any external service fetching a `ctx.storage.getUrl()` link.
  Everything on this Mac (hub, concierge, local uAgent, local dashboard) works against `127.0.0.1`.
- `"use node"` actions run with the `node` on PATH, which must be a supported version (https://docs.convex.dev/cli/local-deployments).
  Supported values are 22 and 24 (https://docs.convex.dev/config/convex.json).
  This Mac's default `node` is 26.10.0 (Homebrew); `/usr/local/bin/node` is 24.13.0.
  Avoid `"use node"` entirely: `fetch` works in the default runtime (https://docs.convex.dev/functions/actions).
- Logs are cleared every time `npx convex dev` restarts, and Safari and Brave block the local dashboard by default (https://docs.convex.dev/cli/local-deployments).
- The dashboard link printed by `dev` is `null` for anonymous deployments; use `npx convex dashboard`, which printed `http://127.0.0.1:6790/`.

### Moving to a cloud deployment after the human logs in

1. The human runs `npx convex login` (interactive browser login).
   After login it asks "Would you like to link your existing deployment to your account?" and links the anonymous local deployment to a new project (CLI source `login.js`, `handleLinkingDeployments`).
   `npx convex login --link-deployments` re-offers this later.
2. Switch this checkout to the personal cloud dev deployment with `npx convex deployment select dev` (https://docs.convex.dev/cli/local-deployments), or reconfigure with `npx convex dev --configure existing --team <team> --project <project> --dev-deployment cloud` (`npx convex dev --help`).
   `npx convex deployment select local` switches back (https://docs.convex.dev/cli/agent-mode).
3. The CLI rewrites `.env.local` to `CONVEX_DEPLOYMENT=dev:<name> # team: <team>, project: <project>`, with `CONVEX_URL=https://<name>.convex.cloud` and `CONVEX_SITE_URL=https://<name>.convex.site` (format from CLI source `lib/deployment.js`; values UNVERIFIED because I could not log in).
4. Re-set every environment variable on the new deployment; they are per deployment (https://docs.convex.dev/production/environment-variables).
5. Re-seed, because data is per deployment (https://docs.convex.dev/cli/local-deployments).
   Either rerun the seed command, or move data with `npx convex export --path snap.zip` (while the local `npx convex dev` runs) and `npx convex import snap.zip` against the cloud deployment (https://docs.convex.dev/cli/reference/export, https://docs.convex.dev/database/import-export/import).
6. For production, `npx convex deploy` (https://docs.convex.dev/cli/reference/deploy).
7. Alternative for a headless agent once an account exists: `npx convex deployment create --type dev --select <team>:<project>:dev/<name>` plus `npx convex deployment token create agent-token --save-env` writes a scoped `CONVEX_DEPLOY_KEY` to `.env.local` (https://docs.convex.dev/cli/agent-mode).

## 3. HTTP actions

- Define routes in `convex/http.ts` with `httpRouter()` and `httpAction`, and make the router the default export (https://docs.convex.dev/functions/http-actions).
- `http.route({ path, method, handler })` matches the exact path; `pathPrefix: "/x/"` matches everything under it.
  Query strings are not part of `path`, so `GET /api/object?name=salt` is `path: "/api/object"` plus `new URL(req.url).searchParams.get("name")`.
- The handler gets `(ctx, request)`: a standard `Request` in, a standard `Response` out; `ctx` has `runQuery`, `runMutation`, `runAction`, `storage`, `scheduler`, and `auth`, but no `ctx.db`.
- HTTP actions have no argument validators.
  The guidelines say to treat `await req.json()` as `unknown`, narrow every field, and return 400 on bad bodies (`convex-ai-guidelines.md`, "HTTP endpoints").
- Read headers with `request.headers.get("X-Earmark-Secret")` (case-insensitive).
- Return JSON with `Response.json(value)` or `new Response(JSON.stringify(v), { headers: { "content-type": "application/json" } })`.
- HTTP actions are not retried by Convex; the caller retries (https://docs.convex.dev/functions/http-actions, "Limits").
  The contract already makes `/ingest` idempotent by `event_id`, which is what makes the hub's offline-queue retries safe.
- Limits: `multipart/form-data` bodies up to 20 MiB, responses up to 100 MiB, 64 MiB memory (same page).
- `defineApp({ httpPrefix: "/app/" })` in `convex/convex.config.ts` can namespace all routes; Earmark does not need it.
- CORS is only needed for browser callers.
  The dashboard talks to Convex through the WebSocket client, and the hub and agents are server-side, so Earmark's HTTP actions need no CORS headers.
  If a browser ever calls one, add `Access-Control-Allow-Origin` and an `OPTIONS` route as in https://docs.convex.dev/functions/http-actions#cors.
- Client URL vs site URL: clients (`ConvexReactClient`, Python `ConvexClient`, `npx convex`) use `CONVEX_URL` (`:3210` or `.convex.cloud`); HTTP actions are served only on `CONVEX_SITE_URL` (`:3211` or `.convex.site`).
  Inside functions both are available as `CONVEX_CLOUD_URL` and `CONVEX_SITE_URL` (observed: `http://127.0.0.1:3210` and `http://127.0.0.1:3211` locally).

This route ran in the scratch deployment and returned 401 with no secret, 400 for a bad body, and 200 with a stored row otherwise (observed):

```ts
// convex/http.ts
import { httpRouter } from "convex/server";
import { env, httpAction } from "./_generated/server";
import { internal } from "./_generated/api";

const http = httpRouter();
http.route({
  path: "/ingest",
  method: "POST",
  handler: httpAction(async (ctx, req) => {
    if (req.headers.get("x-earmark-secret") !== env.HUB_SECRET) {
      return new Response("unauthorized", { status: 401 });
    }
    const body: unknown = await req.json();
    const note =
      typeof body === "object" && body !== null && "note" in body && typeof body.note === "string"
        ? body.note
        : null;
    if (note === null) return new Response("bad request", { status: 400 });
    await ctx.runMutation(internal.pings.add, { note });
    return Response.json({ ok: true });
  }),
});
export default http;
```

For Earmark, the secret names and bodies come from `contracts/schemas/convex_http.schema.json` (`X-Earmark-Secret`, `EARMARK_HUB_SECRET`, `EARMARK_READ_SECRET`, snake_case on the wire, camelCase in tables).
Do the whole ingest batch in one internal mutation so it is one transaction (guidelines, "Function calling").

## 4. Schema, validators, and query rules

From https://docs.convex.dev/database/schemas, https://docs.convex.dev/functions/validation, https://docs.convex.dev/database/reading-data/indexes, and the guidelines:
- `convex/schema.ts`: `export default defineSchema({ table: defineTable({ ... }).index("by_field", ["field"]) })`, importing `defineSchema`/`defineTable` from `convex/server` and `v` from `convex/values`.
- Validators: `v.string()`, `v.number()`, `v.boolean()`, `v.null()`, `v.id("objects")`, `v.array(x)`, `v.object({...})`, `v.record(k, val)`, `v.union(...)`, `v.literal("taken")`, `v.optional(x)`, `v.nullable(x)` (same as `v.union(x, v.null())`), `v.any()`.
- Status enums are `v.union(v.literal("taken"), v.literal("late"), v.literal("missed"), v.literal("pending"))`.
- `_id` and `_creationTime` (ms since epoch) are added automatically.
- `undefined` is not a Convex value and comes back to clients as `null`; return `null`, not nothing.
- Arrays hold at most 8192 values and objects at most 1024 entries; keys cannot start with `$` or `_`.
- Name each index after all its fields (`by_objectId_and_t`) and query fields in declared order (guidelines, "Schema guidelines").
- Every function, of every kind, gets argument validators (guidelines, "Function registration").
- Anything only Convex itself calls (the ingest commit mutation, cron targets, scheduled actions) is `internalMutation`/`internalQuery`/`internalAction`, referenced as `internal.file.fn`.
- Use `.withIndex(...)` with the predicate in the index range, not `.filter()`.
- Bound every read with `.take(n)` or `.paginate()` rather than `.collect()`.
- Never use `.collect().length` for counts.
- Use `.unique()` for exactly-one lookups.
- Do not read `Date.now()` in a query: queries are cached and re-run only when data changes (https://docs.convex.dev/understanding/best-practices#date-in-queries).
  This matters for adherence: "missed" depends on the clock, so materialize dose status in the cron mutation (mutations may call `Date.now()`), or pass `now` as a query argument rounded to the minute.
- Since convex 1.31 the `ctx.db` methods take the table name first: `ctx.db.get("objects", id)`, `ctx.db.patch("objects", id, {...})`, `ctx.db.replace(...)`, `ctx.db.delete("objects", id)` (https://docs.convex.dev/understanding/best-practices).
- `ctx.db.patch` and `ctx.db.replace` throw if the document does not exist.
- Do not keep unbounded lists inside one document; `events` is its own append-only table keyed by `objectId`.
- Import `Id` and `Doc` from `./_generated/dataModel`, and type helpers with `QueryCtx`/`MutationCtx`/`ActionCtx` from `./_generated/server`.

## 5. Crons, scheduled functions, actions

- Crons live in `convex/crons.ts`: `const crons = cronJobs(); crons.interval("name", { minutes: 5 }, internal.doses.recompute, {}); export default crons;` (https://docs.convex.dev/scheduling/cron-jobs).
- The guidelines say to use only `crons.interval` or `crons.cron` and always pass a function reference (`convex-ai-guidelines.md`, "Cron guidelines").
  The docs also offer `crons.daily`/`hourly`/`weekly`/`monthly`; follow the guidelines and use `crons.cron("...")` for a daily summary.
- Cron strings are UTC, so compute household-local times (America/Los_Angeles in `config/objects.seed.json`) in code.
- `crons.interval` supports seconds and its first run happens on deploy; at most one run of a job executes at a time.
- Observed: an interval cron with `{ seconds: 2 }` ran on the local anonymous deployment.
- Schedule from a mutation with `await ctx.scheduler.runAfter(0, internal.mod.fn, args)` (delay in ms) or `runAt(timestampMs, ...)` (https://docs.convex.dev/scheduling/scheduled-functions).
  Scheduling from a mutation is atomic with it.
- Scheduled mutations run exactly once; scheduled actions run at most once and are not retried.
- Actions call external APIs with plain `fetch` in the default runtime; no `"use node"` is needed (https://docs.convex.dev/functions/actions).
  Actions time out after 10 minutes, have 64 MB of memory in the default runtime, and have no `ctx.db`, so they read and write through `ctx.runQuery`/`ctx.runMutation`.
- Calling an action directly from the client is called an anti-pattern; have the client call a mutation that records intent and schedules an internal action (same page).
- Keep `ctx.runQuery`/`ctx.runMutation` calls per action few, since each is a separate transaction.

## 6. File storage (one-time caregiver photo, then delete)

APIs (https://docs.convex.dev/file-storage/upload-files, `serve-files`, `delete-files`, `file-metadata`):
- `await ctx.storage.generateUploadUrl()` in a mutation returns a short-lived POST URL; it expires in 1 hour.
- The browser POSTs the file with its `Content-Type`, and the response JSON is `{ storageId }`.
  The upload request has a 2-minute timeout.
- Validate the ID as `v.id("_storage")`.
- `await ctx.storage.get(storageId)` returns a `Blob` or `null`, in actions and HTTP actions.
- `await ctx.storage.getUrl(storageId)` returns a bearer URL that anyone holding it can open, or `null`.
- `await ctx.storage.delete(storageId)` works in mutations, actions, and HTTP actions.
- Metadata comes from `await ctx.db.system.get("_storage", storageId)`; `ctx.storage.getMetadata` is deprecated (guidelines, "File storage guidelines").

Suggested flow for 5.F (a sketch; it has not been run):
1. Dashboard: `useMutation(api.photos.generateUploadUrl)`, then POST the file and get `storageId`.
2. Dashboard: `useMutation(api.photos.requestSuggestion)({ storageId })`; the mutation inserts a pending suggestion row and calls `ctx.scheduler.runAfter(0, internal.photos.suggest, { suggestionId, storageId })`.
3. `internal.photos.suggest` (internalAction, default runtime) reads the bytes with `ctx.storage.get`, base64-encodes them into a `data:` URL, and calls Claude Haiku 5.5 (Anthropic Messages API) with `fetch`.
   `btoa` and `Blob` exist in the default runtime (https://docs.convex.dev/functions/runtimes); encode in chunks because spreading a large `Uint8Array` into `String.fromCharCode` can overflow the stack.
4. It writes only the text suggestion through an internal mutation and calls `ctx.storage.delete(storageId)` in a `finally` block, so the photo is deleted on success and on failure.
5. The dashboard shows the suggestion through `useQuery` and saves only after the human confirms.

Send bytes, not `getUrl()`: on a local deployment the URL is `127.0.0.1` and unreachable from Anthropic, and on cloud it is a bearer link to the photo.
Add a small cron that deletes any `_storage` file older than a few minutes that is not tied to a pending suggestion, for abandoned uploads (my recommendation).

## 7. Environment variables

- Set per deployment with `npx convex env set NAME 'value'`, `npx convex env set --from-file .env.convex`, or `printf %s "$SECRET" | npx convex env set NAME` to keep it out of shell history (https://docs.convex.dev/cli/reference/env).
- List with `npx convex env list --names-only`; under an AI agent (`CLAUDECODE` is detected) it lists names only unless `--include-values` is passed.
- Observed on the local deployment: `✔ Successfully set HUB_SECRET (on anonymous deployment anonymous-agent)`.
- Declare expected variables in `convex/convex.config.ts` and read them through the typed `env` export (https://docs.convex.dev/production/environment-variables#declaring):

  ```ts
  // convex/convex.config.ts
  import { defineApp } from "convex/server";
  import { v } from "convex/values";
  const app = defineApp({ env: { EARMARK_HUB_SECRET: v.string(), ANTHROPIC_API_KEY: v.optional(v.string()) } });
  export default app;
  ```

  Then `import { env } from "./_generated/server"` and read `env.EARMARK_HUB_SECRET`.
  Both the guidelines and the best-practices page prefer `env` over `process.env` (https://docs.convex.dev/understanding/best-practices).
  Observed working on the local deployment.
- Declared required variables are validated at deploy time, so set them before the push that declares them.
  `env set` needs a configured deployment, so run `dev --once` first, then `env set`, then add the declaration, or declare them `v.optional` (https://docs.convex.dev/cli/agent-mode).
- `process.env.NAME` still works (`string | undefined`).
- Do not choose exports based on env vars; crons read env only at deploy time (https://docs.convex.dev/production/environment-variables).
- Limits: 512 variables, 8 KiB per value.

## 8. Testing

convex-test setup (https://docs.convex.dev/testing/convex-test; guidelines "Testing guidelines"):
- `npm install --save-dev convex-test vitest @edge-runtime/vm`; the guidelines say to install the latest versions.
- `vitest.config.ts`: `export default defineConfig({ test: { environment: "edge-runtime" } })`.
- Put tests under `convex/` (`convex/*.test.ts`); observed: test files there do not break `npx convex dev`.
- In each test file add `/// <reference types="vite/client" />`, build `const modules = import.meta.glob("./**/*.ts")`, then `const t = convexTest(schema, modules)`.
- Call functions with `t.query(api.x.y, args)`, `t.mutation(internal.x.y, args)`, and `t.action(...)`; seed with `t.run(async (ctx) => ctx.db.insert(...))`; call HTTP routes with `t.fetch("/ingest", { method: "POST", headers, body })`.
- Scheduled functions: `vi.useFakeTimers()`, then `t.finishInProgressScheduledFunctions()` or `t.finishAllScheduledFunctions(vi.runAllTimers)`.
- convex-test does not run cron jobs; call the cron's target function directly.
  It also does not enforce limits, and its runtime is an Edge Runtime mock, not the real Convex runtime.
- Mock `fetch` for the Claude action with `vi.stubGlobal("fetch", vi.fn(...))` as in the docs' example.
  The same page warns that `vi.stubGlobal` redefines globals and should be avoided while functions run; the docs' fetch example still uses it, so follow the example and unstub afterwards.
- Observed: convex-test 0.0.65 with vitest 5.0.5 and @edge-runtime/vm 5.0.0 passed a mutation/query test and an HTTP 401 test in about 115 ms.
  The docs only mention Vitest 3 and 4.

Pure TypeScript helpers (the adherence rule, local-time math):
- Put them in a module with no Convex imports (for example `convex/lib/adherence.ts`) that takes `now`, the schedule, and pickup times as arguments.
- Unit-test it with plain Vitest; no `convexTest` is needed, and it runs fine in the same `edge-runtime` environment.
- Call it from the cron mutation, so the rule is tested once and the mutation stays thin.

For tests against a real backend, see https://docs.convex.dev/testing/convex-backend.

## 9. Clients

### Python (hub, concierge, memory agent)

- `pip install convex` (0.8.1, Python >= 3.10); usage is `from convex import ConvexClient; c = ConvexClient(url)`, then `c.query("file:fn", args)`, `c.mutation(...)`, `c.action(...)`, `c.subscribe(...)` (an iterator), plus `set_auth`, `set_admin_auth`, and `set_debug` (https://pypi.org/project/convex/).
- Function names are strings like `"objects:list"`.
- It can call only public functions; calling an internal one gave "Could not find public function" (observed).
  `set_admin_auth(admin_key)` can reach internal functions, but the admin key is a deployment master secret.
- Observed: `subscribe` delivered a new value about 60 ms after a write, but while the iterator waits, every other Python thread in the process stops running (reproduced on Python 3.11 and 3.15 with convex 0.8.1).
  Do not run `subscribe` inside the asyncio concierge or hub process; put it in a dedicated process, or poll.

Recommendation:
- The hub should use plain HTTPS to the HTTP actions (`POST {CONVEX_SITE_URL}/ingest` with `X-Earmark-Secret`), as the brief and contract already specify.
  It adds no dependency, keeps internal functions internal, and fits the retry and offline queue.
- The concierge picks up label edits within seconds by polling `GET {CONVEX_SITE_URL}/api/registry`, or by running a small subscriber process that forwards changes to the hub bus.
- The memory agent uses the `GET /api/*` read endpoints only, per 5.G.

### React dashboard

- `import { ConvexProvider, ConvexReactClient, useQuery, useMutation } from "convex/react"`, with `new ConvexReactClient(import.meta.env.VITE_CONVEX_URL)` wrapping the app in `<ConvexProvider client={convex}>` (https://docs.convex.dev/quickstart/react).
- `useQuery(api.objects.list, args)` returns `undefined` while loading, then live-updates; pass `"skip"` instead of args to disable it (https://docs.convex.dev/client/react/overview).
- `useMutation(api.objects.update)` returns an async function.
- Env naming caveat: the CLI writes `VITE_CONVEX_URL` only if the `package.json` next to `convex/` depends on `vite`; otherwise it writes `CONVEX_URL` (section 2).
  With `convex/` at the repo root and the Vite app in `dashboard/`, either put the root `package.json` in charge of both, or have `dashboard/vite.config.ts` read the root `.env.local` with `loadEnv` and `define` only `CONVEX_URL` and `CONVEX_SITE_URL`.
  Do not widen Vite's `envPrefix` to `CONVEX_`, because that would also expose `CONVEX_DEPLOY_KEY` if one is ever added (my recommendation).
- The dashboard imports `../convex/_generated/api` for typed references.

### ESP32 (not needed)

- https://github.com/convex/convex-esp32 is alpha with "no guarantee of support" and requires Arduino-ESP32 core 3.2+ and ArduinoJson 7.
- It runs reactive queries, mutations, actions, and HTTP actions over a TLS WebSocket, with `convexBegin("https://<dep>.convex.cloud")` ("NOT .site").
- It validates TLS against the core's root CA bundle, so it targets cloud deployments; using it against a plain-HTTP local deployment is UNVERIFIED.
- Earmark's NFC board speaks serial to the hub, so skip it unless the team wants a device-side demo later.

## 10. Seeding with one command

Options, all observed except where noted:
- `npx convex run seed:reset`: the CLI can run internal functions, so make `reset` an `internalMutation`.
  A function can `import seed from "../config/objects.seed.json"` (bundling a JSON file from outside `convex/` worked, and typecheck passed).
  Alternatively pass the file as args: `npx convex run seed:load "$(cat config/objects.seed.json)"` worked, since the seed file's root is a JSON object.
- `npx convex dev --once --run seed:reset` pushes and then runs it in one step (https://docs.convex.dev/cli/reference/dev).
  It cannot be used while another `npx convex dev` is running.
- `npx convex import --table <t> --replace -y file.jsonl` imports one table per file and replaces it atomically (https://docs.convex.dev/database/import-export/import; beta).
  It cannot convert the snake_case seed file into camelCase tables or build relations, so it is a poor fit here.

Recommendation: one idempotent `internal.seed.reset` mutation that clears the Earmark tables, converts `config/objects.seed.json` to camelCase rows, and writes two days of history relative to `Date.now()` (allowed in a mutation), including one missed dose.
Expose it as `npm run seed` -> `npx convex run seed:reset`.

## 11. Hackathon resources

See `docs/sponsors/sponsor-packs/convex.md`.
In short: the prize is "Best use of Convex", $5,000 cash, with no published rubric.
The Convex workshop is Saturday 10/24, 4:00-5:00 PM PDT, at Gate 3, and was still upcoming when I checked.
Coupons are "sometimes" provided; there is no fixed credit amount.

## 12. Where the brief and the official materials differ

- Brief 5.C acceptance says "the schema deploys to a Convex dev deployment".
  Without a login, that is a local anonymous deployment, which is a dev deployment but has no public URL (section 2).
  Remote family labeling from a phone, Azure-hosted dashboard and agents, and any off-Mac caller need the human to log in and switch to cloud (or a tunnel).
- The brief and the team-lead task mention "interval/daily" crons.
  The guidelines restrict crons to `crons.interval` and `crons.cron`, so build the daily summary with `crons.cron`.
- The adherence rule ("missed after that") depends on the current time.
  The guidelines forbid `Date.now()` in queries, so dose status must be computed in the cron mutation or take `now` as an argument.
- The brief offers "Convex's Python client (or plain HTTPS to Convex HTTP actions if simpler)".
  Plain HTTPS is the better fit: the client can't call internal functions without the admin key, and its `subscribe` blocks other threads (section 9).
- The brief's 5.F photo flow implies the model sees the uploaded photo.
  On a local deployment, Anthropic cannot fetch a Convex file URL, so the action must send the bytes inline (section 6).
- The brief's 2.5 says to "install whatever rules or guideline files they provide".
  The official mechanism (`npx convex ai-files install`) also writes `CLAUDE.md`, `AGENTS.md`, and 66 skill directories into the repo.
  The home-page prompt additionally installs a user-scope plugin, which the human should approve.
- The brief calls the Saturday 4 pm session a workshop "on building agentic apps".
  The official title is "Build Your Backend with Convex", which includes a live demo of building with AI coding agents.
- The brief links `github.com/convex/convex-esp32`; the README's install line uses `github.com/get-convex/convex-esp32.git`.
  Both appear to be the same project (the GitHub API answered for `convex/convex-esp32`).
- The local machine's default Node (26.10.0) is not a supported Node-actions version (22 or 24).
  This only matters if someone adds `"use node"`; the CLI itself ran fine on Node 26 (observed).
- The docs say `convex dev` must be running for other CLI commands on a local deployment.
  In 1.48.0 `npx convex run` worked without it but `npx convex export` did not (observed); treat the docs' rule as the contract.
