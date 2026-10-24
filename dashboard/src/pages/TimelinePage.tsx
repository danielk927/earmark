import { fn, type EventRow } from "@contracts/convexFunctions";
import { useBackend } from "../data/backend";
import { addDays, formatClock, formatLongDate, localDate } from "../lib/time";
import { Loading, Page, useNow } from "../components/common";
import { Icon, type IconName } from "../components/Icon";

const kindLook: Record<string, { icon: IconName; label: string }> = {
  pickup: { icon: "held", label: "Picked up" },
  placed: { icon: "placed", label: "Put down" },
  lost: { icon: "missing", label: "Not detected" },
  missing: { icon: "missing", label: "Not detected" },
  roaming: { icon: "roaming", label: "Nearby" },
  unknown_tag: { icon: "newItem", label: "New tag" },
};

const LIMIT = 100;

export function TimelinePage() {
  const { useQuery } = useBackend();
  const map = useQuery(fn.dashboard.liveMap, {});
  const events = useQuery(fn.events.recent, { limit: LIMIT });
  const now = useNow(60_000);

  return (
    <Page title="Timeline" lead="Recent pickups and put-downs, newest first.">
      {!map || !events ? (
        <Loading what="the timeline" />
      ) : events.length === 0 ? (
        <p>Nothing recorded yet. Pickups and put-downs appear here as they happen.</p>
      ) : (
        <Days events={events} timezone={map.household.timezone} today={localDate(now, map.household.timezone)} />
      )}
    </Page>
  );
}

function Days({ events, timezone, today }: { events: EventRow[]; timezone: string; today: string }) {
  const groups = new Map<string, EventRow[]>();
  for (const e of [...events].sort((a, b) => b.t - a.t)) {
    const d = localDate(e.t, timezone);
    groups.set(d, [...(groups.get(d) ?? []), e]);
  }
  const dayName = (d: string) =>
    d === today ? `Today, ${formatLongDate(d)}` : d === addDays(today, -1) ? `Yesterday, ${formatLongDate(d)}` : formatLongDate(d);

  return (
    <>
      <p className="quiet">
        Showing the latest {events.length} events{events.length === LIMIT ? " (older events are not shown)" : ""}. Times
        are in the household's time zone ({timezone}).
      </p>
      {[...groups].map(([day, list]) => (
        <section key={day} aria-labelledby={`day-${day}`} className="block">
          <h2 id={`day-${day}`}>{dayName(day)}</h2>
          <ol className="timeline">
            {list.map((e) => {
              const look = kindLook[e.kind] ?? { icon: "dot" as IconName, label: e.kind.replace(/_/g, " ") };
              return (
                <li key={e.eventId}>
                  <time dateTime={new Date(e.t * 1000).toISOString()} className="timeline-time">
                    {formatClock(e.t, timezone)}
                  </time>
                  <span className="timeline-kind">
                    <Icon name={look.icon} size={20} />
                    <span>{look.label}</span>
                  </span>
                  <span className="timeline-detail">{e.detail}</span>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </>
  );
}
