/** Shared-secret checks for the HTTP actions (header X-Earmark-Secret). */

const encoder = new TextEncoder();

async function sha256(s: string): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(s)));
}

/**
 * Constant-time string comparison: both sides are hashed to 32 bytes first, so
 * neither the content nor the length of the secret leaks through timing.
 * An unset or empty expected secret never matches.
 */
export async function secretMatches(given: string | null, expected: string | undefined): Promise<boolean> {
  if (!expected || given === null) return false;
  const [a, b] = await Promise.all([sha256(given), sha256(expected)]);
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

/**
 * EARMARK_HUB_SECRET is accepted on every route; EARMARK_READ_SECRET only on
 * read routes (GET /api/*).
 */
export async function isAuthorized(
  given: string | null,
  secrets: { hub: string | undefined; read: string | undefined },
  readRoute: boolean,
): Promise<boolean> {
  const hub = await secretMatches(given, secrets.hub);
  const read = readRoute ? await secretMatches(given, secrets.read) : false;
  return hub || read;
}
