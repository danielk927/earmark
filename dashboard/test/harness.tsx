import { render } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../src/App";
import { convexBackend } from "../src/data/convexBackend";
import { demoDoses, makeFixtures, type FixtureData } from "../src/data/fixtures";
import { modeStats } from "../src/data/fixtureBackend";
import { convexMock } from "./convexMock";

/** Friday, October 23, 2026, 5:05 PM in Los Angeles. */
export const NOW = Date.parse("2026-10-23T17:05:00-07:00") / 1000;
export const TODAY = "2026-10-23";
export const YESTERDAY = "2026-10-22";

/** Load contract-shaped fixture data into the mocked Convex queries. */
export function serve(data: FixtureData = makeFixtures(NOW)) {
  convexMock.setQuery("dashboard:liveMap", data.liveMap);
  convexMock.setQuery("objects:list", data.liveMap.objects);
  convexMock.setQuery("events:recent", (a: { limit?: number }) => data.events.slice(0, a.limit ?? 50));
  convexMock.setQuery("medications:list", data.medications);
  convexMock.setQuery("doses:forDate", (a: { date: string }) => ({
    date: a.date,
    timezone: data.liveMap.household.timezone,
    doses: demoDoses(data, a.date, NOW),
  }));
  convexMock.setQuery("trials:list", data.trials);
  convexMock.setQuery("trials:summary", {
    earmark: modeStats(data.trials, "earmark"),
    baseline: modeStats(data.trials, "baseline"),
  });
  return data;
}

/** Render the real app (real convexBackend, mocked convex/react) at a route, with the clock frozen at NOW. */
export function renderAt(route: string) {
  vi.useFakeTimers({ toFake: ["Date"], now: NOW * 1000 });
  window.history.replaceState(null, "", route);
  return render(<App backend={convexBackend} mode={{ kind: "convex", url: "https://test.convex.cloud" }} />);
}
