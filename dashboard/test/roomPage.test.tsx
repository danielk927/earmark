/** The /room page in jsdom: label safety, bus URL, status pills, held keys, and axe. WebGL is absent here, so the 3D scene itself is not drawn. */
import axe from "axe-core";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RoomPage } from "../src/room/RoomPage";
import { setTag, tag } from "../src/room/scene3d";
import { busUnreachable, busUrl } from "../src/room/useBus";

class FakeSocket {
  static all: FakeSocket[] = [];
  static OPEN = 1;
  readyState = 1;
  sent: Record<string, unknown>[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(public url: string) {
    FakeSocket.all.push(this);
    queueMicrotask(() => this.onopen?.());
  }
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {}
  emit(msg: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
}

beforeEach(() => {
  FakeSocket.all = [];
  vi.stubGlobal("WebSocket", FakeSocket);
});
afterEach(() => vi.unstubAllGlobals());

const where = (protocol: string, hostname: string) => vi.stubGlobal("location", { protocol, hostname, pathname: "/room", search: "" });

describe("room labels", () => {
  it("shows an item name with markup as plain text", () => {
    const name = "<img src=x onerror=alert(1)>";
    const el = tag(name, "m3-item").element;
    expect(el.querySelector("img")).toBeNull();
    expect(el.textContent).toBe(name);
    setTag(el, name, "<b>1</b>");
    expect(el.querySelector("img, b")).toBeNull();
    expect(el.textContent).toBe(`${name}<b>1</b>`);
  });
});

describe("bus URL", () => {
  it("uses ws on http and wss on https", () => {
    where("http:", "localhost");
    expect(busUrl()).toBe("ws://127.0.0.1:8765");
    where("https:", "family.example.net");
    expect(busUrl()).toBe("wss://family.example.net:8765");
  });
  it("is unreachable only on a deployed https page", () => {
    where("https:", "family.example.net");
    expect(busUnreachable()).toBe(true);
    where("http:", "localhost");
    expect(busUnreachable()).toBe(false);
    where("http:", "192.168.1.20");
    expect(busUnreachable()).toBe(false);
  });
  it("says the room page only works on the demo Mac when deployed", () => {
    where("https:", "family.example.net");
    render(<RoomPage />);
    expect(screen.getByText(/only works on the demo Mac/)).toBeInTheDocument();
    expect(FakeSocket.all).toHaveLength(0);
  });
});

async function open() {
  render(<RoomPage />);
  await act(async () => {});
  return FakeSocket.all[0]!;
}
const pill = (name: RegExp) => screen.getByText(name).closest("li")!;

describe("room page", () => {
  it("shows status as words with a shape, and Phones can fail", async () => {
    const sock = await open();
    expect(pill(/^Phones:/)).toHaveTextContent("Phones: not connected");
    expect(pill(/^Hub:/)).toHaveTextContent("Hub: not connected");
    act(() => sock.emit({ type: "snapshot", space: { areas: [], spots: [] }, objects: [], states: [] }));
    expect(pill(/^Hub:/)).toHaveTextContent("Hub: connected");
    act(() => sock.emit({ type: "status", component: "locator", ok: false, detail: "not set up" }));
    expect(pill(/^Phones:/)).toHaveTextContent("Phones: no fix");
    expect(pill(/^Phones:/)).toHaveClass("bad");
    act(() => {
      sock.emit({ type: "status", component: "locator", ok: true, detail: "calibrated" });
      sock.emit({ type: "listener_pose", position: [0, 1, 1.5], quality: "ok", beacons_heard: 3, source: "beacons" });
    });
    expect(pill(/^Phones:/)).toHaveTextContent("Phones: tracking");
    expect(within(pill(/^Phones:/)).getByText("✓")).toBeInTheDocument();
  });

  it("marks the chosen view with aria-pressed", async () => {
    await open();
    const u = userEvent.setup();
    expect(screen.getByRole("button", { name: "Angle" })).toHaveAttribute("aria-pressed", "true");
    await u.click(screen.getByRole("button", { name: "Top" }));
    expect(screen.getByRole("button", { name: "Top" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Angle" })).toHaveAttribute("aria-pressed", "false");
  });

  it("stops the simulated walk when the window loses focus", async () => {
    vi.useFakeTimers();
    try {
      const sock = await open();
      await act(async () => {
        screen.getByRole("checkbox").click();
      });
      act(() => {
        window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp" }));
        vi.advanceTimersByTime(200);
      });
      const y = () => (sock.sent.filter((m) => m.type === "listener_pose").at(-1)!.position as number[])[1]!;
      act(() => vi.advanceTimersByTime(300));
      const moved = y();
      expect(moved).toBeGreaterThan(0);
      act(() => {
        window.dispatchEvent(new Event("blur"));
        vi.advanceTimersByTime(300);
      });
      const afterBlur = y();
      act(() => vi.advanceTimersByTime(600));
      expect(y()).toBe(afterBlur);
    } finally {
      vi.useRealTimers();
    }
  });

  it("has no axe violations", async () => {
    document.title = "Earmark room"; // index.html sets this in the real page
    await open();
    const result = await axe.run(document, { rules: { "color-contrast": { enabled: false }, "color-contrast-enhanced": { enabled: false } } });
    expect(result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`)).toEqual([]);
  });
});
