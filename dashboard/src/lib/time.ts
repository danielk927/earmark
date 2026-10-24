/** Time helpers. All Earmark times are unix seconds; display is in the household's time zone. */

function parts(t: number, timeZone: string): Record<string, string> {
  const out: Record<string, string> = {};
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  for (const p of fmt.formatToParts(new Date(t * 1000))) out[p.type] = p.value;
  return out;
}

/** Household-local calendar date, YYYY-MM-DD. */
export function localDate(t: number, timeZone: string): string {
  const p = parts(t, timeZone);
  return `${p.year}-${p.month}-${p.day}`;
}

/** Unix seconds for a household-local wall time ("YYYY-MM-DD", "HH:MM"). */
export function zonedToUnix(date: string, time: string, timeZone: string): number {
  const [y, mo, d] = date.split("-").map(Number) as [number, number, number];
  const [h, mi] = time.split(":").map(Number) as [number, number];
  const wallAsUtc = Date.UTC(y, mo - 1, d, h, mi) / 1000;
  // Two passes handle the offset change around DST transitions.
  let guess = wallAsUtc;
  for (let i = 0; i < 2; i++) {
    const p = parts(guess, timeZone);
    const seenAsUtc = Date.UTC(+p.year!, +p.month! - 1, +p.day!, +p.hour!, +p.minute!, +p.second!) / 1000;
    guess += wallAsUtc - seenAsUtc;
  }
  return guess;
}

/** Shift a YYYY-MM-DD date by whole days (calendar arithmetic, no time zone involved). */
export function addDays(date: string, days: number): string {
  const [y, mo, d] = date.split("-").map(Number) as [number, number, number];
  return new Date(Date.UTC(y, mo - 1, d + days)).toISOString().slice(0, 10);
}

export function isIsoDate(value: string | null | undefined): value is string {
  return !!value && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(`${value}T00:00:00Z`));
}

/** "4:58 PM" in the household's time zone. */
export function formatClock(t: number, timeZone: string): string {
  return new Intl.DateTimeFormat("en-US", { timeZone, hour: "numeric", minute: "2-digit" }).format(new Date(t * 1000));
}

/** "4:58 PM" for a household-local "HH:MM" wall time. */
export function formatWallTime(hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number) as [number, number];
  const suffix = h < 12 ? "AM" : "PM";
  const hour12 = h % 12 === 0 ? 12 : h % 12;
  return `${hour12}:${String(m).padStart(2, "0")} ${suffix}`;
}

/** "Friday, October 24" for a YYYY-MM-DD date. */
export function formatLongDate(date: string): string {
  const [y, mo, d] = date.split("-").map(Number) as [number, number, number];
  return new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "long", month: "long", day: "numeric" }).format(
    new Date(Date.UTC(y, mo - 1, d)),
  );
}

/** Short zone name, for example "PDT". */
export function zoneAbbreviation(t: number, timeZone: string): string {
  const p = new Intl.DateTimeFormat("en-US", { timeZone, timeZoneName: "short" })
    .formatToParts(new Date(t * 1000))
    .find((x) => x.type === "timeZoneName");
  return p?.value ?? timeZone;
}

/** "just now", "4 min ago", "2 h ago", "3 days ago". */
export function formatAgo(t: number, now: number): string {
  const s = Math.max(0, now - t);
  if (s < 45) return "just now";
  const min = Math.round(s / 60);
  if (min < 60) return `${min} min ago`;
  const h = Math.round(s / 3600);
  if (h < 24) return `${h} h ago`;
  const days = Math.round(s / 86400);
  return days === 1 ? "1 day ago" : `${days} days ago`;
}

/** Clock time when it is today, otherwise date and time. Always household-local. */
export function formatWhen(t: number, now: number, timeZone: string): string {
  const clock = formatClock(t, timeZone);
  const day = localDate(t, timeZone);
  if (day === localDate(now, timeZone)) return clock;
  if (day === addDays(localDate(now, timeZone), -1)) return `Yesterday ${clock}`;
  return `${formatLongDate(day)}, ${clock}`;
}

export function formatSeconds(seconds: number): string {
  return `${seconds.toFixed(1)} s`;
}
