import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fn } from "@contracts/convexFunctions";
import { ConvexError } from "convex/values";
import { resolveMode } from "../src/config";
import { describeChanges } from "../src/lib/changes";
import { errorMessage, photoErrorMessage } from "../src/lib/errors";
import { addDays, formatAgo, formatClock, localDate, zonedToUnix } from "../src/lib/time";
import { splitAliases } from "../src/lib/words";
import { createFixtureBackend, modeStats, slugify } from "../src/data/fixtureBackend";
import { makeFixtures, UNKNOWN_TAG } from "../src/data/fixtures";
import { NOW } from "./harness";

const TZ = "America/Los_Angeles";

describe("time", () => {
  it("converts household-local wall time to unix seconds across DST", () => {
    expect(zonedToUnix("2026-10-23", "17:05", TZ)).toBe(Date.parse("2026-10-23T17:05:00-07:00") / 1000);
    expect(zonedToUnix("2026-11-02", "08:00", TZ)).toBe(Date.parse("2026-11-02T08:00:00-08:00") / 1000);
    expect(localDate(NOW, TZ)).toBe("2026-10-23");
    expect(formatClock(NOW, TZ)).toBe("5:05 PM");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
  });

  it("phrases elapsed time", () => {
    expect(formatAgo(NOW - 10, NOW)).toBe("just now");
    expect(formatAgo(NOW - 300, NOW)).toBe("5 min ago");
    expect(formatAgo(NOW - 7200, NOW)).toBe("2 h ago");
    expect(formatAgo(NOW - 86400, NOW)).toBe("1 day ago");
  });
});

describe("config", () => {
  it("chooses demo, convex, or not connected", () => {
    expect(resolveMode("?demo=1", "https://x.convex.cloud")).toEqual({ kind: "demo" });
    expect(resolveMode("", "https://x.convex.cloud")).toEqual({ kind: "convex", url: "https://x.convex.cloud" });
    expect(resolveMode("", "")).toEqual({ kind: "unconfigured", reason: "missing" });
    expect(resolveMode("", undefined)).toEqual({ kind: "unconfigured", reason: "missing" });
    expect(resolveMode("", "not a url")).toEqual({ kind: "unconfigured", reason: "invalid", url: "not a url" });
  });
});

describe("change announcements", () => {
  const base = makeFixtures(NOW).liveMap;
  const withState = (id: string, patch: object) => ({
    ...base,
    states: base.states.map((s) => (s.objectId === id ? { ...s, ...patch } : s)),
  });

  it("describes pickups, put-downs, moves, losses, and new tags", () => {
    expect(describeChanges(base, withState("sugar", { status: "held", spot: null }))).toEqual([
      "Sugar picked up from the center right spot.",
    ]);
    expect(describeChanges(base, withState("salt", { status: "on_spot", spot: 2 }))).toEqual([
      "Salt put down on the center left spot.",
    ]);
    expect(describeChanges(base, withState("sugar", { spot: 1 }))).toEqual(["Sugar moved to the far left spot."]);
    expect(describeChanges(base, withState("bp_meds", { status: "missing", spot: null }))).toEqual([
      "Blood pressure pills is missing.",
    ]);
    expect(describeChanges(base, withState("keys", { distanceClass: "near" }))).toEqual([
      "Keys is near the hub receiver, close range.",
    ]);
    expect(describeChanges({ ...base, unknownTags: [] }, base)).toEqual([
      "New item on the far left spot. Label it on the Items page.",
    ]);
    expect(describeChanges(base, base)).toEqual([]);
  });

  it("describes remote labeling", () => {
    const renamed = { ...base, objects: base.objects.map((o) => (o.objectId === "salt" ? { ...o, name: "sea salt" } : o)) };
    expect(describeChanges(base, renamed)).toEqual(["Salt renamed to sea salt."]);
  });
});

describe("errors", () => {
  it("reads ConvexError data and trims server noise", () => {
    expect(errorMessage(new ConvexError("Name already used"))).toBe("Name already used");
    expect(errorMessage(new ConvexError({ message: "No such item" }))).toBe("No such item");
    expect(errorMessage(new Error("[CONVEX M(objects:update)] [Request ID: 9] Server Error\nUncaught Error: No such item\n  at x"))).toBe(
      "No such item",
    );
    expect(photoErrorMessage(new Error("Request timed out"))).toMatch(/took too long/);
  });
});

describe("demo backend", () => {
  it("labels an unknown tag: the tag disappears and the new item sits on its spot", async () => {
    const backend = createFixtureBackend(makeFixtures(NOW), { delayMs: 0, now: () => NOW });
    const { result } = renderHook(() => ({
      map: backend.useQuery(fn.dashboard.liveMap, {}),
      create: backend.useMutation(fn.objects.create),
    }));
    expect(result.current.map?.unknownTags.map((u) => u.tag)).toEqual([UNKNOWN_TAG]);
    let id = "";
    await act(async () => {
      id = await result.current.create({
        name: "Honey",
        aliases: [],
        notes: "",
        description: "",
        tag: UNKNOWN_TAG,
        homeSpot: 1,
        isMedication: false,
        fobId: null,
      });
    });
    expect(id).toBe("honey");
    expect(result.current.map?.unknownTags).toEqual([]);
    expect(result.current.map?.states.find((s) => s.objectId === "honey")).toMatchObject({ status: "on_spot", spot: 1 });
  });

  it("summarizes trials with raw counts and a median", () => {
    const trials = makeFixtures(NOW).trials;
    expect(modeStats(trials, "earmark")).toEqual({ trials: 3, found: 3, testers: 2, medianSecondsToFind: 11.1, wrongPicks: 1 });
    expect(modeStats(trials, "baseline")).toEqual({ trials: 3, found: 2, testers: 2, medianSecondsToFind: 52.35, wrongPicks: 4 });
    expect(modeStats([], "earmark")).toEqual({ trials: 0, found: 0, testers: 0, medianSecondsToFind: null, wrongPicks: 0 });
  });

  it("derives object ids and cleans aliases", () => {
    expect(slugify("Blood pressure pills")).toBe("blood_pressure_pills");
    expect(splitAliases(" a, b ,, A, c")).toEqual(["a", "b", "c"]);
  });
});

