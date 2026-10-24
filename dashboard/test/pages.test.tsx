import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { TrialRow } from "@contracts/convexFunctions";
import { makeFixtures } from "../src/data/fixtures";
import { App } from "../src/App";
import { convexMock } from "./convexMock";
import { NOW, renderAt, serve, YESTERDAY } from "./harness";

function doseItem(time: string) {
  return screen.getByText(time, { selector: ".dose-time" }).closest("li")!;
}

describe("Medications", () => {
  it("shows the seeded missed dose with its window, in text", () => {
    serve();
    renderAt(`/medications?date=${YESTERDAY}`);
    expect(screen.getByRole("heading", { name: "Doses on Thursday, October 22" })).toBeInTheDocument();
    const evening = doseItem("8:00 PM");
    expect(evening).toHaveTextContent("Blood pressure pills");
    expect(evening).toHaveTextContent("Missed");
    expect(evening).toHaveTextContent("No pickup between 7:00 PM and 10:00 PM.");
    const morning = doseItem("8:00 AM");
    expect(morning).toHaveTextContent("Taken");
    expect(morning).toHaveTextContent("Picked up at 8:07 AM.");
    expect(screen.getByText(/1 taken/).closest("p")).toHaveTextContent("1 taken, 0 late, 1 missed, 0 pending");
  });

  it("shows today's late and pending doses", () => {
    serve();
    renderAt("/medications");
    expect(screen.getByRole("heading", { name: "Doses on Friday, October 23 (today)" })).toBeInTheDocument();
    expect(doseItem("8:00 AM")).toHaveTextContent("Late");
    expect(doseItem("8:00 AM")).toHaveTextContent("Picked up at 9:24 AM, more than 60 minutes after the scheduled time.");
    expect(doseItem("8:00 PM")).toHaveTextContent("Pending");
    expect(doseItem("8:00 PM")).toHaveTextContent("Counts as taken if picked up between 7:00 PM and 9:00 PM.");
    expect(convexMock.queryCalls).toContainEqual({ name: "doses:forDate", args: { date: "2026-10-23" } });
  });

  it("moves between days with buttons and the date field", async () => {
    serve();
    renderAt("/medications");
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Previous day" }));
    expect(screen.getByRole("heading", { name: "Doses on Thursday, October 22" })).toBeInTheDocument();
    expect(window.location.search).toBe(`?date=${YESTERDAY}`);
    await u.click(screen.getByRole("button", { name: "Previous day" }));
    expect(screen.getByText("No doses recorded for this day.")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Today" }));
    expect(screen.getByRole("heading", { name: "Doses on Friday, October 23 (today)" })).toBeInTheDocument();
  });

  it("saves an edited schedule through medications.upsert", async () => {
    serve();
    renderAt("/medications");
    const u = userEvent.setup();
    const form = screen.getByRole("form", { name: "Blood pressure pills" });
    await u.click(within(form).getByRole("button", { name: "Add a time" }));
    const w = within(form).getByLabelText("Window, in minutes");
    await u.clear(w);
    await u.type(w, "45");
    await u.click(within(form).getByRole("button", { name: "Save schedule" }));
    expect(convexMock.mutation("medications:upsert")).toHaveBeenCalledWith({
      objectId: "bp_meds",
      scheduleTimes: ["08:00", "12:00", "20:00"],
      windowMinutes: 45,
    });
    expect(await within(form).findByText("Saved the schedule for Blood pressure pills.")).toBeInTheDocument();
  });

  it("rejects an out-of-range window without saving", async () => {
    serve();
    renderAt("/medications");
    const u = userEvent.setup();
    const form = screen.getByRole("form", { name: "Blood pressure pills" });
    const w = within(form).getByLabelText("Window, in minutes");
    await u.clear(w);
    await u.type(w, "0");
    await u.click(within(form).getByRole("button", { name: "Save schedule" }));
    expect(within(form).getByRole("alert")).toHaveTextContent("The window must be a whole number of minutes from 5 to 240.");
    expect(convexMock.mutation("medications:upsert")).not.toHaveBeenCalled();
  });
});

describe("Timeline", () => {
  it("groups recent events by household-local day, newest first", () => {
    serve();
    renderAt("/timeline");
    expect(convexMock.queryCalls).toContainEqual({ name: "events:recent", args: { limit: 100 } });
    const today = screen.getByRole("heading", { name: "Today, Friday, October 23" }).closest("section")!;
    const items = within(today).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("5:04 PM");
    expect(items[0]).toHaveTextContent("Picked up");
    expect(items[0]).toHaveTextContent("Salt picked up from the center left spot.");
    const yesterday = screen.getByRole("heading", { name: "Yesterday, Thursday, October 22" }).closest("section")!;
    expect(yesterday).toHaveTextContent("Blood pressure pills picked up from the far right spot.");
    expect(today).toHaveTextContent("Put in a place");
    expect(today).toHaveTextContent("Keys put in the drawer.");
  });

  it("has an empty state", () => {
    const data = makeFixtures(NOW);
    serve({ ...data, events: [] });
    renderAt("/timeline");
    expect(screen.getByText(/Nothing recorded yet/)).toBeInTheDocument();
  });
});

describe("Trials", () => {
  it("shows raw counts per mode and labels a small sample as a pilot", () => {
    serve();
    renderAt("/trials");
    expect(screen.getByText("Pilot: 6 completed trials")).toBeInTheDocument();
    expect(screen.getByText(/3 with Earmark and 3 at baseline, by 2 testers/)).toBeInTheDocument();
    const row = (label: string) => screen.getByRole("rowheader", { name: label }).closest("tr")!;
    expect(row("Completed trials")).toHaveTextContent("Completed trials33");
    expect(row("Target found")).toHaveTextContent("3 of 3");
    expect(row("Target found")).toHaveTextContent("2 of 3");
    expect(row("Testers")).toHaveTextContent("Testers22");
    expect(row("Median time to find")).toHaveTextContent("11.1 s (over 3 finds)");
    expect(row("Median time to find")).toHaveTextContent("52.4 s (over 2 finds)");
    expect(row("Wrong picks")).toHaveTextContent("1 across 3 trials");
    expect(row("Wrong picks")).toHaveTextContent("4 across 3 trials");
    expect(document.body.textContent).not.toMatch(/%/);
    // The raw table has one row per trial.
    expect(screen.getAllByText(/Example tester/)).toHaveLength(6);
  });

  it("counts only completed trials and shows running ones as running", () => {
    const data = makeFixtures(NOW);
    const running: TrialRow = {
      trialId: "t-run",
      mode: "earmark",
      targetObjectId: "sugar",
      tester: "Example tester C",
      startedAt: NOW - 30,
      endedAt: null,
      secondsToFind: null,
      wrongPicks: 0,
      outcome: null,
    };
    serve({ ...data, trials: [...data.trials, running] });
    renderAt("/trials");
    expect(screen.getByText("Pilot: 6 completed trials")).toBeInTheDocument();
    expect(screen.getByText("1 trial is still running.")).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "5:04 PM" }).closest("tr")).toHaveTextContent("Running");
  });

  it("says plainly when there are no trials", () => {
    serve(makeFixtures(NOW, { trials: "none" }));
    renderAt("/trials");
    expect(screen.getByRole("heading", { name: "No trials recorded yet" })).toBeInTheDocument();
    expect(screen.queryByText(/Pilot/)).not.toBeInTheDocument();
  });
});

describe("Not connected", () => {
  it("explains the missing VITE_CONVEX_URL and offers the demo", () => {
    render(<App backend={null} mode={{ kind: "unconfigured", reason: "missing" }} />);
    expect(screen.getByRole("heading", { level: 1, name: "Not connected" })).toBeInTheDocument();
    expect(document.querySelector(".connection")).toHaveTextContent("Connection: Not connected");
    expect(screen.getByRole("link", { name: "See the dashboard with demo data" })).toHaveAttribute("href", "?demo=1");
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });
});
