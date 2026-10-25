import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { compare, initialState, reduce, roomSize, simulatorSelect, type RoomState } from "../src/room/model";
import { PositioningCard } from "../src/room/RoomPage";

const snapshot = {
  type: "snapshot",
  space: { anchors: [
    { anchor: "uwb_1", label: "Fixed phone 1", position: [-1.2, 1.0, 1.1] },
    { anchor: "uwb_2", label: "Fixed phone 2", position: [1.3, 1.0, 1.1] },
    { anchor: "uwb_3", label: "Fixed phone 3", position: [0, -2.6, 1.1] },
  ] },
  objects: [], states: [],
};
const fix = (x: number, y: number, extra: Record<string, unknown> = {}) => ({ position: [x, y, 1.5], quality: "ok", source: "uwb", age_s: 0.1, ...extra });
const pos = (active: string, uwb: unknown, sound: unknown) => ({ type: "positioning", active, uwb, sound, t: 1 });
const run = (...msgs: Record<string, unknown>[]): RoomState =>
  msgs.reduce((s, m, i) => reduce(s, m as { type: string }, 100 + i), initialState());

describe("positioning in the room model", () => {
  it("takes the fixed phones from the snapshot and sizes the room from them", () => {
    const s = run(snapshot);
    expect(s.phones.map((p) => p.label)).toEqual(["Fixed phone 1", "Fixed phone 2", "Fixed phone 3"]);
    expect(roomSize(s.phones, s.places)).toEqual({ w: 3.6, d: 6.2 });
    expect(roomSize([], [])).toEqual({ w: 3.5, d: 3.5 });
  });

  it("reduces positioning, with null for a system that has no pose", () => {
    const s = run(pos("sound", null, fix(1, 1, { source: "beacons" })));
    expect(s.positioning?.active).toBe("sound");
    expect(s.positioning?.uwb).toBeNull();
    expect(s.positioning?.sound?.position).toEqual([1, 1, 1.5]);
  });

  it("reports the horizontal gap only when both are live", () => {
    const s = run(pos("uwb", fix(0, 0), fix(0.3, 0.4, { source: "beacons" })));
    expect(compare(s.positioning, 100).gap).toBeCloseTo(0.5, 5);
    expect(compare(s.positioning, 104).gap).toBeNull(); // both stale after 2 s
    const lost = run(pos("uwb", fix(0, 0), fix(1, 1, { quality: "lost" })));
    expect(compare(lost.positioning, 100).gap).toBeNull();
    expect(compare(lost.positioning, 100).lines.sound).toContain("lost");
    expect(compare(run(pos("uwb", null, fix(1, 1))).positioning, 100).lines.uwb).toBe("UWB: not tracking");
  });

  it("logs tap results", () => {
    expect(run({ type: "tap_position", ok: true, position: [0, 0, 1], source: "uwb", t: 1 }).log[0]!.text).toBe("Marked by tap (UWB)");
    expect(run({ type: "tap_position", ok: false, source: "none", t: 1 }).log[0]!.text).toBe("Tap ignored: UWB isn't tracking");
  });
});

describe("UWB / Sound switch", () => {
  it("reflects the hub's active system and sends the other on click", () => {
    const onSelect = vi.fn();
    const s = run(pos("uwb", fix(0, 0), null));
    render(<PositioningCard state={s} onSelect={onSelect} />);
    expect(screen.getByRole("radio", { name: "UWB" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Sound" })).not.toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "Sound" }));
    expect(onSelect).toHaveBeenCalledWith("sound");
  });
});

describe("the walking simulator", () => {
  it("switches the audio to Sound when it starts, because its poses are sound-side", () => {
    expect(simulatorSelect(null, 5)).toEqual({ type: "positioning_select", active: "sound", t: 5 });
    expect(simulatorSelect(run(pos("uwb", null, null)).positioning, 5)).toMatchObject({ active: "sound" });
    expect(simulatorSelect(run(pos("sound", null, null)).positioning, 5)).toBeNull();
  });
});
