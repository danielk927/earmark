/* eslint-disable */
/**
 * Generated `api` utility.
 *
 * THIS CODE IS AUTOMATICALLY GENERATED.
 *
 * To regenerate, run `npx convex dev`.
 * @module
 */

import type * as crons from "../crons.js";
import type * as dashboard from "../dashboard.js";
import type * as doses from "../doses.js";
import type * as events from "../events.js";
import type * as http from "../http.js";
import type * as ingest from "../ingest.js";
import type * as labeling from "../labeling.js";
import type * as lib_adherence from "../lib/adherence.js";
import type * as lib_auth from "../lib/auth.js";
import type * as lib_bitdeer from "../lib/bitdeer.js";
import type * as lib_describe from "../lib/describe.js";
import type * as lib_match from "../lib/match.js";
import type * as lib_registry from "../lib/registry.js";
import type * as lib_seedPlan from "../lib/seedPlan.js";
import type * as lib_time from "../lib/time.js";
import type * as lib_validators from "../lib/validators.js";
import type * as lib_wire from "../lib/wire.js";
import type * as medications from "../medications.js";
import type * as objects from "../objects.js";
import type * as reads from "../reads.js";
import type * as registry from "../registry.js";
import type * as seed from "../seed.js";
import type * as summaries from "../summaries.js";
import type * as trials from "../trials.js";

import type {
  ApiFromModules,
  FilterApi,
  FunctionReference,
} from "convex/server";

declare const fullApi: ApiFromModules<{
  crons: typeof crons;
  dashboard: typeof dashboard;
  doses: typeof doses;
  events: typeof events;
  http: typeof http;
  ingest: typeof ingest;
  labeling: typeof labeling;
  "lib/adherence": typeof lib_adherence;
  "lib/auth": typeof lib_auth;
  "lib/bitdeer": typeof lib_bitdeer;
  "lib/describe": typeof lib_describe;
  "lib/match": typeof lib_match;
  "lib/registry": typeof lib_registry;
  "lib/seedPlan": typeof lib_seedPlan;
  "lib/time": typeof lib_time;
  "lib/validators": typeof lib_validators;
  "lib/wire": typeof lib_wire;
  medications: typeof medications;
  objects: typeof objects;
  reads: typeof reads;
  registry: typeof registry;
  seed: typeof seed;
  summaries: typeof summaries;
  trials: typeof trials;
}>;

/**
 * A utility for referencing Convex functions in your app's public API.
 *
 * Usage:
 * ```js
 * const myFunctionReference = api.myModule.myFunction;
 * ```
 */
export declare const api: FilterApi<
  typeof fullApi,
  FunctionReference<any, "public">
>;

/**
 * A utility for referencing Convex functions in your app's internal API.
 *
 * Usage:
 * ```js
 * const myFunctionReference = internal.myModule.myFunction;
 * ```
 */
export declare const internal: FilterApi<
  typeof fullApi,
  FunctionReference<any, "internal">
>;

export declare const components: {};
