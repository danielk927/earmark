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

describe("Live map: UWB anchors and the person", () => {
  const OLD_CAPTION = /The listener sits at the bottom/;

  it("draws the anchors and the person, with a caption and a text list that say the same", () => {
    serve();
    renderAt("/");
    expect(screen.getByText("Seen from above. The dot is the person; the triangles are the UWB anchors.")).toBeInTheDocument();
    expect(screen.queryByText(OLD_CAPTION)).not.toBeInTheDocument();

    const map = screen.getByRole("img", { name: /Map of the spots/ });
    expect(map).toHaveAccessibleName(expect.stringContaining("UWB Reader/Emitter 1: online, 2.4 m from the person."));
    expect(map).toHaveAccessibleName(expect.stringContaining("The person: walking toward the counter."));
    // On the picture itself: a label and a status in words for every anchor, and the person's mode.
    expect([...map.querySelectorAll(".anchor-name")].map((e) => e.textContent)).toEqual([
      "UWB Reader/Emitter 1",
      "UWB Reader/Emitter 2",
      "UWB Reader/Emitter 3",
    ]);
    expect([...map.querySelectorAll(".anchor-state")].map((e) => e.textContent)).toEqual(Array(3).fill("✓ Online"));
    expect(map.querySelector(".person-label")).toHaveTextContent("Walking toward");

    const list = screen.getByRole("heading", { name: "The person and UWB anchors" }).closest("section")!;
    expect(within(list).getByText("The person: walking toward the counter")).toBeInTheDocument();
    expect(within(list).getByText("UWB Reader/Emitter 1: online, 2.4 m from the person")).toBeInTheDocument();
    expect(within(list).getByText("UWB Reader/Emitter 3: online, 1.1 m from the person")).toBeInTheDocument();
    expect(within(list).getByText(/Position from the UWB anchors, updated just now\./)).toBeInTheDocument();
  });

  it("shows an offline anchor with an icon and words, never color alone", () => {
    const data = makeFixtures(NOW);
    data.liveMap.anchors = data.liveMap.anchors.map((a) =>
      a.anchorId === "uwb_2" ? { ...a, online: false, lastDistanceM: null, lastSeenT: NOW - 600 } : a,
    );
    serve(data);
    renderAt("/");
    const map = screen.getByRole("img", { name: /Map of the spots/ });
    expect(map).toHaveAccessibleName(expect.stringContaining("UWB Reader/Emitter 2: offline."));
    expect([...map.querySelectorAll(".anchor-state")].map((e) => e.textContent)).toContain("✕ Offline");
    expect(map.querySelectorAll(".anchor-off .anchor-shape")).toHaveLength(1);

    const list = screen.getByRole("heading", { name: "The person and UWB anchors" }).closest("section")!;
    const item = within(list).getByText("UWB Reader/Emitter 2: offline").closest("li")!;
    expect(item.querySelector("svg.icon")).not.toBeNull();
    expect(item).toHaveTextContent("Last heard 10 min ago.");
  });

  it.each([
    ["frozen", "At the counter"],
    ["lost", "Location lost"],
    ["fixed", "Seated at the listening spot"],
  ] as const)("says the %s mode in words", (mode, words) => {
    const data = makeFixtures(NOW);
    data.liveMap.wearer = { ...data.liveMap.wearer!, mode };
    serve(data);
    renderAt("/");
    expect(screen.getByRole("img", { name: /Map of the spots/ })).toHaveAccessibleName(expect.stringContaining(`The person: ${words.toLowerCase()}.`));
    const list = screen.getByRole("heading", { name: "The person and UWB anchors" }).closest("section")!;
    expect(within(list).getByText(`The person: ${words.toLowerCase()}`)).toBeInTheDocument();
    if (mode === "lost") expect(list).toHaveTextContent("Showing the last known position.");
  });

  it("keeps the old caption and hides the list when there are no anchors or person", () => {
    const data = makeFixtures(NOW);
    data.liveMap.anchors = [];
    data.liveMap.wearer = null;
    serve(data);
    renderAt("/");
    expect(screen.getByText(OLD_CAPTION)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "The person and UWB anchors" })).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Map of the spots/ }).querySelector(".person, .anchor")).toBeNull();
  });

  it("says when nobody is being tracked but anchors exist", () => {
    const data = makeFixtures(NOW);
    data.liveMap.wearer = null;
    serve(data);
    renderAt("/");
    expect(screen.getByText("The person: not being tracked right now")).toBeInTheDocument();
  });

  it("announces an anchor going offline, but never the person's movement", () => {
    const data = serve();
    renderAt("/");
    const live = document.querySelector('[aria-live="polite"]')!;
    act(() => convexMock.setQuery("dashboard:liveMap", { ...data.liveMap, wearer: { ...data.liveMap.wearer!, position: [0.1, -1.2, 0], t: NOW + 1 } }));
    expect(live).toHaveTextContent("");
    const anchors = data.liveMap.anchors.map((a) => (a.anchorId === "uwb_1" ? { ...a, online: false } : a));
    act(() => convexMock.setQuery("dashboard:liveMap", { ...data.liveMap, anchors }));
    expect(live).toHaveTextContent("UWB Reader/Emitter 1 is offline.");
  });
});

