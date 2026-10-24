import { describe, expect, test } from "vitest";
import {
  addDays,
  formatLocalIso,
  isValidDate,
  isValidTimeZone,
  localDate,
  localHHMM,
  longDateLabel,
  offsetMinutes,
  startOfLocalDay,
  zonedToUnix,
} from "./time";

const LA = "America/Los_Angeles";

describe("formatLocalIso", () => {
  test("matches the contract examples", () => {
    expect(formatLocalIso(1761350400.12, LA)).toBe("2025-10-24T17:00:00.120-07:00");
    expect(formatLocalIso(1761318000, LA)).toBe("2025-10-24T08:00:00-07:00");
    expect(formatLocalIso(1761274800, LA)).toBe("2025-10-23T20:00:00-07:00");
  });
  test("uses the standard-time offset in winter and +00:00 for UTC", () => {
    expect(formatLocalIso(Date.UTC(2025, 11, 1, 16) / 1000, LA)).toBe("2025-12-01T08:00:00-08:00");
    expect(formatLocalIso(Date.UTC(2025, 11, 1, 16) / 1000, "UTC")).toBe("2025-12-01T16:00:00+00:00");
    expect(formatLocalIso(Date.UTC(2025, 11, 1, 16) / 1000, "Asia/Kolkata")).toBe("2025-12-01T21:30:00+05:30");
  });
});

describe("zonedToUnix", () => {
  test("round-trips ordinary times", () => {
    expect(zonedToUnix("2025-10-24", "08:00", LA)).toBe(1761318000);
    expect(zonedToUnix("2025-10-23", "20:00", LA)).toBe(1761274800);
  });
  test("spring forward (2025-03-09): the day before is PST, the day after PDT", () => {
    expect(formatLocalIso(zonedToUnix("2025-03-08", "08:00", LA), LA)).toBe("2025-03-08T08:00:00-08:00");
    expect(formatLocalIso(zonedToUnix("2025-03-09", "08:00", LA), LA)).toBe("2025-03-09T08:00:00-07:00");
    expect(formatLocalIso(zonedToUnix("2025-03-09", "20:00", LA), LA)).toBe("2025-03-09T20:00:00-07:00");
    // 08:00 to 08:00 across the transition is 23 hours.
    expect(zonedToUnix("2025-03-09", "08:00", LA) - zonedToUnix("2025-03-08", "08:00", LA)).toBe(23 * 3600);
  });
  test("a skipped time (02:30 on spring-forward day) resolves to 03:30 PDT", () => {
    expect(formatLocalIso(zonedToUnix("2025-03-09", "02:30", LA), LA)).toBe("2025-03-09T03:30:00-07:00");
  });
  test("fall back (2025-11-02): a repeated time resolves to the earlier instant", () => {
    expect(formatLocalIso(zonedToUnix("2025-11-02", "01:30", LA), LA)).toBe("2025-11-02T01:30:00-07:00");
    expect(formatLocalIso(zonedToUnix("2025-11-02", "08:00", LA), LA)).toBe("2025-11-02T08:00:00-08:00");
    expect(zonedToUnix("2025-11-02", "08:00", LA) - zonedToUnix("2025-11-01", "08:00", LA)).toBe(25 * 3600);
  });
  test("local midnight and days", () => {
    expect(formatLocalIso(startOfLocalDay("2025-03-09", LA), LA)).toBe("2025-03-09T00:00:00-08:00");
    expect(startOfLocalDay("2025-03-10", LA) - startOfLocalDay("2025-03-09", LA)).toBe(23 * 3600);
    expect(startOfLocalDay("2025-11-03", LA) - startOfLocalDay("2025-11-02", LA)).toBe(25 * 3600);
  });
});

describe("helpers", () => {
  test("local date and time", () => {
    expect(localDate(1761350400.12, LA)).toBe("2025-10-24");
    expect(localDate(Date.UTC(2025, 9, 25, 6, 59) / 1000, LA)).toBe("2025-10-24");
    expect(localDate(Date.UTC(2025, 9, 25, 7, 0) / 1000, LA)).toBe("2025-10-25");
    expect(localHHMM(1761318900, LA)).toBe("08:15");
    expect(localHHMM(Date.UTC(2025, 9, 25, 7, 0) / 1000, LA)).toBe("00:00");
  });
  test("offsets", () => {
    expect(offsetMinutes(Date.UTC(2025, 6, 1), LA)).toBe(-420);
    expect(offsetMinutes(Date.UTC(2025, 0, 1), LA)).toBe(-480);
  });
  test("dates", () => {
    expect(addDays("2025-10-24", -1)).toBe("2025-10-23");
    expect(addDays("2025-03-01", -1)).toBe("2025-02-28");
    expect(addDays("2024-12-31", 1)).toBe("2025-01-01");
    expect(isValidDate("2025-02-29")).toBe(false);
    expect(isValidDate("2024-02-29")).toBe(true);
    expect(isValidDate("2025-1-01")).toBe(false);
    expect(longDateLabel("2025-10-23")).toBe("Thursday, October 23");
    expect(isValidTimeZone(LA)).toBe(true);
    expect(isValidTimeZone("Mars/Olympus")).toBe(false);
  });
});
