import { useId, useState, type FormEvent } from "react";
import { useLocation, useSearch } from "wouter";
import { fn, type DoseRow, type DoseStatus, type MedicationRow, type ObjectRow } from "@contracts/convexFunctions";
import { useBackend } from "../data/backend";
import { errorMessage } from "../lib/errors";
import { addDays, formatClock, formatLongDate, formatWallTime, isIsoDate, localDate } from "../lib/time";
import { capitalize } from "../lib/words";
import { Loading, Notice, Page, StatusText, useHref, useNow, type Tone } from "../components/common";
import { Icon, type IconName } from "../components/Icon";

const doseLook: Record<DoseStatus, { icon: IconName; tone: Tone; label: string }> = {
  taken: { icon: "taken", tone: "ok", label: "Taken" },
  late: { icon: "late", tone: "warn", label: "Late" },
  missed: { icon: "missed", tone: "bad", label: "Missed" },
  pending: { icon: "pending", tone: "idle", label: "Pending" },
};

export function MedicationsPage() {
  const { useQuery } = useBackend();
  const map = useQuery(fn.dashboard.liveMap, {});
  const meds = useQuery(fn.medications.list, {});
  const now = useNow(30_000);
  const tz = map?.household.timezone;
  const today = tz ? localDate(now, tz) : null;
  const param = new URLSearchParams(useSearch()).get("date");
  const date = isIsoDate(param) ? param : today;

  return (
    <Page
      title="Medications"
      lead="Each dose is judged by when the bottle was picked up from its spot. Earmark can't tell whether a pill was taken, only that the bottle was lifted."
    >
      {!map || !meds || !date || !today ? (
        <Loading what="medications" />
      ) : (
        <>
          <DayView date={date} today={today} meds={meds} />
          <Schedules meds={meds} objects={map.objects} />
        </>
      )}
    </Page>
  );
}

function windowText(d: DoseRow, meds: MedicationRow[], tz: string): string | null {
  const w = meds.find((m) => m.objectId === d.objectId)?.windowMinutes;
  if (w == null) return null;
  const S = d.scheduledForT;
  const fmt = (t: number) => formatClock(t, tz);
  switch (d.status) {
    case "taken":
      return d.takenT != null ? `Picked up at ${fmt(d.takenT)}.` : null;
    case "late":
      return d.takenT != null ? `Picked up at ${fmt(d.takenT)}, more than ${w} minutes after the scheduled time.` : null;
    case "missed":
      return `No pickup between ${fmt(S - w * 60)} and ${fmt(S + 2 * w * 60)}.`;
    case "pending":
      return `Counts as taken if picked up between ${fmt(S - w * 60)} and ${fmt(S + w * 60)}.`;
  }
}

function DayView({ date, today, meds }: { date: string; today: string; meds: MedicationRow[] }) {
  const { useQuery } = useBackend();
  const result = useQuery(fn.doses.forDate, { date });
  const [, navigate] = useLocation();
  const href = useHref();
  const id = useId();
  const go = (d: string) => navigate(href("/medications", d === today ? {} : { date: d }), { replace: true });

  const doses = result ? [...result.doses].sort((a, b) => a.scheduledForT - b.scheduledForT) : [];
  const counts = (["taken", "late", "missed", "pending"] as DoseStatus[]).map((s) => ({
    s,
    n: doses.filter((d) => d.status === s).length,
  }));

  return (
    <section aria-labelledby={`${id}-h`} className="block">
      <h2 id={`${id}-h`}>
        Doses on {formatLongDate(date)}
        {date === today && " (today)"}
      </h2>
      <div className="day-picker">
        <div className="field inline">
          <label htmlFor={`${id}-date`}>Day</label>
          <input
            id={`${id}-date`}
            type="date"
            value={date}
            onChange={(e) => isIsoDate(e.target.value) && go(e.target.value)}
          />
        </div>
        <div className="actions">
          <button type="button" className="button" onClick={() => go(addDays(date, -1))}>
            Previous day
          </button>
          <button type="button" className="button" onClick={() => go(today)} disabled={date === today}>
            Today
          </button>
          <button type="button" className="button" onClick={() => go(addDays(date, 1))}>
            Next day
          </button>
        </div>
      </div>

      {!result ? (
        <Loading what="doses" />
      ) : doses.length === 0 ? (
        <p>No doses recorded for this day.</p>
      ) : (
        <>
          <p className="dose-counts">
            {counts.map(({ s, n }, i) => (
              <span key={s}>
                {n} {doseLook[s].label.toLowerCase()}
                {i < counts.length - 1 ? ", " : ""}
              </span>
            ))}
            <span className="quiet"> (times are in {result.timezone})</span>
          </p>
          <ol className="doses">
            {doses.map((d) => {
              const look = doseLook[d.status];
              const detail = windowText(d, meds, result.timezone);
              return (
                <li key={`${d.objectId}-${d.scheduledForT}`} className={`dose dose-${d.status}`}>
                  <p className="dose-time">{formatWallTime(d.scheduledLocalTime)}</p>
                  <div>
                    <p className="dose-name">{capitalize(d.name)}</p>
                    <StatusText icon={look.icon} tone={look.tone}>
                      {look.label}
                    </StatusText>
                    {detail && <p className="quiet">{detail}</p>}
                  </div>
                </li>
              );
            })}
          </ol>
        </>
      )}
    </section>
  );
}

