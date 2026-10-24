/// <reference types="vite/client" />
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { api } from "./_generated/api";
import {
  examples,
  expectSchema,
  get,
  HUB,
  pickupEvent,
  post,
  READ,
  seed,
  setup,
  stateUpdate,
  type T,
} from "./test.helpers";

// Friday 2025-10-24 17:00 PDT, the "now" of the contract examples.
const NOW = 1761350400;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW * 1000);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

const READ_ROUTES = [
  "/api/registry",
  "/api/object?name=sugar",
  "/api/objects",
  "/api/history?objectId=sugar",
  "/api/adherence",
  "/api/daily-summary",
];

describe("auth", () => {
  let t: T;
  beforeEach(async () => {
    t = setup();
    await seed(t);
  });

  test.each(READ_ROUTES)("GET %s: hub and read secrets work, others get 401", async (path) => {
    for (const secret of [HUB, READ]) expect((await get(t, path, secret)).status).toBe(200);
    for (const secret of [null, "", "wrong", `${READ}x`, HUB.slice(0, -1)]) {
      const r = await get(t, path, secret);
      expect(r.status).toBe(401);
      expectSchema("error_response", r.body);
      expect(r.body.error).toBe("unauthorized");
    }
  });

  test.each([
    ["/ingest", { events: [], states: [] }],
    ["/api/label", { tag: "04AAAAAAAAAA01", name: "honey", aliases: [] }],
  ])("POST %s: only the hub secret works", async (path, body) => {
    expect((await post(t, path, body, HUB)).status).toBe(200);
    for (const secret of [null, READ, "wrong"]) {
      const r = await post(t, path, body, secret);
      expect(r.status).toBe(401);
      expectSchema("error_response", r.body);
    }
  });

  test("an unset secret never matches, even an empty header", async () => {
    vi.stubEnv("EARMARK_HUB_SECRET", "");
    vi.stubEnv("EARMARK_READ_SECRET", "");
    expect((await get(t, "/api/registry", "")).status).toBe(401);
    expect((await post(t, "/ingest", { events: [], states: [] }, "")).status).toBe(401);
  });
});

