/**
 * Stand-in for "convex/react" (wired up in setup.ts). Queries resolve by contract function name
 * ("dashboard:liveMap") to values the test sets; mutations and actions are vi.fn spies, so tests
 * assert the exact function and arguments the real backend would receive.
 */
import { useSyncExternalStore, type ReactNode } from "react";
import { getFunctionName, type FunctionReference } from "convex/server";
import { vi, type Mock } from "vitest";

type Resolver = (args: Record<string, unknown>) => unknown;

const queries = new Map<string, Resolver>();
const mutations = new Map<string, Mock>();
const actions = new Map<string, Mock>();
const queryCalls: { name: string; args: unknown }[] = [];
let version = 0;
const listeners = new Set<() => void>();

export const convexMock = {
  reset() {
    queries.clear();
    mutations.clear();
    actions.clear();
    queryCalls.length = 0;
    this.connected = true;
  },
  connected: true,
  /** Set a query result (a value, or a function of the args). Re-renders subscribers. */
  setQuery(name: string, value: unknown) {
    queries.set(name, typeof value === "function" ? (value as Resolver) : () => value);
    version++;
    for (const l of listeners) l();
  },
  mutation(name: string): Mock {
    if (!mutations.has(name)) mutations.set(name, vi.fn(async () => null));
    return mutations.get(name)!;
  },
  action(name: string): Mock {
    if (!actions.has(name)) actions.set(name, vi.fn(async () => null));
    return actions.get(name)!;
  },
  queryCalls,
};

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function useQuery(ref: FunctionReference<"query">, args: Record<string, unknown> = {}) {
  useSyncExternalStore(subscribe, () => version);
  const name = getFunctionName(ref);
  queryCalls.push({ name, args });
  return queries.get(name)?.(args);
}

export function useMutation(ref: FunctionReference<"mutation">) {
  return convexMock.mutation(getFunctionName(ref));
}

export function useAction(ref: FunctionReference<"action">) {
  return convexMock.action(getFunctionName(ref));
}

export function useConvexConnectionState() {
  return {
    isWebSocketConnected: convexMock.connected,
    hasEverConnected: true,
    hasInflightRequests: false,
    timeOfOldestInflightRequest: null,
    connectionCount: 1,
    connectionRetries: 0,
    inflightMutations: 0,
    inflightActions: 0,
  };
}

export function ConvexProvider({ children }: { children: ReactNode }) {
  return children;
}

export class ConvexReactClient {
  constructor(readonly address: string) {}
}