function Schedules({ meds, objects }: { meds: MedicationRow[]; objects: ObjectRow[] }) {
  const [adding, setAdding] = useState<string>("");
  const unscheduled = objects.filter((o) => o.isMedication && !meds.some((m) => m.objectId === o.objectId));
  const id = useId();
  return (
    <section aria-labelledby={`${id}-h`} className="block">
      <h2 id={`${id}-h`}>Schedules</h2>
      <p className="quiet">
        A dose counts as taken when the bottle is picked up within the window before or after the time, and late when it
        is picked up within twice the window after. Otherwise it is missed.
      </p>
      {meds.length === 0 && <p>No medication schedules yet.</p>}
      <div className="schedules">
        {meds.map((m) => (
          <ScheduleForm key={m.objectId} med={m} />
        ))}
      </div>
      {unscheduled.length > 0 && (
        <div className="field inline add-schedule">
          <label htmlFor={`${id}-add`}>Add a schedule for</label>
          <select id={`${id}-add`} value={adding} onChange={(e) => setAdding(e.target.value)}>
            <option value="">Choose a medication</option>
            {unscheduled.map((o) => (
              <option key={o.objectId} value={o.objectId}>
                {capitalize(o.name)}
              </option>
            ))}
          </select>
        </div>
      )}
      {adding && (
        <ScheduleForm
          key={adding}
          med={{ objectId: adding, name: objects.find((o) => o.objectId === adding)?.name ?? adding, scheduleTimes: ["08:00"], windowMinutes: 60 }}
          isNew
          onSaved={() => setAdding("")}
        />
      )}
      {objects.every((o) => !o.isMedication) && (
        <p className="quiet">To track a medication, mark the item as a medication on the Items page.</p>
      )}
    </section>
  );
}

function ScheduleForm({ med, isNew = false, onSaved }: { med: MedicationRow; isNew?: boolean; onSaved?: () => void }) {
  const id = useId();
  const upsert = useBackend().useMutation(fn.medications.upsert);
  const [times, setTimes] = useState<string[]>(med.scheduleTimes);
  const [windowMinutes, setWindowMinutes] = useState(String(med.windowMinutes));
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const name = capitalize(med.name);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaved(null);
    const clean = [...new Set(times.filter(Boolean))].sort();
    const w = Number(windowMinutes);
    if (clean.length === 0) return setError("Add at least one dose time.");
    if (!Number.isInteger(w) || w < 5 || w > 240) return setError("The window must be a whole number of minutes from 5 to 240.");
    setError(null);
    setSaving(true);
    try {
      await upsert({ objectId: med.objectId, scheduleTimes: clean, windowMinutes: w });
      setTimes(clean);
      setSaved(`Saved the schedule for ${name}.`);
      onSaved?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="schedule" onSubmit={submit} noValidate aria-labelledby={`${id}-h`}>
      <h3 id={`${id}-h`}>{isNew ? `New schedule for ${name}` : name}</h3>
      <fieldset>
        <legend>Dose times</legend>
        <ul className="times">
          {times.map((t, i) => (
            <li key={i}>
              <label htmlFor={`${id}-t${i}`} className="visually-hidden">
                Dose time {i + 1}
              </label>
              <input
                id={`${id}-t${i}`}
                type="time"
                value={t}
                onChange={(e) => setTimes(times.map((x, j) => (j === i ? e.target.value : x)))}
              />
              <button
                type="button"
                className="button small"
                onClick={() => setTimes(times.filter((_, j) => j !== i))}
                disabled={times.length === 1}
              >
                <Icon name="trash" size={18} /> Remove<span className="visually-hidden"> dose time {i + 1}</span>
              </button>
            </li>
          ))}
        </ul>
        <button type="button" className="button small" onClick={() => setTimes([...times, "12:00"])}>
          <Icon name="plus" size={18} /> Add a time
        </button>
      </fieldset>
      <div className="field inline">
        <label htmlFor={`${id}-w`}>Window, in minutes</label>
        <input
          id={`${id}-w`}
          type="number"
          inputMode="numeric"
          min={5}
          max={240}
          step={5}
          value={windowMinutes}
          onChange={(e) => setWindowMinutes(e.target.value)}
          className="narrow"
        />
      </div>
      {error && (
        <Notice tone="bad" icon="alert" role="alert" title="Not saved.">
          <p>{error}</p>
        </Notice>
      )}
      <div role="status">{saved && <p className="saved">{saved}</p>}</div>
      <div className="actions">
        <button type="submit" className="button primary" disabled={saving}>
          {saving ? "Saving..." : "Save schedule"}
        </button>
      </div>
    </form>
  );
}
