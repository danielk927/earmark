import { cronJobs } from "convex/server";
import { internal } from "./_generated/api";

const crons = cronJobs();

// Dose statuses depend on the clock (pending -> missed), and queries may not read it.
crons.interval("recompute today's and yesterday's doses", { minutes: 1 }, internal.doses.recomputeRecent, {});

// UTC cron string; the target picks the previous household-local day itself.
crons.cron("daily summary for the previous local day", "5 * * * *", internal.summaries.buildYesterday, {});

// Privacy backstop for photos uploaded but never sent for a suggestion.
crons.interval("delete abandoned photos", { minutes: 5 }, internal.labeling.sweepStalePhotos, {});

export default crons;
