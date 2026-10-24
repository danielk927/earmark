import { ConvexError } from "convex/values";

/**
 * A readable sentence from a Convex error. ConvexError data is shown as is; other server errors
 * arrive as "[CONVEX ...] [Request ID: ...] Server Error Uncaught Error: <message> at ..." and are trimmed.
 */
export function errorMessage(err: unknown): string {
  if (err instanceof ConvexError) {
    const data: unknown = err.data;
    if (typeof data === "string") return data;
    if (data && typeof data === "object" && "message" in data && typeof data.message === "string") return data.message;
  }
  const raw = err instanceof Error ? err.message : String(err);
  const uncaught = /Uncaught (?:\w*Error: )?([^\n]*?)(?:\s+at\s|\n|$)/.exec(raw);
  const text = (uncaught?.[1] ?? raw).trim();
  if (/^Server Error$/i.test(text) || text.includes("[Request ID")) return "The server reported an error.";
  return text || "Something went wrong.";
}

/** Photo suggestion failures, phrased for a family member rather than a developer. */
export function photoErrorMessage(err: unknown): string {
  const text = errorMessage(err);
  if (/bitdeer|api[_ ]?key/i.test(text)) {
    return "Photo suggestions are not set up on this Earmark server yet (no Bitdeer API key). Fill in the details by hand instead.";
  }
  if (/timed? ?out|timeout/i.test(text)) return "The suggestion took too long. Try again, or fill in the details by hand.";
  return `No suggestion this time: ${text}`;
}
