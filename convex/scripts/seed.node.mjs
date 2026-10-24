#!/usr/bin/env node
// Seed or reset the Convex deployment from config/space.json and config/objects.seed.json.
//   node convex/scripts/seed.node.mjs seed   [extra `npx convex run` flags]
//   node convex/scripts/seed.node.mjs reset  [extra `npx convex run` flags]
// The file name has two dots so the Convex bundler skips it (it is a Node script, not a Convex module).
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const [mode, ...extra] = process.argv.slice(2);
if (mode !== "seed" && mode !== "reset") {
  console.error("usage: seed.node.mjs seed|reset [convex run flags]");
  process.exit(2);
}
const root = fileURLToPath(new URL("../../", import.meta.url));
const read = (p) => JSON.parse(readFileSync(new URL(p, `file://${root}`), "utf8"));
const args = JSON.stringify({ space: read("config/space.json"), registry: read("config/objects.seed.json") });
const r = spawnSync("npx", ["convex", "run", `seed:${mode}`, args, ...extra], { cwd: root, stdio: "inherit" });
process.exit(r.status ?? 1);
