// Screenshots every page against the real Convex deployment the dev server points at.
// Usage: npm run dev (with VITE_CONVEX_URL), then `node e2e/live.mjs [baseUrl] [outDir]`.
// Fails on console errors or pages that never leave their loading state.
import { chromium } from "playwright";

const base = process.argv[2] ?? "http://localhost:5173";
const out = process.argv[3] ?? "docs/screenshots/live/";
const pages = [
  { name: "live-map", path: "/", ready: "Every item, as a list" },
  { name: "items", path: "/items", ready: "Your items" },
  { name: "medications", path: "/medications", ready: "Schedules" },
  { name: "timeline", path: "/timeline", ready: "Showing the latest" },
  { name: "trials", path: "/trials", ready: "Trials" },
];

const browser = await chromium.launch();
let failed = false;
for (const theme of ["light", "dark"]) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: theme });
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));
  for (const p of pages) {
    await page.goto(base + p.path);
    try {
      await page.getByText(p.ready, { exact: false }).first().waitFor({ timeout: 8000 });
    } catch {
      console.error(`${p.name} (${theme}): never showed "${p.ready}"`);
      failed = true;
    }
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${out}${p.name}-${theme}.png`, fullPage: true });
  }
  if (errors.length) {
    console.error(`console errors (${theme}):\n  ${errors.join("\n  ")}`);
    failed = true;
  }
  await ctx.close();
}
await browser.close();
console.log(failed ? "FAILED" : `ok: screenshots in ${out}`);
process.exit(failed ? 1 : 0);
