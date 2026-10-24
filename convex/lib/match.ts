/**
 * GET /api/object?name= matching: case-insensitive exact name, then exact alias,
 * then substring (the query inside a name or alias, or a name or alias inside the
 * query as whole words, so "the sugar jar" finds "sugar"). Lower rank is better.
 */
export const normalizeQuery = (s: string) => s.toLowerCase().trim().replace(/\s+/g, " ");

export function matchRank(query: string, name: string, aliases: readonly string[]): number | null {
  const q = normalizeQuery(query);
  if (q.length === 0) return null;
  const n = normalizeQuery(name);
  const as = aliases.map(normalizeQuery).filter((a) => a.length > 0);
  if (n === q) return 0;
  if (as.includes(q)) return 1;
  const all = [n, ...as];
  if (all.some((x) => x.includes(q))) return 2;
  const padded = ` ${q} `;
  if (all.some((x) => padded.includes(` ${x} `))) return 3;
  return null;
}
