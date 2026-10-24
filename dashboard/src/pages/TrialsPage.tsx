import { fn, type LiveMap, type ModeStats, type TrialRow, type TrialSummary } from "@contracts/convexFunctions";
import { useBackend } from "../data/backend";
import { formatSeconds, formatWhen } from "../lib/time";
import { capitalize, objectName } from "../lib/words";
import { Loading, Notice, Page, StatusText, TableScroll, useNow } from "../components/common";

export const PILOT_THRESHOLD = 10;

const modeName: Record<TrialRow["mode"], string> = { earmark: "Earmark", baseline: "Baseline (searching by touch)" };
const outcomeText: Record<NonNullable<TrialRow["outcome"]>, string> = {
  found: "Found",
  gave_up: "Gave up",
  aborted: "Stopped",
};

export function TrialsPage() {
  const { useQuery, kind } = useBackend();
  const summary = useQuery(fn.trials.summary, {});
  const trials = useQuery(fn.trials.list, {});
  const map = useQuery(fn.dashboard.liveMap, {});

  return (
    <Page
      title="Trials"
      lead="Timed search trials: a blindfolded tester looks for one item among look-alikes, either with Earmark or by touch alone."
    >
      {kind === "demo" && (
        <Notice tone="warn" icon="flask" title="These are made-up example trials.">
          <p>They show how this page looks. They are not results and must not be quoted.</p>
        </Notice>
      )}
      {!summary || !trials || !map ? <Loading what="trials" /> : <TrialsBody summary={summary} trials={trials} map={map} />}
    </Page>
  );
}

function TrialsBody({ summary, trials, map }: { summary: TrialSummary; trials: TrialRow[]; map: LiveMap }) {
  const now = useNow(60_000);
  const completed = summary.earmark.trials + summary.baseline.trials;
  if (trials.length === 0 && completed === 0) {
    return (
      <section className="block" aria-labelledby="empty-heading">
        <h2 id="empty-heading">No trials recorded yet</h2>
        <p>
          Run a trial with <code>scripts/trial.py</code>. Each finished trial appears here as soon as it is recorded.
        </p>
      </section>
    );
  }
  const testers = new Set(trials.filter((t) => t.endedAt != null).map((t) => t.tester)).size;
  const inProgress = trials.filter((t) => t.endedAt == null).length;

  return (
    <>
      {completed < PILOT_THRESHOLD ? (
        <Notice tone="accent" icon="info" title={`Pilot: ${completed} completed ${completed === 1 ? "trial" : "trials"}`}>
          <p>
            {summary.earmark.trials} with Earmark and {summary.baseline.trials} at baseline, by {testers}{" "}
            {testers === 1 ? "tester" : "testers"}. That is too few trials to generalize from; read these as early
            observations.
          </p>
        </Notice>
      ) : (
        <p>
          {completed} completed trials by {testers} {testers === 1 ? "tester" : "testers"}.
        </p>
      )}

      <section aria-labelledby="summary-heading" className="block">
        <h2 id="summary-heading">Summary</h2>
        <p className="quiet">Counts are raw numbers of completed trials. Trials still running are not included.</p>
        <TableScroll label="Summary table">
          <table className="summary-table">
            <thead>
              <tr>
                <th scope="col">Measure</th>
                <th scope="col">Earmark</th>
                <th scope="col">Baseline (searching by touch)</th>
              </tr>
            </thead>
            <tbody>
              <SummaryRow label="Completed trials" get={(m) => String(m.trials)} summary={summary} />
              <SummaryRow label="Target found" get={(m) => `${m.found} of ${m.trials}`} summary={summary} />
              <SummaryRow label="Testers" get={(m) => String(m.testers)} summary={summary} />
              <SummaryRow
                label="Median time to find"
                get={(m) =>
                  m.medianSecondsToFind == null
                    ? "No finds yet"
                    : `${formatSeconds(m.medianSecondsToFind)} (over ${m.found} ${m.found === 1 ? "find" : "finds"})`
                }
                summary={summary}
              />
              <SummaryRow
                label="Wrong picks"
                get={(m) => `${m.wrongPicks} across ${m.trials} ${m.trials === 1 ? "trial" : "trials"}`}
                summary={summary}
              />
            </tbody>
          </table>
        </TableScroll>
      </section>

      <section aria-labelledby="all-heading" className="block">
        <h2 id="all-heading">Every trial</h2>
        {inProgress > 0 && <p>{inProgress} {inProgress === 1 ? "trial is" : "trials are"} still running.</p>}
        <TableScroll label="Table of every trial">
          <table>
            <thead>
              <tr>
                <th scope="col">Started</th>
                <th scope="col">Mode</th>
                <th scope="col">Target</th>
                <th scope="col">Tester</th>
                <th scope="col">Outcome</th>
                <th scope="col">Time to find</th>
                <th scope="col">Wrong picks</th>
              </tr>
            </thead>
            <tbody>
              {[...trials]
                .sort((a, b) => b.startedAt - a.startedAt)
                .map((t) => (
                  <tr key={t.trialId}>
                    <th scope="row">{formatWhen(t.startedAt, now, map.household.timezone)}</th>
                    <td>{modeName[t.mode]}</td>
                    <td>{capitalize(objectName(map, t.targetObjectId))}</td>
                    <td>{t.tester}</td>
                    <td>
                      {t.endedAt == null ? (
                        <StatusText icon="pending" tone="idle">
                          Running
                        </StatusText>
                      ) : t.outcome === "found" ? (
                        <StatusText icon="taken" tone="ok">
                          Found
                        </StatusText>
                      ) : (
                        <StatusText icon="missed" tone="bad">
                          {t.outcome ? outcomeText[t.outcome] : "Ended"}
                        </StatusText>
                      )}
                    </td>
                    <td>{t.secondsToFind != null ? formatSeconds(t.secondsToFind) : "None"}</td>
                    <td>{t.wrongPicks}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </TableScroll>
      </section>
    </>
  );
}

function SummaryRow({ label, get, summary }: { label: string; get: (m: ModeStats) => string; summary: TrialSummary }) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td>{get(summary.earmark)}</td>
      <td>{get(summary.baseline)}</td>
    </tr>
  );
}
