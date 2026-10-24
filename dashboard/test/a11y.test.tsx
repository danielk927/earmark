/**
 * axe-core on every page in both themes, in jsdom. jsdom has no layout, so color contrast is checked
 * by tokens.test.ts here and by e2e/check.mjs in real Chromium.
 */
import axe from "axe-core";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "../src/App";
import { renderAt, serve, YESTERDAY } from "./harness";

async function violations() {
  const result = await axe.run(document, {
    rules: { "color-contrast": { enabled: false }, "color-contrast-enhanced": { enabled: false } },
  });
  return result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`);
}

const routes = ["/", "/items", "/medications", `/medications?date=${YESTERDAY}`, "/timeline", "/trials", "/nowhere"];

describe.each(["light", "dark"])("axe, %s theme", (theme) => {
  it.each(routes)("%s has no violations", async (route) => {
    document.documentElement.setAttribute("data-theme", theme);
    serve();
    renderAt(route);
    await screen.findAllByRole("heading", { level: 1 });
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(await violations()).toEqual([]);
  });

  it("the item editor and delete confirmation have no violations", async () => {
    document.documentElement.setAttribute("data-theme", theme);
    serve();
    renderAt("/items");
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Edit Salt" }));
    expect(await violations()).toEqual([]);
    await u.click(screen.getByRole("button", { name: "Delete Salt" }));
    expect(await violations()).toEqual([]);
  });

  it("the photo panel has no violations", async () => {
    document.documentElement.setAttribute("data-theme", theme);
    serve();
    renderAt("/items");
    await userEvent.setup().click(screen.getByRole("button", { name: "Start from a photo" }));
    expect(await violations()).toEqual([]);
  });

  it("the not-connected page has no violations", async () => {
    document.documentElement.setAttribute("data-theme", theme);
    render(<App backend={null} mode={{ kind: "unconfigured", reason: "missing" }} />);
    expect(await violations()).toEqual([]);
  });
});

describe("keyboard and structure", () => {
  it("starts with a skip link to main, and has banner, navigation, main, and footer landmarks", () => {
    serve();
    renderAt("/");
    const skip = screen.getByRole("link", { name: "Skip to main content" });
    expect(skip).toHaveAttribute("href", "#main");
    expect(document.body.querySelector("a")).toBe(skip);
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });

  it("marks the current page in the navigation", () => {
    serve();
    renderAt("/timeline");
    expect(screen.getByRole("link", { name: "Timeline" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Items" })).not.toHaveAttribute("aria-current");
  });

  it("moves focus to the new page's heading after navigating", async () => {
    serve();
    renderAt("/");
    await userEvent.setup().click(screen.getByRole("link", { name: "Trials" }));
    expect(screen.getByRole("heading", { level: 1, name: "Trials" })).toHaveFocus();
    expect(document.title).toBe("Trials - Earmark");
  });

  it("theme choice applies and persists", async () => {
    serve();
    renderAt("/");
    const u = userEvent.setup();
    await u.click(screen.getByRole("radio", { name: "Dark" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(localStorage.getItem("earmark.theme")).toBe("dark");
    await u.click(screen.getByRole("radio", { name: "System" }));
    expect(document.documentElement).not.toHaveAttribute("data-theme");
    expect(localStorage.getItem("earmark.theme")).toBeNull();
  });
});
