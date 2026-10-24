import { act, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { makeFixtures, UNKNOWN_TAG } from "../src/data/fixtures";
import { convexMock } from "./convexMock";
import { NOW, renderAt, serve } from "./harness";

describe("Live map", () => {
  it("draws the map with a text description and a table with the same facts", () => {
    serve();
    renderAt("/");
    expect(screen.getByRole("heading", { level: 1, name: "Live map" })).toBeInTheDocument();

    const map = screen.getByRole("img", { name: /Map of the spots/ });
    expect(map).toHaveAccessibleName(expect.stringContaining("Center right spot: sugar."));
    expect(map).toHaveAccessibleName(expect.stringContaining("Far left spot: a new unlabeled item."));
    expect(map).toHaveAccessibleName(expect.stringContaining("Keys: near the hub receiver, middle range."));

    const table = screen.getByRole("table");
    const keys = within(table).getByRole("rowheader", { name: "Keys" }).closest("tr")!;
    expect(keys).toHaveTextContent("Roaming");
    expect(keys).toHaveTextContent("Near the hub receiver, middle range");
    const sugar = within(table).getByRole("rowheader", { name: "Sugar" }).closest("tr")!;
    expect(sugar).toHaveTextContent("On a spot");
    expect(sugar).toHaveTextContent("The center right spot (its home)");
    const pepper = within(table).getByRole("rowheader", { name: "Pepper" }).closest("tr")!;
    expect(pepper).toHaveTextContent("Missing");
  });

  it("lists held and missing items beside the map", () => {
    serve();
    renderAt("/");
    const off = screen.getByRole("heading", { name: "Not on a spot" }).closest("section")!;
    expect(within(off).getByText("Salt")).toBeInTheDocument();
    expect(within(off).getByText("Picked up")).toBeInTheDocument();
    expect(within(off).getByText(/Off its spot\. Home is the center left spot\./)).toBeInTheDocument();
    expect(within(off).getByText("Pepper")).toBeInTheDocument();
    expect(within(off).queryByText("Sugar")).not.toBeInTheDocument();
  });

  it("points an unlabeled tag straight at labeling", () => {
    serve();
    renderAt("/");
    expect(screen.getByText("New item on the far left spot")).toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: "Label this item" });
    expect(links.length).toBeGreaterThan(0);
    for (const l of links) expect(l).toHaveAttribute("href", `/items?label=${UNKNOWN_TAG}`);
  });

  it("announces changes politely as they arrive", () => {
    const data = serve();
    renderAt("/");
    const live = document.querySelector('[aria-live="polite"]')!;
    expect(live).toHaveTextContent("");

    const states = data.liveMap.states.map((s) =>
      s.objectId === "sugar" ? { ...s, status: "held" as const, spot: null, position: null, t: NOW + 1 } : s,
    );
    act(() => convexMock.setQuery("dashboard:liveMap", { ...data.liveMap, states }));
    expect(live).toHaveTextContent("Sugar picked up from the center right spot.");
    expect(screen.getByRole("heading", { name: "Recent changes" }).closest("section")).toHaveTextContent(
      "Sugar picked up from the center right spot.",
    );
  });

  it("shows a loading state until the query answers", () => {
    renderAt("/");
    expect(screen.getByText("Loading the live map...")).toHaveAttribute("role", "status");
  });

  it("shows the household name and live connection", () => {
    serve(makeFixtures(NOW));
    renderAt("/");
    expect(screen.getByText("Demo household")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
  });
});
