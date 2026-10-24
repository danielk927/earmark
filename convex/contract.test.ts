/**
 * The dashboard calls Convex through contracts/ts/convexFunctions.ts (`fn`).
 * Compile-time: every function's kind matches, the contract's args are accepted
 * by our validators, and our return type is assignable to the contract's.
 * `npx convex dev` and `npm run typecheck` both type-check this file, so a drift
 * fails the build. Runtime: every contract name resolves to the same function.
 */
import { getFunctionName, type FunctionArgs, type FunctionReference, type FunctionReturnType } from "convex/server";
import { describe, expect, test } from "vitest";
import { fn } from "../contracts/ts/convexFunctions";
import { api } from "./_generated/api";

type AnyRef = FunctionReference<"query" | "mutation" | "action", "public">;
type Matches<Ours extends AnyRef, Contract extends AnyRef> = [Ours["_type"]] extends [Contract["_type"]]
  ? [FunctionArgs<Contract>] extends [FunctionArgs<Ours>]
    ? [FunctionReturnType<Ours>] extends [FunctionReturnType<Contract>]
      ? true
      : "our return type is not assignable to the contract's"
    : "the contract's args are not accepted by our validators"
  : "function kind differs";

export const typeChecks: Record<string, true> = {
  "dashboard:liveMap": true satisfies Matches<typeof api.dashboard.liveMap, typeof fn.dashboard.liveMap>,
  "objects:list": true satisfies Matches<typeof api.objects.list, typeof fn.objects.list>,
  "objects:create": true satisfies Matches<typeof api.objects.create, typeof fn.objects.create>,
  "objects:update": true satisfies Matches<typeof api.objects.update, typeof fn.objects.update>,
  "objects:remove": true satisfies Matches<typeof api.objects.remove, typeof fn.objects.remove>,
  "events:recent": true satisfies Matches<typeof api.events.recent, typeof fn.events.recent>,
  "medications:list": true satisfies Matches<typeof api.medications.list, typeof fn.medications.list>,
  "medications:upsert": true satisfies Matches<typeof api.medications.upsert, typeof fn.medications.upsert>,
  "doses:forDate": true satisfies Matches<typeof api.doses.forDate, typeof fn.doses.forDate>,
  "trials:list": true satisfies Matches<typeof api.trials.list, typeof fn.trials.list>,
  "trials:summary": true satisfies Matches<typeof api.trials.summary, typeof fn.trials.summary>,
  "labeling:generateUploadUrl": true satisfies Matches<
    typeof api.labeling.generateUploadUrl,
    typeof fn.labeling.generateUploadUrl
  >,
  "labeling:suggestFromPhoto": true satisfies Matches<
    typeof api.labeling.suggestFromPhoto,
    typeof fn.labeling.suggestFromPhoto
  >,
};

describe("client function contract", () => {
  test("every contract reference names a function we export", () => {
    const names = Object.values(fn).flatMap((mod) => Object.values(mod).map((ref) => getFunctionName(ref)));
    expect(names.sort()).toEqual(Object.keys(typeChecks).sort());
    const ours = api as unknown as Record<string, Record<string, AnyRef>>;
    for (const name of names) {
      const [mod, f] = name.split(":");
      expect(ours[mod]?.[f], name).toBeDefined();
      expect(getFunctionName(ours[mod][f])).toBe(name);
    }
  });
});
