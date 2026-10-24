/// <reference types="vite/client" />
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { fn } from "../contracts/ts/convexFunctions";
import { internal } from "./_generated/api";
import { pickupEvent, post, seed, setup, stateUpdate, type T } from "./test.helpers";

// Every call below goes through the dashboard's contract references (fn.*), by name.
const NOW = 1761350400; // 2025-10-24 17:00 PDT

let t: T;
beforeEach(async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW * 1000);
  t = setup();
  await seed(t);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

const fields = {
  name: "Honey",
  aliases: ["honey jar", " honey "],
  notes: "For tea.",
  description: "Squeeze bottle.",
  tag: "04aabbccddee01",
  homeSpot: 1,
  isMedication: false,
  fobId: null,
};

describe("dashboard:liveMap", () => {
  test("returns the seeded household, space, registry, and states", async () => {
    const map = await t.query(fn.dashboard.liveMap, {});
    expect(map.household).toEqual({ name: "Demo household", timezone: "America/Los_Angeles" });
    expect(map.spots.map((s) => [s.spot, s.label])).toEqual([
      [1, "far left"],
      [2, "center left"],
      [3, "center right"],
      [4, "far right"],
    ]);
    expect(map.areas.map((a) => a.area).sort()).toEqual(["bag", "box", "cupboard", "drawer", "kitchen_counter"]);
    expect(map.areas.find((a) => a.area === "kitchen_counter")).toEqual({
      area: "kitchen_counter",
      label: "the counter",
      position: [0, 0.6, 0],
    });
    expect(map.objects.map((o) => o.objectId).sort()).toEqual(["bp_meds", "keys", "pepper", "salt", "sugar"]);
    expect(map.states.map((s) => s.objectId).sort()).toEqual(["bp_meds", "keys", "salt", "sugar"]);
    expect(map.states.find((s) => s.objectId === "sugar")).toEqual({
      objectId: "sugar",
      status: "on_spot",
      spot: 3,
      position: [0.16, 0.58, 0],
      area: null,
      near: null,
      distanceClass: null,
      precision: "exact",
      homeSpot: 3,
      lastSeenT: NOW,
      t: NOW,
    });
    expect(map.unknownTags).toEqual([]);
  });

  test("reflects /ingest as soon as it commits (the query the dashboard subscribes to)", async () => {
    await post(t, "/ingest", {
      events: [pickupEvent("salt", 2, NOW + 1)],
      states: [stateUpdate("salt", NOW + 1, { home_spot: 2 })],
    });
    const map = await t.query(fn.dashboard.liveMap, {});
    expect(map.states.find((s) => s.objectId === "salt")).toMatchObject({ status: "held", spot: null, t: NOW + 1 });
  });
});

