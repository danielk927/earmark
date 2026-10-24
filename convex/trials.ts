import { v } from "convex/values";
import type { Doc } from "./_generated/dataModel";
import { query } from "./_generated/server";
import { trialFields } from "./lib/validators";

/** Trials are few (a pilot); this bound is far above any real count. */
const MAX_TRIALS = 2000;

const modeStats = v.object({
  trials: v.number(),
  found: v.number(),
  testers: v.number(),
  medianSecondsToFind: v.union(v.number(), v.null()),
  wrongPicks: v.number(),
});

function toRow(t: Doc<"trials">) {
  return {
    trialId: t.trialId,
    mode: t.mode,
    targetObjectId: t.targetObjectId,
    tester: t.tester,
    startedAt: t.startedAt,
    endedAt: t.endedAt,
    secondsToFind: t.secondsToFind,
    wrongPicks: t.wrongPicks,
    outcome: t.outcome,
  };
}

export function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 === 1 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

/** Raw counts per mode over completed trials (endedAt set). Never extrapolated. */
export function statsFor(trials: Doc<"trials">[], mode: "earmark" | "baseline"): typeof modeStats.type {
  const done = trials.filter((t) => t.mode === mode && t.endedAt !== null);
  const found = done.filter((t) => t.outcome === "found");
  return {
    trials: done.length,
    found: found.length,
    testers: new Set(done.map((t) => t.tester)).size,
    medianSecondsToFind: median(found.flatMap((t) => (t.secondsToFind === null ? [] : [t.secondsToFind]))),
    wrongPicks: done.reduce((sum, t) => sum + t.wrongPicks, 0),
  };
}

export const list = query({
  args: {},
  returns: v.array(v.object(trialFields)),
  handler: async (ctx) =>
    (await ctx.db.query("trials").withIndex("by_startedAt").order("desc").take(MAX_TRIALS)).map(toRow),
});

export const summary = query({
  args: {},
  returns: v.object({ earmark: modeStats, baseline: modeStats }),
  handler: async (ctx) => {
    const trials = await ctx.db.query("trials").withIndex("by_startedAt").take(MAX_TRIALS);
    return { earmark: statsFor(trials, "earmark"), baseline: statsFor(trials, "baseline") };
  },
});
