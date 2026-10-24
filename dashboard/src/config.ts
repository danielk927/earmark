export type AppMode =
  | { kind: "convex"; url: string }
  | { kind: "demo" }
  | { kind: "unconfigured"; reason: "missing" | "invalid"; url?: string };

/** ?demo=1 always wins; otherwise VITE_CONVEX_URL decides. */
export function resolveMode(search: string, convexUrl: string | undefined): AppMode {
  if (new URLSearchParams(search).get("demo") === "1") return { kind: "demo" };
  const url = convexUrl?.trim();
  if (!url) return { kind: "unconfigured", reason: "missing" };
  try {
    const u = new URL(url);
    if (u.protocol !== "https:" && u.protocol !== "http:") throw new Error("bad protocol");
  } catch {
    return { kind: "unconfigured", reason: "invalid", url };
  }
  return { kind: "convex", url };
}