describe("objects", () => {
  test("create derives and dedupes objectId, normalizes fields, returns the id", async () => {
    expect(await t.mutation(fn.objects.create, fields)).toBe("honey");
    const honey = (await t.query(fn.objects.list, {})).find((o) => o.objectId === "honey");
    expect(honey).toMatchObject({ name: "Honey", aliases: ["honey jar"], tag: "04AABBCCDDEE01", homeSpot: 1 });
    expect(await t.mutation(fn.objects.create, { ...fields, tag: null })).toBe("honey_2");
    expect(await t.mutation(fn.objects.create, { ...fields, tag: null, objectId: "manuka" })).toBe("manuka");
  });

  test("create rejects bad input with readable errors", async () => {
    await expect(t.mutation(fn.objects.create, { ...fields, name: "  " })).rejects.toThrow(/Name cannot be empty/);
    await expect(t.mutation(fn.objects.create, { ...fields, tag: "04A1B2C3D4E502" })).rejects.toThrow(
      /already belongs to sugar/,
    );
    await expect(t.mutation(fn.objects.create, { ...fields, objectId: "salt" })).rejects.toThrow(/already exists/);
    await expect(t.mutation(fn.objects.create, { ...fields, objectId: "Bad Id" })).rejects.toThrow(/objectId may only/);
    await expect(t.mutation(fn.objects.create, { ...fields, homeSpot: 1.5 })).rejects.toThrow(/Home spot/);
  });

  test("update patches only the given fields and bumps updatedAt", async () => {
    const before = (await t.query(fn.objects.list, {})).find((o) => o.objectId === "pepper")!;
    expect(await t.mutation(fn.objects.update, { objectId: "pepper", homeSpot: 1, notes: "Moved to the counter." })).toBeNull();
    const after = (await t.query(fn.objects.list, {})).find((o) => o.objectId === "pepper")!;
    expect(after).toEqual({ ...before, homeSpot: 1, notes: "Moved to the counter.", updatedAt: after.updatedAt });
    expect(after.updatedAt).toBeGreaterThan(before.updatedAt);
    await expect(t.mutation(fn.objects.update, { objectId: "unicorn", name: "x" })).rejects.toThrow(/Unknown objectId/);
  });

  test("turning off isMedication removes the schedule and its doses", async () => {
    await t.mutation(fn.objects.update, { objectId: "bp_meds", isMedication: false });
    expect(await t.query(fn.medications.list, {})).toEqual([]);
    expect((await t.query(fn.doses.forDate, { date: "2025-10-23" })).doses).toEqual([]);
  });

  test("remove deletes the object, its state, schedule and doses, but keeps events", async () => {
    expect(await t.mutation(fn.objects.remove, { objectId: "bp_meds" })).toBeNull();
    const map = await t.query(fn.dashboard.liveMap, {});
    expect(map.objects.find((o) => o.objectId === "bp_meds")).toBeUndefined();
    expect(map.states.find((s) => s.objectId === "bp_meds")).toBeUndefined();
    expect(await t.query(fn.medications.list, {})).toEqual([]);
    expect((await t.query(fn.doses.forDate, { date: "2025-10-23" })).doses).toEqual([]);
    const events = await t.query(fn.events.recent, { limit: 200 });
    expect(events.some((e) => e.objectId === "bp_meds")).toBe(true);
    await expect(t.mutation(fn.objects.remove, { objectId: "bp_meds" })).rejects.toThrow(/Unknown objectId/);
  });
});

describe("events:recent", () => {
  test("newest first, bounded, with sentences that name the object", async () => {
    const recent = await t.query(fn.events.recent, { limit: 3 });
    expect(recent).toHaveLength(3);
    expect(recent[0]).toMatchObject({ kind: "placed", objectId: "sugar", spot: 3, detail: "Sugar put down on the center right spot." });
    expect(recent[1]).toMatchObject({ kind: "pickup", objectId: "sugar", detail: "Sugar picked up from the center right spot." });
    const chirps = Array.from({ length: 10 }, (_, i) => ({
      event_id: `e-chirp-${i}-0000`,
      kind: "chirp",
      object_id: "keys",
      t: NOW + i,
      data: { type: "chirp", fob_id: "fob_keys", action: "start", t: NOW + i },
    }));
    await post(t, "/ingest", { events: chirps, states: [] });
    expect((await t.query(fn.events.recent, {})).length).toBe(50); // default limit; 54 exist
    expect((await t.query(fn.events.recent, { limit: 10_000 })).length).toBeLessThanOrEqual(200);
    const chirp = (await t.query(fn.events.recent, { limit: 200 })).find((e) => e.kind === "chirp");
    expect(chirp?.detail).toMatch(/^The keys fob (was asked to chirp|stopped chirping)\.$/);
  });
});

