/// <reference types="vite/client" />
import { afterEach, describe, expect, test, vi } from "vitest";
import { api, internal } from "./_generated/api";
import { formatLocalIso, zonedToUnix } from "./lib/time";
import { pickupEvent, post, seed, seedArgs, setup, type T } from "./test.helpers";

const LA = "America/Los_Angeles";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

function at(date: string, hhmm: string) {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(zonedToUnix(date, hhmm, LA) * 1000);
}

async function allDoses(t: T) {
  return await t.run(async (ctx) => await ctx.db.query("doses").collect());
}

describe("seed", () => {
  // Times of day around every dose boundary, plus both DST transitions and a month boundary.
  const moments: [string, string][] = [
    ["2025-10-24", "00:30"],
    ["2025-10-24", "07:59"],
    ["2025-10-24", "08:16"],
    ["2025-10-24", "10:01"],
    ["2025-10-24", "17:00"],
    ["2025-10-24", "20:03"],
    ["2025-10-24", "22:30"],
    ["2025-10-24", "23:59"],
    ["2025-03-10", "09:00"], // day after spring forward
    ["2025-11-03", "21:00"], // day after fall back
    ["2026-03-01", "12:00"],
  ];

  test.each(moments)("at %s %s: exactly one missed dose, yesterday at 20:00", async (date, hhmm) => {
    at(date, hhmm);
    const t = setup();
    const result = await seed(t);
    expect(result.doses.missed).toBe(1);
    expect(result.doses.late).toBe(0);
    const missed = (await allDoses(t)).filter((d) => d.status === "missed");
    expect(missed).toHaveLength(1);
    expect(missed[0].scheduledLocalTime).toBe("20:00");
    expect(formatLocalIso(missed[0].scheduledFor, LA).slice(11, 16)).toBe("20:00");
    // Two full days of history: the doses two days ago and yesterday all exist.
    expect(result.doses.taken + result.doses.missed + result.doses.pending).toBeGreaterThanOrEqual(4);
  });

  test("idempotent: a second seed adds no history and keeps live state", async () => {
    at("2025-10-24", "17:00");
    const t = setup();
    const first = await seed(t);
    expect(first.historyEvents).toBe(44);
    await post(t, "/ingest", { events: [pickupEvent("salt", 2, zonedToUnix("2025-10-24", "17:00", LA))], states: [] });
    const before = await t.run(async (ctx) => ({
      events: (await ctx.db.query("events").collect()).length,
      states: await ctx.db.query("objectState").collect(),
      doses: await ctx.db.query("doses").collect(),
    }));
    const second = await seed(t);
    expect(second.historyEvents).toBe(0);
    const after = await t.run(async (ctx) => ({
      events: (await ctx.db.query("events").collect()).length,
      states: await ctx.db.query("objectState").collect(),
      doses: await ctx.db.query("doses").collect(),
      households: (await ctx.db.query("household").collect()).length,
      spots: (await ctx.db.query("spots").collect()).length,
    }));
    expect(after.events).toBe(before.events);
    expect(after.states).toEqual(before.states);
    expect(after.doses).toEqual(before.doses);
    expect(after.households).toBe(1);
    expect(after.spots).toBe(4);
  });

  test("all objects end on their home spots and history is consistent", async () => {
    at("2025-10-24", "17:00");
    const t = setup();
    await seed(t);
    const map = await t.query(api.dashboard.liveMap, {});
    for (const id of ["salt", "sugar", "bp_meds"]) {
      const o = map.objects.find((x) => x.objectId === id)!;
      expect(map.states.find((s) => s.objectId === id)).toMatchObject({ status: "on_spot", spot: o.homeSpot });
    }
  });
});

describe("reset", () => {
  test("restores the demo state, never touching trials", async () => {
    at("2025-10-24", "17:00");
    const t = setup();
    await seed(t);
    const now = zonedToUnix("2025-10-24", "17:00", LA);
    const start = { type: "trial_start", trial_id: "t-real", mode: "earmark", target_object_id: "sugar", tester: "tester-A", t: now };
    const end = { ...start, type: "trial_end", outcome: "found", started_t: now, seconds_to_find: 7.4, wrong_picks: 1, t: now + 7.4 };
    await post(t, "/ingest", {
      events: [
        { event_id: "e-real-start", kind: "trial_start", object_id: "sugar", t: now, data: start },
        pickupEvent("salt", 2, now + 3),
        { event_id: "e-real-end", kind: "trial_end", object_id: "sugar", t: now + 7.4, data: end },
      ],
      states: [],
    });
    await post(t, "/api/label", { tag: "04DDDDDDDDDD01", name: "honey", aliases: [] });
    await t.mutation(api.objects.update, { objectId: "salt", name: "sea salt" });
    const trialsBefore = await t.run(async (ctx) => await ctx.db.query("trials").collect());
    expect(trialsBefore).toHaveLength(1);

    vi.setSystemTime((now + 60) * 1000);
    const result = await t.action(internal.seed.reset, seedArgs());
    expect(result.seeded.doses.missed).toBe(1);

    const trialsAfter = await t.run(async (ctx) => await ctx.db.query("trials").collect());
    expect(trialsAfter).toEqual(trialsBefore); // same _id, _creationTime, and every field

    const objects = await t.query(api.objects.list, {});
    expect(objects.map((o) => o.objectId).sort()).toEqual(["bp_meds", "keys", "pepper", "salt", "sugar"]);
    expect(objects.find((o) => o.objectId === "salt")?.name).toBe("salt");

    const events = await t.run(async (ctx) => await ctx.db.query("events").collect());
    expect(events.filter((e) => e.kind.startsWith("trial_")).map((e) => e.eventId).sort()).toEqual([
      "e-real-end",
      "e-real-start",
    ]);
    expect(events.filter((e) => !e.kind.startsWith("trial_")).every((e) => e.eventId.startsWith("seed-"))).toBe(true);

    // Idempotent.
    const again = await t.action(internal.seed.reset, seedArgs());
    expect(again.seeded).toEqual(result.seeded);
    expect(await t.run(async (ctx) => await ctx.db.query("trials").collect())).toEqual(trialsBefore);
  });
});