describe("POST /ingest", () => {
  let t: T;
  beforeEach(async () => {
    t = setup();
    await seed(t);
  });

  test("contract examples are accepted, then recognized as duplicates", async () => {
    for (const req of examples("ingest_request")) {
      expectSchema("ingest_request", req);
      const first = await post(t, "/ingest", req);
      expect(first.status).toBe(200);
      expectSchema("ingest_response", first.body);
      const n = (req as { events: unknown[] }).events.length;
      expect(first.body).toMatchObject({ ok: true, accepted_events: n, duplicate_events: 0 });
      const again = await post(t, "/ingest", req);
      expectSchema("ingest_response", again.body);
      expect(again.body).toMatchObject({ ok: true, accepted_events: 0, duplicate_events: n });
    }
  });

  test("duplicates inside one batch are counted once", async () => {
    const e = pickupEvent("salt", 2, NOW - 10);
    const r = await post(t, "/ingest", { events: [e, e], states: [] });
    expect(r.body).toMatchObject({ accepted_events: 1, duplicate_events: 1 });
  });

  test("states: the newest t wins and an older replay is ignored", async () => {
    const newer = stateUpdate("salt", NOW, { status: "held" });
    const older = stateUpdate("salt", NOW - 30, {
      status: "on_spot",
      precision: "exact",
      location: { spot: 2, position: [-0.16, 0.58, 0] },
    });
    expect((await post(t, "/ingest", { events: [], states: [newer] })).body.accepted_states).toBe(1);
    expect((await post(t, "/ingest", { events: [], states: [older] })).body.accepted_states).toBe(0);
    const map = await t.query(api.dashboard.liveMap, {});
    expect(map.states.find((s) => s.objectId === "salt")).toMatchObject({ status: "held", t: NOW });
  });

  test("a medication pickup re-materializes its dose immediately", async () => {
    // Today's 20:00 dose is pending at 17:00; a pickup at 19:45 (with the clock at 19:50) makes it taken.
    vi.setSystemTime((NOW + 170 * 60) * 1000);
    await post(t, "/ingest", { events: [pickupEvent("bp_meds", 4, NOW + 165 * 60, "e-evening-pills")], states: [] });
    const day = await t.query(api.doses.forDate, { date: "2025-10-24" });
    expect(day.doses.find((d) => d.scheduledLocalTime === "20:00")).toMatchObject({
      status: "taken",
      evidenceEventId: "e-evening-pills",
    });
  });

  test("trial_start then trial_end makes one trial; a second end never edits it", async () => {
    const start = { type: "trial_start", trial_id: "t-9", mode: "baseline", target_object_id: "salt", tester: "tester-B", t: NOW };
    const end = {
      type: "trial_end",
      trial_id: "t-9",
      mode: "baseline",
      target_object_id: "salt",
      tester: "tester-B",
      outcome: "found",
      started_t: NOW,
      seconds_to_find: 21.5,
      wrong_picks: 2,
      t: NOW + 21.5,
    };
    const ev = (kind: string, data: Record<string, unknown>, id: string) => ({ event_id: id, kind, object_id: "salt", t: data.t, data });
    await post(t, "/ingest", { events: [ev("trial_start", start, "e-trial-start")], states: [] });
    expect(await t.query(api.trials.list, {})).toMatchObject([{ trialId: "t-9", endedAt: null, outcome: null }]);
    await post(t, "/ingest", { events: [ev("trial_end", end, "e-trial-end")], states: [] });
    await post(t, "/ingest", {
      events: [ev("trial_end", { ...end, outcome: "aborted", wrong_picks: 9 }, "e-trial-end-2")],
      states: [],
    });
    expect(await t.query(api.trials.list, {})).toEqual([
      {
        trialId: "t-9",
        mode: "baseline",
        targetObjectId: "salt",
        tester: "tester-B",
        startedAt: NOW,
        endedAt: NOW + 21.5,
        secondsToFind: 21.5,
        wrongPicks: 2,
        outcome: "found",
      },
    ]);
  });

  test("unknown tags appear on the live map and clear when labeled or removed", async () => {
    const unknown = examples("hub_event")[1]; // unknown_tag 04A1B2C3D4E5FF on spot 1
    await post(t, "/ingest", { events: [unknown], states: [] });
    expect((await t.query(api.dashboard.liveMap, {})).unknownTags).toEqual([
      { tag: "04A1B2C3D4E5FF", spot: 1, t: 1761350400.12 },
    ]);
    const label = await post(t, "/api/label", examples("label_request")[0]);
    expect(label.body).toEqual({ ok: true, object_id: "honey", created: true });
    expect((await t.query(api.dashboard.liveMap, {})).unknownTags).toEqual([]);

    const other = { event_id: "e-unknown-2", kind: "unknown_tag", object_id: null, t: NOW, data: { type: "unknown_tag", tag: "04BBBBBBBBBB01", spot: 1, t: NOW } };
    await post(t, "/ingest", { events: [other], states: [] });
    expect((await t.query(api.dashboard.liveMap, {})).unknownTags).toHaveLength(1);
    const removed = { event_id: "e-removed-2", kind: "removed", object_id: null, t: NOW + 5, data: { spot: 1, tag: "04BBBBBBBBBB01", source: "nfc" } };
    await post(t, "/ingest", { events: [removed], states: [] });
    expect((await t.query(api.dashboard.liveMap, {})).unknownTags).toEqual([]);
  });

  test.each([
    ["not JSON", "{nope"],
    ["missing states", { events: [] }],
    ["extra top-level key", { events: [], states: [], extra: 1 }],
    ["bad kind", { events: [{ event_id: "e-12345678", kind: "teleport", object_id: null, t: NOW, data: {} }], states: [] }],
    ["short event_id", { events: [{ event_id: "e-1", kind: "chirp", object_id: "keys", t: NOW, data: {} }], states: [] }],
    ["pickup without from_spot", { events: [{ event_id: "e-12345678", kind: "pickup", object_id: "salt", t: NOW, data: {} }], states: [] }],
    ["data with a $ key", { events: [{ event_id: "e-12345678", kind: "chirp", object_id: "keys", t: NOW, data: { $x: 1 } }], states: [] }],
    ["bad trial_end", { events: [{ event_id: "e-12345678", kind: "trial_end", object_id: "salt", t: NOW, data: { type: "trial_end", trial_id: "t" } }], states: [] }],
    ["state with bad status", { events: [], states: [stateUpdate("salt", NOW, { status: "flying" })] }],
    ["state with a 2D position", { events: [], states: [stateUpdate("salt", NOW, { location: { spot: 2, position: [0, 1] } })] }],
    ["state missing source", { events: [], states: [(({ source: _s, ...rest }) => rest)(stateUpdate("salt", NOW))] }],
  ])("400 for %s, and nothing is written", async (_name, body) => {
    const before = await t.query(api.events.recent, { limit: 200 });
    const r = await post(t, "/ingest", body);
    expect(r.status).toBe(400);
    expectSchema("error_response", r.body);
    expect(await t.query(api.events.recent, { limit: 200 })).toEqual(before);
  });

  test("a batch is atomic: one bad event rejects the whole request", async () => {
    const good = pickupEvent("salt", 2, NOW - 5, "e-good-0001");
    const bad = { event_id: "e-bad-00001", kind: "pickup", object_id: null, t: NOW, data: { from_spot: 2 } };
    expect((await post(t, "/ingest", { events: [good, bad], states: [] })).status).toBe(400);
    expect((await post(t, "/ingest", { events: [good], states: [] })).body.accepted_events).toBe(1);
  });
});

