import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "edge-runtime",
    include: ["convex/**/*.test.ts"],
    server: { deps: { inline: ["convex-test"] } },
    // Node 25+ enables Web Storage by default and warns when the edge-runtime
    // environment probes `localStorage`; nothing here uses it.
    execArgv: ["--no-experimental-webstorage"],
  },
});
