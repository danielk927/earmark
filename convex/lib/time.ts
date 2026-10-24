/**
 * Household-local time math with Intl.DateTimeFormat only (no dependencies).
 * Times are unix seconds (floats) unless a name says Ms. Dates are "YYYY-MM-DD".
 */

const DAY_MS = 86_400_000;
const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(timeZone: string): Intl.DateTimeFormat {
  let f = formatters.get(timeZone);
  if (!f) {
    f = new Intl.DateTimeFormat("en-US", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    });
    formatters.set(timeZone, f);
  }
  return f;
}

export function isValidTimeZone(timeZone: string): boolean {
  try {
    formatter(timeZone);
    return true;
  } catch {
    return false;
  }
}

interface WallClock {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
}

function wallClock(ms: number, timeZone: string): WallClock {
  const out: WallClock = { year: 0, month: 0, day: 0, hour: 0, minute: 0, second: 0 };
  for (const part of formatter(timeZone).formatToParts(new Date(ms))) {
    if (part.type in out) out[part.type as keyof WallClock] = Number(part.value);
  }
  return out;
}

/** Offset of `timeZone` from UTC at instant `ms`, in minutes (America/Los_Angeles in summer: -420). */
export function offsetMinutes(ms: number, timeZone: string): number {
  const w = wallClock(ms, timeZone);
  const asUtc = Date.UTC(w.year, w.month - 1, w.day, w.hour, w.minute, w.second);
  return Math.round((asUtc - Math.floor(ms / 1000) * 1000) / 60_000);
}

const pad = (n: number, width = 2) => String(n).padStart(width, "0");

const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const HHMM_RE = /^([01]\d|2[0-3]):([0-5]\d)$/;

export function isValidDate(date: string): boolean {
  const m = DATE_RE.exec(date);
  if (!m) return false;
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  return d.getUTCFullYear() === Number(m[1]) && d.getUTCMonth() + 1 === Number(m[2]) && d.getUTCDate() === Number(m[3]);
}

export function isValidHHMM(time: string): boolean {
  return HHMM_RE.test(time);
}

function parseDate(date: string): [number, number, number] {
  const m = DATE_RE.exec(date);
  if (!m || !isValidDate(date)) throw new Error(`invalid date ${date}`);
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

export function addDays(date: string, days: number): string {
  const [y, m, d] = parseDate(date);
  const t = new Date(Date.UTC(y, m - 1, d) + days * DAY_MS);
  return `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())}`;
}

/** Household-local calendar date of instant `t`. */
export function localDate(t: number, timeZone: string): string {
  const w = wallClock(t * 1000, timeZone);
  return `${pad(w.year, 4)}-${pad(w.month)}-${pad(w.day)}`;
}

/** Household-local "HH:MM" of instant `t`. */
export function localHHMM(t: number, timeZone: string): string {
  const w = wallClock(t * 1000, timeZone);
  return `${pad(w.hour)}:${pad(w.minute)}`;
}

/**
 * Unix seconds of the local wall-clock time `date` `hhmm` in `timeZone`.
 * Follows Temporal's "compatible" disambiguation: a time repeated by a fall-back
 * transition resolves to the earlier instant; a time skipped by a spring-forward
 * transition resolves to the instant just after the gap (02:30 becomes 03:30).
 */
export function zonedToUnix(date: string, hhmm: string, timeZone: string): number {
  const [y, mo, d] = parseDate(date);
  const tm = HHMM_RE.exec(hhmm);
  if (!tm) throw new Error(`invalid time ${hhmm}`);
  const wall = Date.UTC(y, mo - 1, d, Number(tm[1]), Number(tm[2]));
  const before = offsetMinutes(wall - 1.5 * DAY_MS, timeZone);
  const after = offsetMinutes(wall + 1.5 * DAY_MS, timeZone);
  const candidates = [...new Set([before, after])]
    .map((off) => wall - off * 60_000)
    .filter((ms) => wall - offsetMinutes(ms, timeZone) * 60_000 === ms)
    .sort((a, b) => a - b);
  const ms = candidates.length > 0 ? candidates[0] : wall - before * 60_000;
  return ms / 1000;
}

/** Unix seconds of local midnight that starts `date`. */
export function startOfLocalDay(date: string, timeZone: string): number {
  return zonedToUnix(date, "00:00", timeZone);
}

/**
 * ISO 8601 with the household offset, e.g. "2025-10-24T17:00:00.120-07:00".
 * Milliseconds appear only when nonzero.
 */
export function formatLocalIso(t: number, timeZone: string): string {
  const ms = Math.round(t * 1000);
  const w = wallClock(ms, timeZone);
  const off = offsetMinutes(ms, timeZone);
  const millis = ((ms % 1000) + 1000) % 1000;
  const sign = off < 0 ? "-" : "+";
  const abs = Math.abs(off);
  return (
    `${pad(w.year, 4)}-${pad(w.month)}-${pad(w.day)}T${pad(w.hour)}:${pad(w.minute)}:${pad(w.second)}` +
    (millis ? `.${pad(millis, 3)}` : "") +
    `${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`
  );
}

const longDate = new Intl.DateTimeFormat("en-US", {
  timeZone: "UTC",
  weekday: "long",
  month: "long",
  day: "numeric",
});

/** "Thursday, October 23" for "2025-10-23". */
export function longDateLabel(date: string): string {
  const [y, m, d] = parseDate(date);
  return longDate.format(new Date(Date.UTC(y, m - 1, d, 12)));
}