describe("POST /api/label", () => {
  test("creates, renames (keeping aliases), and bumps the registry version", async () => {
    const t = setup();
    await seed(t);
    const v0 = (await get(t, "/api/registry")).body.version as number;

    vi.setSystemTime((NOW + 1) * 1000);
    const created = await post(t, "/api/label", examples("label_request")[0]);
    expectSchema("label_response", created.body);
    expect(created.body).toEqual({ ok: true, object_id: "honey", created: true });
    const reg1 = (await get(t, "/api/registry")).body;
    expect(reg1.version).toBeGreaterThan(v0);
    expect(reg1.objects.find((o: { object_id: string }) => o.object_id === "honey")).toMatchObject({
      tag: "04A1B2C3D4E5FF",
      home_spot: 1,
    });

    const renamed = await post(t, "/api/label", examples("label_request")[1]);
    expectSchema("label_response", renamed.body);
    expect(renamed.body).toEqual({ ok: true, object_id: "sugar", created: false });
    const reg2 = (await get(t, "/api/registry")).body;
    expect(reg2.version).toBeGreaterThan(reg1.version);
    expect(reg2.objects.find((o: { object_id: string }) => o.object_id === "sugar").aliases).toEqual([
      "white sugar",
      "sweetener",
      "cane sugar",
    ]);

    // Same name as an existing object: a new, distinct objectId.
    const twin = await post(t, "/api/label", { tag: "04CCCCCCCCCC01", name: "honey", aliases: [] });
    expect(twin.body).toEqual({ ok: true, object_id: "honey_2", created: true });
  });

  test.each([
    ["missing name", { tag: "04AA", aliases: [] }],
    ["blank name", { tag: "04AA", name: "  ", aliases: [] }],
    ["aliases not strings", { tag: "04AA", name: "x", aliases: [1] }],
    ["spot not an integer", { tag: "04AA", name: "x", aliases: [], spot: 1.5 }],
    ["empty tag", { tag: " ", name: "x", aliases: [] }],
  ])("400 for %s", async (_name, body) => {
    const t = setup();
    const r = await post(t, "/api/label", body);
    expect(r.status).toBe(400);
    expectSchema("error_response", r.body);
  });
});

describe("GET /api/registry", () => {
  test("matches registry.schema.json and changes version on every registry edit", async () => {
    const t = setup();
    expect((await get(t, "/api/registry")).body).toMatchObject({ objects: [], medications: [], version: null });
    await seed(t);
    const r0 = await get(t, "/api/registry");
    expectSchema("registry.schema.json", r0.body);
    expect(r0.body.household).toEqual({ name: "Demo household", timezone: "America/Los_Angeles" });
    expect(r0.body.objects.map((o: { object_id: string }) => o.object_id)).toEqual(["bp_meds", "keys", "pepper", "salt", "sugar"]);
    expect(r0.body.medications).toEqual([{ object_id: "bp_meds", schedule_times: ["08:00", "20:00"], window_minutes: 60 }]);

    let last = r0.body.version as number;
    const edits = [
      () => t.mutation(api.objects.update, { objectId: "pepper", notes: "On the spice rack." }),
      () => t.mutation(api.medications.upsert, { objectId: "bp_meds", scheduleTimes: ["08:00", "21:00"], windowMinutes: 45 }),
      () => t.mutation(api.objects.remove, { objectId: "pepper" }),
    ];
    for (const edit of edits) {
      await edit(); // same fake millisecond: the version must still move forward
      const r = await get(t, "/api/registry");
      expectSchema("registry.schema.json", r.body);
      expect(r.body.version).toBeGreaterThan(last);
      last = r.body.version;
    }
  });
});

