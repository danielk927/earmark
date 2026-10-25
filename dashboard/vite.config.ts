/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv, searchForWorkspaceRoot } from "vite";
import react from "@vitejs/plugin-react";

const dashboardDir = fileURLToPath(new URL(".", import.meta.url));
const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const contractsDir = fileURLToPath(new URL("../contracts/ts", import.meta.url));

export default defineConfig(({ mode }) => {
  // VITE_CONVEX_URL (shell or dashboard/.env*) wins. Otherwise fall back to the CONVEX_URL that
  // `npx convex dev` writes to the repo-root .env.local, so local dev needs no copy step.
  // Only CONVEX_URL is read from the root; envPrefix is not widened (see docs/sponsors/vendor-notes/convex.md).
  const own = loadEnv(mode, dashboardDir, "VITE_");
  const root = loadEnv(mode, repoRoot, "CONVEX_URL");
  const convexUrl = own.VITE_CONVEX_URL ?? root.CONVEX_URL ?? "";

  return {
    plugins: [react()],
    define: mode === "test" ? {} : { "import.meta.env.VITE_CONVEX_URL": JSON.stringify(convexUrl) },
    resolve: {
      alias: { "@contracts": contractsDir },
      // contracts/ts/convexFunctions.ts imports "convex/server"; make it resolve to this package's copy.
      dedupe: ["convex", "react", "react-dom"],
    },
    server: {
      fs: { allow: [searchForWorkspaceRoot(process.cwd()), contractsDir] },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./test/setup.ts"],
      include: ["test/**/*.test.{ts,tsx}"],
      css: false,
    },
  };
});
