import { useAction, useConvexConnectionState, useMutation, useQuery } from "convex/react";
import type { OptionalRestArgsOrSkip } from "convex/react";
import type { FunctionReference } from "convex/server";
import type { Backend, Connection } from "./backend";

export const convexBackend: Backend = {
  kind: "convex",
  useQuery: <Q extends FunctionReference<"query">>(query: Q, args: Q["_args"]) =>
    useQuery(query, ...([args] as unknown as OptionalRestArgsOrSkip<Q>)),
  useMutation: (mutation) => {
    const run = useMutation(mutation);
    return (args) => run(args);
  },
  useAction: (action) => {
    const run = useAction(action);
    return (args) => run(args);
  },
  useConnection: (): Connection => {
    const s = useConvexConnectionState();
    if (s.isWebSocketConnected) return "live";
    return s.hasEverConnected ? "offline" : "connecting";
  },
  async uploadPhoto(uploadUrl, photo) {
    const res = await fetch(uploadUrl, { method: "POST", headers: { "Content-Type": photo.type }, body: photo });
    if (!res.ok) throw new Error(`The photo upload failed (HTTP ${res.status}).`);
    const body = (await res.json()) as { storageId?: string };
    if (!body.storageId) throw new Error("The photo upload did not return a storage id.");
    return body.storageId;
  },
};
