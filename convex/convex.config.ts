import { defineApp } from "convex/server";
import { v } from "convex/values";

/**
 * Deployment environment variables (set with `npx convex env set NAME value`).
 * All optional so a fresh deployment pushes before they are set; without the
 * secrets every HTTP route answers 401, and without ANTHROPIC_API_KEY photo
 * suggestions fail with a clear message.
 */
const app = defineApp({
  env: {
    EARMARK_HUB_SECRET: v.optional(v.string()),
    EARMARK_READ_SECRET: v.optional(v.string()),
    ANTHROPIC_API_KEY: v.optional(v.string()),
    ANTHROPIC_BASE_URL: v.optional(v.string()),
    ANTHROPIC_VISION_MODEL: v.optional(v.string()),
  },
});

export default app;
