/** Contrast of the design tokens in both themes (WCAG 2.x relative luminance). */
/// <reference types="node" />
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Vitest runs from dashboard/. (A ?raw import comes back empty because tests skip CSS processing.)
const css = readFileSync(resolve(process.cwd(), "src/styles/tokens.css"), "utf8");

const tokens: Record<string, { light: string; dark: string }> = {};
for (const m of css.matchAll(/--([\w-]+):\s*light-dark\(\s*(#[0-9a-f]{6})\s*,\s*(#[0-9a-f]{6})\s*\)/gi)) {
  tokens[m[1]!] = { light: m[2]!, dark: m[3]! };
}

function luminance(hex: string) {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

// [foreground, background, minimum]. 7 = AAA body text, 4.5 = AA text, 3 = non-text (borders, icons, focus).
const pairs: [string, string, number][] = [
  ...["paper", "surface", "field"].flatMap((bg): [string, string, number][] => [
    ["ink", bg, 7],
    ["ink-soft", bg, 7],
    ["accent", bg, 7],
    ["warn", bg, 7],
    ["bad", bg, 7],
    ["idle", bg, 7],
    ["ok", bg, bg === "field" ? 4.5 : 7],
    ["line", bg, 3],
  ]),
  ["accent-ink", "accent", 7],
  ["ink", "accent-wash", 7],
  ["accent", "accent-wash", 7],
  ["ink", "ok-wash", 7],
  ["ok", "ok-wash", 7],
  ["ink", "warn-wash", 7],
  ["warn", "warn-wash", 7],
  ["ink", "bad-wash", 7],
  ["bad", "bad-wash", 7],
  ["ink-soft", "bad-wash", 7],
  ["ink-soft", "warn-wash", 7],
  ["ink-soft", "accent-wash", 7],
  ["paper", "ink", 7], // primary button hover
];

describe("design tokens", () => {
  it("parses every token used below", () => {
    for (const [fg, bg] of pairs) {
      expect(tokens[fg], fg).toBeDefined();
      expect(tokens[bg], bg).toBeDefined();
    }
  });

  describe.each(["light", "dark"] as const)("%s theme", (theme) => {
    it.each(pairs)("%s on %s is at least %s:1", (fg, bg, min) => {
      expect(contrast(tokens[fg]![theme], tokens[bg]![theme])).toBeGreaterThanOrEqual(min);
    });
  });
});
