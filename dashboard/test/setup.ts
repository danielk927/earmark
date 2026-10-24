import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { convexMock } from "./convexMock";

vi.mock("convex/react", () => import("./convexMock"));

// jsdom has no object URLs; the photo preview only needs a string.
URL.createObjectURL = vi.fn(() => "blob:preview");
URL.revokeObjectURL = vi.fn();

// index.html sets lang="en"; jsdom's blank document does not.
document.documentElement.lang = "en";

beforeEach(() => {
  convexMock.reset();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
