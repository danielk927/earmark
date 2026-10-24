// Real-browser check of the built dashboard in demo mode:
// axe-core (WCAG 2.2 A/AA + best practices) on every page in light and dark themes, reflow at
// 320 CSS px and at 200% zoom, the theme toggle persisting, and screenshots for docs/screenshots/.
// Run with `npm run e2e` (builds first). Uses Playwright's Chromium.
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { preview } from "vite";
import { chromium } from "playwright";
import { AxeBuilder } from "@axe-core/playwright";

const root = fileURLToPath(new URL("..", import.meta.url));
const shots = fileURLToPath(new URL("../docs/screenshots/", import.meta.url));
const PORT = 4317;
// A fixed household-local time (Friday 5:05 PM in Los Angeles) so screenshots are repeatable.
const NOW = new Date("2026-10-23T17:05:00-07:00");
const YESTERDAY = "2026-10-22";

const pages = [
  { name: "live-map", path: "/?demo=1", ready: "Every item, as a list" },
  { name: "items", path: "/items?demo=1", ready: "Your items (5)" },
  { name: "medications", path: "/medications?demo=1", ready: "Schedules" },
  { name: "medications-yesterday", path: `/medications?demo=1&date=${YESTERDAY}`, ready: "Schedules" },
  { name: "timeline", path: "/timeline?demo=1", ready: "Showing the latest" },
  { name: "trials", path: "/trials?demo=1", ready: "Every trial" },
  { name: "not-connected", path: "/", ready: "Not connected" },
];

const server = await preview({ root, preview: { port: PORT, strictPort: true }, logLevel: "warn" });
const base = `http://localhost:${PORT}`;
const browser = await chromium.launch();
const failures = [];
const aaaNotes = [];

async function open(context, path, ready) {
  const page = await context.newPage();
  await page.clock.setFixedTime(NOW);
  await page.goto(base + path);
  await page.getByText(ready, { exact: false }).first().waitFor();
  await page.evaluate(() => document.fonts.ready);
  return page;
}

async function axe(page, label) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"])
    .analyze();
  for (const v of result.violations) {
    failures.push(`${label}: axe ${v.id} (${v.impact}) - ${v.help} - ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
  }
  const aaa = await new AxeBuilder({ page }).withRules(["color-contrast-enhanced"]).analyze();
  for (const v of aaa.violations) {
    aaaNotes.push(`${label}: ${v.nodes.length} node(s) below AAA 7:1 - ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(", ")}`);
  }
  return result.violations.length;
}

async function overflow(page, label) {
  const o = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
  if (o.sw > o.cw + 1) failures.push(`${label}: horizontal overflow (${o.sw}px content in ${o.cw}px viewport)`);
}

try {
  await mkdir(shots, { recursive: true });
  for (const theme of ["light", "dark"]) {
    const desktop = await browser.newContext({ colorScheme: theme, viewport: { width: 1280, height: 900 } });
    const phone = await browser.newContext({ colorScheme: theme, viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
    const reflow = await browser.newContext({ colorScheme: theme, viewport: { width: 320, height: 640 } });
    const zoom200 = await browser.newContext({ colorScheme: theme, viewport: { width: 640, height: 450 }, deviceScaleFactor: 2 });
    for (const p of pages) {
      const page = await open(desktop, p.path, p.ready);
      const n = await axe(page, `${p.name} ${theme} desktop`);
      await page.screenshot({ path: `${shots}${p.name}-${theme}.png`, fullPage: true });
      await page.close();

      const mobile = await open(phone, p.path, p.ready);
      await axe(mobile, `${p.name} ${theme} phone`);
      await overflow(mobile, `${p.name} ${theme} phone`);
      if (["live-map", "items", "medications-yesterday"].includes(p.name)) {
        await mobile.screenshot({ path: `${shots}${p.name}-${theme}-phone.png`, fullPage: true });
      }
      await mobile.close();

      for (const [ctx, label] of [[reflow, "320px"], [zoom200, "200% zoom"]]) {
        const pg = await open(ctx, p.path, p.ready);
        await overflow(pg, `${p.name} ${theme} ${label}`);
        await pg.close();
      }
      console.log(`${p.name} ${theme}: ${n} axe violations on desktop`);
    }

    // Photo labeling: choose a photo, wait for the suggestion form, check it, screenshot it.
    const page = await open(desktop, "/items?demo=1", "Your items (5)");
    await page.getByRole("button", { name: "Start from a photo" }).click();
    await page.locator('input[type="file"]:not([capture])').setInputFiles({
      name: "item.png",
      mimeType: "image/png",
      buffer: await page.evaluate(async () => {
        const c = document.createElement("canvas");
        c.width = 320;
        c.height = 240;
        const g = c.getContext("2d");
        g.fillStyle = "#e0a100";
        g.fillRect(0, 0, 320, 240);
        g.fillStyle = "#6a2a70";
        g.beginPath();
        g.arc(160, 120, 70, 0, Math.PI * 2);
        g.fill();
        const b = await new Promise((r) => c.toBlob(r, "image/png"));
        return Array.from(new Uint8Array(await b.arrayBuffer()));
      }).then((a) => Buffer.from(a)),
    });
    await page.getByRole("heading", { name: "Check the suggestion" }).waitFor();
    await page.getByText("Photo deleted.").waitFor();
    await axe(page, `photo-suggestion ${theme} desktop`);
    await page.locator(".add-block").screenshot({ path: `${shots}photo-suggestion-${theme}.png` });
    await page.close();

    for (const c of [desktop, phone, reflow, zoom200]) await c.close();
  }

  // The manual theme choice wins over the system setting and survives a reload.
  const ctx = await browser.newContext({ colorScheme: "light" });
  const page = await open(ctx, "/?demo=1", "Every item, as a list");
  await page.getByLabel("Dark").check({ force: true });
  await page.reload();
  await page.getByText("Every item, as a list").waitFor();
  const theme = await page.evaluate(() => document.documentElement.dataset.theme);
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  if (theme !== "dark" || bg !== "rgb(15, 26, 29)") failures.push(`theme toggle did not persist (data-theme=${theme}, background=${bg})`);
  else console.log("theme toggle: dark persisted across reload");
  await ctx.close();
} finally {
  await browser.close();
  await new Promise((r) => server.httpServer.close(r));
}

if (aaaNotes.length) {
  console.log("\nAAA (7:1) contrast notes, informational:");
  for (const n of aaaNotes) console.log("  " + n);
}
if (failures.length) {
  console.error(`\n${failures.length} failure(s):`);
  for (const f of failures) console.error("  " + f);
  process.exit(1);
}
console.log("\nAll real-browser checks passed. Screenshots in docs/screenshots/.");
