import { describe, expect, test } from "vitest";
import { computeAdherence, type Pickup, type ScheduledDose } from "./adherence";
import { zonedToUnix } from "./time";

const M = 60;
const S = 1_000_000; // a scheduled time
const W = 60; // window, minutes
const one = (pickups: Pickup[], now: number) => computeAdherence([{ key: "d", scheduledFor: S }], pickups, W, now)[0];
const p = (offsetMin: number, id = `e${offsetMin}`): Pickup => ({ eventId: id, t: S + offsetMin * M });

describe("single dose boundaries", () => {
  test("taken within +-W, inclusive", () => {
    for (const off of [-60, -59, 0, 30, 60]) {
      const r = one([p(off)], S + 10_000 * M);
      expect(r.status, `offset ${off}`).toBe("taken");
      expect(r.takenT).toBe(S + off * M);
      expect(r.evidenceEventId).toBe(`e${off}`);
    }
  });
  test("late in (W, 2W], inclusive of 2W", () => {
    for (const off of [61, 90, 120]) {
      const r = one([p(off)], S + 10_000 * M);
      expect(r.status, `offset ${off}`).toBe("late");
      expect(r.takenT).toBe(S + off * M);
    }
  });
  test("an early pickup beyond W does not count", () => {
    const r = one([p(-61)], S + 200 * M);
    expect(r).toMatchObject({ status: "missed", takenT: null, evidenceEventId: null });
  });
  test("a pickup after 2W does not count", () => {
    expect(one([p(121)], S + 200 * M).status).toBe("missed");
  });
  test("pending until S + 2W, missed after", () => {
    expect(one([], S - 600 * M).status).toBe("pending");
    expect(one([], S + 120 * M).status).toBe("pending");
    expect(one([], S + 120 * M + 1).status).toBe("missed");
  });
  test("a late pickup decides the dose even before 2W has passed", () => {
    expect(one([p(70)], S + 80 * M).status).toBe("late");
  });
});

describe("multiple pickups", () => {
  test("taken beats late, and the earliest qualifying pickup is the evidence", () => {
    const r = one([p(90, "late"), p(20, "b"), p(-10, "a")], S + 1000 * M);
    expect(r).toMatchObject({ status: "taken", evidenceEventId: "a", takenT: S - 10 * M });
  });
  test("several late pickups: the earliest is the evidence", () => {
    expect(one([p(100, "y"), p(70, "x")], S + 1000 * M)).toMatchObject({ status: "late", evidenceEventId: "x" });
  });
  test("order of input does not matter", () => {
    const ps = [p(5, "a"), p(40, "b"), p(-30, "c")];
    expect(one(ps, S + 1000 * M)).toEqual(one([...ps].reverse(), S + 1000 * M));
  });
});

describe("each pickup is evidence for at most one dose (the nearest)", () => {
  const doses: ScheduledDose[] = [
    { key: "08", scheduledFor: S },
    { key: "09", scheduledFor: S + 60 * M },
  ];
  test("one pickup between two close doses counts only for the nearer", () => {
    const r = computeAdherence(doses, [p(40)], W, S + 1000 * M);
    expect(r.map((d) => d.status)).toEqual(["missed", "taken"]);
  });
  test("two pickups cover two doses", () => {
    const r = computeAdherence(doses, [p(5, "a"), p(55, "b")], W, S + 1000 * M);
    expect(r.map((d) => [d.status, d.evidenceEventId])).toEqual([
      ["taken", "a"],
      ["taken", "b"],
    ]);
  });
  test("an exact tie goes to the earlier dose", () => {
    const r = computeAdherence(doses, [p(30)], W, S + 1000 * M);
    expect(r.map((d) => d.status)).toEqual(["taken", "missed"]);
  });
  test("a pickup inside two doses' windows is not reused for the second", () => {
    // Doses 08:00 and 08:20 with W=30: a pickup at 08:09 is within both taken windows,
    // but it is nearest to 08:00, so 08:20 has no evidence.
    const close: ScheduledDose[] = [
      { key: "a", scheduledFor: S },
      { key: "b", scheduledFor: S + 20 * M },
    ];
    const r = computeAdherence(close, [p(9)], 30, S + 1000 * M);
    expect(r.map((d) => d.status)).toEqual(["taken", "missed"]);
  });
  test("a pickup nearest to a dose but outside its windows is not evidence for any dose", () => {
    // Doses 08:00 and 08:30 with W=10: a pickup at 07:46 is nearest to 08:00 but too early.
    const close: ScheduledDose[] = [
      { key: "a", scheduledFor: S },
      { key: "b", scheduledFor: S + 30 * M },
    ];
    const r = computeAdherence(close, [p(-14)], 10, S + 1000 * M);
    expect(r.map((d) => d.status)).toEqual(["missed", "missed"]);
  });
  test("twice-daily schedule: an evening pickup is not reused for the next morning", () => {
    const day: ScheduledDose[] = [
      { key: "am", scheduledFor: S },
      { key: "pm", scheduledFor: S + 720 * M },
      { key: "am+1", scheduledFor: S + 1440 * M },
    ];
    const r = computeAdherence(day, [p(5, "am"), p(730, "pm")], W, S + 1440 * M + 121 * M);
    expect(r.map((d) => d.status)).toEqual(["taken", "taken", "missed"]);
  });
});

describe("DST day (America/Los_Angeles, 2025-03-09 spring forward)", () => {
  const tz = "America/Los_Angeles";
  const am = zonedToUnix("2025-03-09", "08:00", tz);
  const pm = zonedToUnix("2025-03-09", "20:00", tz);
  const doses: ScheduledDose[] = [
    { key: "am", scheduledFor: am },
    { key: "pm", scheduledFor: pm },
  ];
  test("wall-clock windows hold across the transition", () => {
    const pickupAm = { eventId: "a", t: zonedToUnix("2025-03-09", "08:59", tz) };
    const pickupPm = { eventId: "b", t: zonedToUnix("2025-03-09", "21:30", tz) };
    const r = computeAdherence(doses, [pickupAm, pickupPm], 60, pm + 3 * 3600);
    expect(r.map((d) => d.status)).toEqual(["taken", "late"]);
  });
  test("the overnight transition does not shift the morning window", () => {
    // 07:00 PDT is exactly W before 08:00 PDT even though the night was 1 hour shorter.
    const r = computeAdherence(doses, [{ eventId: "a", t: zonedToUnix("2025-03-09", "07:00", tz) }], 60, pm);
    expect(r[0].status).toBe("taken");
  });
});