describe("agent read endpoints", () => {
  let t: T;
  beforeEach(async () => {
    t = setup();
    await seed(t);
  });

  test("GET /api/object matches name, alias, and substring, best first", async () => {
    const sugar = await get(t, "/api/object?name=Sugar");
    expectSchema("object_lookup_response", sugar.body);
    expect(sugar.body.matches[0]).toMatchObject({
      object_id: "sugar",
      home_spot: 3,
      home_spot_label: "center right",
      state: { status: "on_spot", spot: 3, spot_label: "center right", precision: "exact" },
    });
    expect(sugar.body.now_t).toBe(NOW);
    expect(sugar.body.now_local).toBe("2025-10-24T17:00:00-07:00");

    const pills = await get(t, "/api/object?name=evening%20pills");
    expect(pills.body.matches.map((m: { object_id: string }) => m.object_id)).toEqual(["bp_meds"]);
    const both = await get(t, "/api/object?name=salt%20and%20pepper");
    expect(both.body.matches.map((m: { object_id: string }) => m.object_id).sort()).toEqual(["pepper", "salt"]);
    const none = await get(t, "/api/object?name=unicorn");
    expectSchema("object_lookup_response", none.body);
    expect(none.body.matches).toEqual([]);
    const missing = await get(t, "/api/object");
    expect(missing.status).toBe(400);
    expectSchema("error_response", missing.body);
  });

  test("GET /api/objects lists every object with state and last touch", async () => {
    const r = await get(t, "/api/objects");
    expectSchema("objects_response", r.body);
    const by = Object.fromEntries(r.body.objects.map((o: { object_id: string }) => [o.object_id, o]));
    expect(by.pepper).toMatchObject({ state: null, last_touched_t: null, home_spot_label: null });
    expect(by.keys.state).toMatchObject({ status: "roaming", near: "hub", precision: "proximity" });
    // Salt was last put back after the 12:31 lunch pickup today (the 18:44 one is after 17:00).
    expect(by.salt.last_touched_local).toBe("2025-10-24T12:33:00-07:00");
  });

  test("GET /api/history is newest first with deterministic sentences", async () => {
    const r = await get(t, "/api/history?objectId=sugar");
    expectSchema("history_response", r.body);
    expect(r.body.since_t).toBe(NOW - 7 * 86400);
    const ts = r.body.events.map((e: { t: number }) => e.t);
    expect([...ts].sort((a, b) => b - a)).toEqual(ts);
    expect(r.body.events[0]).toMatchObject({ kind: "placed", spot: 3, detail: "Put down on the center right spot." });
    const moved = r.body.events.find((e: { at_local: string }) => e.at_local === "2025-10-23T19:22:00-07:00");
    expect(moved).toMatchObject({ kind: "placed", spot: 1, spot_label: "far left", detail: "Put down on the far left spot." });

    const since = await get(t, `/api/history?objectId=sugar&since=${NOW - 3600 * 3}`);
    expect(since.body.events.every((e: { t: number }) => e.t >= NOW - 3600 * 3)).toBe(true);
    expect(since.body.events.length).toBeGreaterThan(0);

    for (const [path, status] of [
      ["/api/history", 400],
      ["/api/history?objectId=sugar&since=yesterday", 400],
      ["/api/history?objectId=unicorn", 404],
    ] as const) {
      const bad = await get(t, path);
      expect(bad.status).toBe(status);
      expectSchema("error_response", bad.body);
    }
  });

  test("GET /api/adherence reports yesterday's missed evening dose", async () => {
    const r = await get(t, "/api/adherence?date=2025-10-23");
    expectSchema("adherence_response", r.body);
    expect(r.body.doses).toEqual([
      expect.objectContaining({ scheduled_local_time: "08:00", status: "taken", taken_local: "2025-10-23T07:52:00-07:00" }),
      {
        object_id: "bp_meds",
        name: "blood pressure pills",
        scheduled_local_time: "20:00",
        scheduled_for_t: 1761274800,
        scheduled_for_local: "2025-10-23T20:00:00-07:00",
        status: "missed",
        taken_t: null,
        taken_local: null,
        evidence_event_id: null,
      },
    ]);
    const today = await get(t, "/api/adherence");
    expectSchema("adherence_response", today.body);
    expect(today.body.date).toBe("2025-10-24");
    expect(today.body.doses.map((d: { status: string }) => d.status)).toEqual(["taken", "pending"]);
    for (const bad of ["2025-02-30", "10/23/2025", "yesterday"]) {
      const res = await get(t, `/api/adherence?date=${bad}`);
      expect(res.status).toBe(400);
      expectSchema("error_response", res.body);
    }
    // Before monitoring started: no fabricated doses.
    expect((await get(t, "/api/adherence?date=2025-10-01")).body.doses).toEqual([]);
  });

  test("GET /api/daily-summary is deterministic text from the data", async () => {
    const y = await get(t, "/api/daily-summary?date=2025-10-23");
    expectSchema("daily_summary_response", y.body);
    expect(y.body).toMatchObject({ date: "2025-10-23", pickup_count: 8, untouched_7d: ["pepper"], missing: [] });
    expect(y.body.text).toBe(
      "On Thursday, October 23: the 08:00 blood pressure pills dose was taken at 07:52. " +
        "The 20:00 dose was missed (no pickup between 19:00 and 22:00). 8 pickups recorded. " +
        "Not touched in 7 days: pepper.",
    );
    const today = await get(t, "/api/daily-summary");
    expectSchema("daily_summary_response", today.body);
    expect(today.body.date).toBe("2025-10-24");
    expect(today.body.text).toContain("The 20:00 dose is pending.");
  });
});
