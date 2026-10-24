/**
 * HTTP actions for the hub and agents, exactly per contracts/schemas/convex_http.schema.json.
 * snake_case on the wire; conversion happens here (via lib/wire.ts) and nowhere else.
 * Auth: header X-Earmark-Secret. EARMARK_HUB_SECRET works on every route,
 * EARMARK_READ_SECRET only on GET /api/*.
 */
import { httpRouter } from "convex/server";
import { internal } from "./_generated/api";
import { env, httpAction, type ActionCtx } from "./_generated/server";
import { isAuthorized } from "./lib/auth";
import { formatLocalIso, isValidDate } from "./lib/time";
import {
  BadRequest,
  doseToWire,
  historyEventToWire,
  objectSummaryToWire,
  parseDateParam,
  parseIngestRequest,
  parseLabelRequest,
  parseNumberParam,
  registryToWire,
  summaryToWire,
} from "./lib/wire";

const HISTORY_DEFAULT_S = 7 * 86_400;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

const errorResponse = (status: number, error: string) => json(status, { ok: false, error });

type Handler = (ctx: ActionCtx, req: Request, now: number) => Promise<Response>;

/** Auth, then the handler; a BadRequest anywhere becomes 400 with an error_response body. */
function route(readRoute: boolean, handler: Handler) {
  return httpAction(async (ctx, req) => {
    const ok = await isAuthorized(
      req.headers.get("x-earmark-secret"),
      { hub: env.EARMARK_HUB_SECRET, read: env.EARMARK_READ_SECRET },
      readRoute,
    );
    if (!ok) return errorResponse(401, "unauthorized");
    try {
      return await handler(ctx, req, Date.now() / 1000);
    } catch (err) {
      if (err instanceof BadRequest) return errorResponse(400, err.message);
      console.error("http handler failed", err instanceof Error ? err.message : String(err));
      return errorResponse(500, "internal error");
    }
  });
}

async function readJson(req: Request): Promise<unknown> {
  try {
    return await req.json();
  } catch {
    throw new BadRequest("body must be valid JSON");
  }
}

const params = (req: Request) => new URL(req.url).searchParams;

const http = httpRouter();

http.route({
  path: "/ingest",
  method: "POST",
  handler: route(false, async (ctx, req) => {
    const { events, states } = parseIngestRequest(await readJson(req));
    const r = await ctx.runMutation(internal.ingest.apply, { events, states });
    return json(200, {
      ok: true,
      accepted_events: r.acceptedEvents,
      duplicate_events: r.duplicateEvents,
      accepted_states: r.acceptedStates,
    });
  }),
});

http.route({
  path: "/api/label",
  method: "POST",
  handler: route(false, async (ctx, req) => {
    const body = parseLabelRequest(await readJson(req));
    const r = await ctx.runMutation(internal.registry.label, body);
    return json(200, { ok: true, object_id: r.objectId, created: r.created });
  }),
});

http.route({
  path: "/api/registry",
  method: "GET",
  handler: route(true, async (ctx) => json(200, registryToWire(await ctx.runQuery(internal.registry.get, {})))),
});

http.route({
  path: "/api/object",
  method: "GET",
  handler: route(true, async (ctx, req, now) => {
    const name = params(req).get("name");
    if (name === null || name.trim() === "") throw new BadRequest("name is required");
    const r = await ctx.runQuery(internal.reads.objectSummaries, { name });
    return json(200, {
      query: name,
      matches: r.objects.map((o) => objectSummaryToWire(o, r.timezone)),
      now_t: now,
      now_local: formatLocalIso(now, r.timezone),
    });
  }),
});

http.route({
  path: "/api/objects",
  method: "GET",
  handler: route(true, async (ctx, _req, now) => {
    const r = await ctx.runQuery(internal.reads.objectSummaries, {});
    return json(200, {
      objects: r.objects.map((o) => objectSummaryToWire(o, r.timezone)),
      now_t: now,
      now_local: formatLocalIso(now, r.timezone),
    });
  }),
});

http.route({
  path: "/api/history",
  method: "GET",
  handler: route(true, async (ctx, req, now) => {
    const p = params(req);
    const objectId = p.get("objectId");
    if (objectId === null || objectId === "") throw new BadRequest("objectId is required");
    const since = parseNumberParam(p.get("since"), "since") ?? now - HISTORY_DEFAULT_S;
    const r = await ctx.runQuery(internal.reads.history, { objectId, since });
    if (r === null) return errorResponse(404, "unknown objectId");
    return json(200, {
      object_id: r.objectId,
      name: r.name,
      since_t: since,
      events: r.events.map((e) => historyEventToWire(e, r.timezone)),
    });
  }),
});

http.route({
  path: "/api/adherence",
  method: "GET",
  handler: route(true, async (ctx, req, now) => {
    const date = parseDateParam(params(req).get("date"), isValidDate);
    const r = await ctx.runMutation(internal.doses.refreshDate, { date, now });
    return json(200, {
      date: r.date,
      timezone: r.timezone,
      doses: r.doses.map((d) => doseToWire(d, r.timezone)),
      now_t: now,
    });
  }),
});

http.route({
  path: "/api/daily-summary",
  method: "GET",
  handler: route(true, async (ctx, req, now) => {
    const date = parseDateParam(params(req).get("date"), isValidDate);
    return json(200, summaryToWire(await ctx.runMutation(internal.summaries.getOrBuild, { date, now })));
  }),
});

export default http;