describe("medications and doses", () => {
  test("list joins names; upsert validates, sorts, and recomputes", async () => {
    expect(await t.query(fn.medications.list, {})).toEqual([
      { objectId: "bp_meds", name: "blood pressure pills", scheduleTimes: ["08:00", "20:00"], windowMinutes: 60 },
    ]);
    await expect(
      t.mutation(fn.medications.upsert, { objectId: "bp_meds", scheduleTimes: ["8am"], windowMinutes: 60 }),
    ).rejects.toThrow(/HH:MM/);
    await expect(
      t.mutation(fn.medications.upsert, { objectId: "bp_meds", scheduleTimes: ["08:00"], windowMinutes: 0 }),
    ).rejects.toThrow(/Window/);
    await expect(
      t.mutation(fn.medications.upsert, { objectId: "nope", scheduleTimes: ["08:00"], windowMinutes: 60 }),
    ).rejects.toThrow(/Unknown objectId/);

    // Narrow the window to 10 minutes: today's 08:15 pickup becomes late.
    await t.mutation(fn.medications.upsert, { objectId: "bp_meds", scheduleTimes: ["20:00", "08:00"], windowMinutes: 10 });
    const today = await t.query(fn.doses.forDate, { date: "2025-10-24" });
    expect(today).toEqual({
      date: "2025-10-24",
      timezone: "America/Los_Angeles",
      doses: [
        {
          objectId: "bp_meds",
          name: "blood pressure pills",
          scheduledLocalTime: "08:00",
          scheduledForT: 1761318000,
          status: "late",
          takenT: 1761318900,
          evidenceEventId: "seed-2025-10-24-0815-bp_meds-pickup",
        },
        {
          objectId: "bp_meds",
          name: "blood pressure pills",
          scheduledLocalTime: "20:00",
          scheduledForT: 1761361200,
          status: "pending",
          takenT: null,
          evidenceEventId: null,
        },
      ],
    });
  });

  test("upsert on a non-medication marks it as one; its schedule starts now", async () => {
    await t.mutation(fn.medications.upsert, { objectId: "pepper", scheduleTimes: ["09:00", "18:00"], windowMinutes: 30 });
    expect((await t.query(fn.objects.list, {})).find((o) => o.objectId === "pepper")?.isMedication).toBe(true);
    const doses = (await t.query(fn.doses.forDate, { date: "2025-10-24" })).doses.filter((d) => d.objectId === "pepper");
    expect(doses.map((d) => d.scheduledLocalTime)).toEqual(["18:00"]);
    expect(doses[0].status).toBe("pending");
  });

  test("forDate rejects a malformed date", async () => {
    await expect(t.query(fn.doses.forDate, { date: "2025-13-01" })).rejects.toThrow(/YYYY-MM-DD/);
  });

  test("the minute cron flips pending to missed once S + 2W passes", async () => {
    vi.setSystemTime((NOW + 5 * 3600 + 60) * 1000); // 22:01
    await t.mutation(internal.doses.recomputeRecent, {});
    const pm = (await t.query(fn.doses.forDate, { date: "2025-10-24" })).doses.find((d) => d.scheduledLocalTime === "20:00");
    // The seed's 20:06 pickup is only written when the seed runs after it; here the seed ran at 17:00.
    expect(pm?.status).toBe("missed");
  });
});

describe("trials", () => {
  async function trial(id: string, mode: "earmark" | "baseline", tester: string, outcome: string | null, secs: number | null, wrong: number) {
    const start = { type: "trial_start", trial_id: id, mode, target_object_id: "sugar", tester, t: NOW };
    const events: unknown[] = [{ event_id: `e-${id}-start`, kind: "trial_start", object_id: "sugar", t: NOW, data: start }];
    if (outcome !== null) {
      const end = { ...start, type: "trial_end", outcome, started_t: NOW, seconds_to_find: secs, wrong_picks: wrong, t: NOW + 30 };
      events.push({ event_id: `e-${id}-end`, kind: "trial_end", object_id: "sugar", t: NOW + 30, data: end });
    }
    expect((await post(t, "/ingest", { events, states: [] })).status).toBe(200);
  }

  test("summary reports raw counts over completed trials only", async () => {
    await trial("t-1", "earmark", "tester-A", "found", 6, 0);
    await trial("t-2", "earmark", "tester-B", "found", 10, 1);
    await trial("t-3", "earmark", "tester-A", "gave_up", null, 2);
    await trial("t-4", "baseline", "tester-A", "found", 41, 3);
    await trial("t-5", "baseline", "tester-B", null, null, 0); // still running
    expect(await t.query(fn.trials.summary, {})).toEqual({
      earmark: { trials: 3, found: 2, testers: 2, medianSecondsToFind: 8, wrongPicks: 3 },
      baseline: { trials: 1, found: 1, testers: 1, medianSecondsToFind: 41, wrongPicks: 3 },
    });
    const list = await t.query(fn.trials.list, {});
    expect(list).toHaveLength(5);
    expect(list.find((r) => r.trialId === "t-5")).toMatchObject({ endedAt: null, outcome: null, wrongPicks: 0 });
  });

  test("empty summary", async () => {
    const empty = { trials: 0, found: 0, testers: 0, medianSecondsToFind: null, wrongPicks: 0 };
    expect(await t.query(fn.trials.summary, {})).toEqual({ earmark: empty, baseline: empty });
  });
});

describe("labeling:generateUploadUrl", () => {
  test("returns an upload URL", async () => {
    expect(typeof (await t.mutation(fn.labeling.generateUploadUrl, {}))).toBe("string");
  });
});
