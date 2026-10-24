import { createContext, useContext, type ReactNode } from "react";
import type { FunctionArgs, FunctionReference, FunctionReturnType } from "convex/server";

export type Connection = "live" | "connecting" | "offline" | "demo";

/**
 * Everything a page needs from the data layer. Two implementations exist: the real Convex client
 * (convexBackend.ts) and the in-memory demo fixtures (fixtureBackend.ts). The choice is made once
 * at startup and never changes, so calling these hooks is stable across renders.
 */
export interface Backend {
  kind: "convex" | "demo";
  useQuery<Q extends FunctionReference<"query">>(query: Q, args: FunctionArgs<Q>): FunctionReturnType<Q> | undefined;
  useMutation<M extends FunctionReference<"mutation">>(
    mutation: M,
  ): (args: FunctionArgs<M>) => Promise<FunctionReturnType<M>>;
  useAction<A extends FunctionReference<"action">>(action: A): (args: FunctionArgs<A>) => Promise<FunctionReturnType<A>>;
  useConnection(): Connection;
  /** POSTs the photo to a Convex upload URL and returns the storage id. */
  uploadPhoto(uploadUrl: string, photo: Blob): Promise<string>;
}

const BackendContext = createContext<Backend | null>(null);

export function BackendProvider({ backend, children }: { backend: Backend; children: ReactNode }) {
  return <BackendContext.Provider value={backend}>{children}</BackendContext.Provider>;
}

/** "demo", "convex", or null when the dashboard is not connected to anything. */
export function useBackendKind(): Backend["kind"] | null {
  return useContext(BackendContext)?.kind ?? null;
}

export function useBackend(): Backend {
  const b = useContext(BackendContext);
  if (!b) throw new Error("useBackend must be used inside <BackendProvider>");
  return b;
}
