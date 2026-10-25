import { describe, expect, it } from "vitest";
import { MAT, describeOffset, initialOffset, listenerPosition, manualTarget, nudge } from "../src/operator/control";
import { addEvent, type OpEvent } from "../src/operator/events";

describe("operator control", () => {
  it("starts the dot where the item really is, seen from the mat", () => {
    expect(initialOffset([0.6, 1.8, 0.4])).toEqual([0.6, 1.8]);
  });

  it("puts the listener so the item sounds exactly at the dot, at ear level", () => {
    const target: [number, number, number] = [0.6, 1.8, 0.4];
    const l = listenerPosition(target, [-1, 0.5]);
    expect(l[0]).toBeCloseTo(1.6);
    expect(l[1]).toBeCloseTo(1.3);
    expect(l[2]).toBeCloseTo(0.4);
    // what the Mac app and the voice compute: target minus listener
    expect(target[0] - l[0]).toBeCloseTo(-1);
    expect(target[1] - l[1]).toBeCloseTo(0.5);
  });

  it("stands the listener on the mat when nothing is being guided", () => {
    expect(listenerPosition(null, [2, 2])).toEqual(MAT);
  });

  it("a manual ping starts at the dot without moving the listener off the mat", () => {
    const t = manualTarget([1, -0.5]);
    expect(listenerPosition(t, [1, -0.5])).toEqual(MAT);
  });

  it("describes the dot as the judge hears it", () => {
    expect(describeOffset([0, 2], 0)).toMatchObject({ hour: 12, distance: 2 });
    expect(describeOffset([1, 0], 0).hour).toBe(3);
    expect(describeOffset([0, -1], 0).hour).toBe(6);
    // the judge turned 90 degrees right: a dot straight ahead in the room is now at 9 o'clock
    expect(describeOffset([0, 2], 90).hour).toBe(9);
  });

  it("nudges by keyboard and keeps the dot inside the stage", () => {
    expect(nudge([0, 0], "ArrowUp")).toEqual([0, 0.1]);
    expect(nudge([0, 0], "ArrowLeft")).toEqual([-0.1, 0]);
    expect(nudge([3.98, 0], "ArrowRight")[0]).toBeLessThanOrEqual(4);
  });
});

describe("operator event log", () => {
  const run = (...msgs: Record<string, unknown>[]) => msgs.reduce<OpEvent[]>((log, m, i) => addEvent(log, m as { type: string }, 100 + i), []);

  it("updates one line while a transcript is still partial, then makes it final", () => {
    const log = run(
      { type: "transcript", text: "where", is_final: false, source: "cartesia" },
      { type: "transcript", text: "where is the", is_final: false, source: "cartesia" },
      { type: "transcript", text: "where is the salt", is_final: true, source: "cartesia" },
    );
    expect(log).toHaveLength(1);
    expect(log[0]).toMatchObject({ kind: "heard", text: "where is the salt", partial: false });
  });

  it("shows what Earmark says once per utterance", () => {
    const log = run(
      { type: "speak", utterance_id: "u1", seq: 0, text: "The salt is ahead.", final: false },
      { type: "speak", utterance_id: "u1", seq: 1, final: true },
      { type: "speak_text", utterance_id: "u2", text: "You're here." },
    );
    expect(log.map((e) => e.text)).toEqual(["The salt is ahead.", "You're here."]);
    expect(log.every((e) => e.kind === "said")).toBe(true);
  });

  it("explains every guidance event", () => {
    const log = run(
      { type: "guide_start", object_id: "salt", name: "salt", target_position: [0, 1, 0], precision: "exact", utterance_id: "u" },
      { type: "guide_feedback", object_id: "salt", event: "behind", turn: "left", error_deg: -140 },
      { type: "guide_feedback", object_id: "salt", event: "locked", turn: null, error_deg: 2 },
      { type: "guide_feedback", object_id: "salt", event: "arrived", turn: null, error_deg: 0 },
      { type: "guide_stop", reason: "found", object_id: "salt" },
    );
    expect(log.map((e) => e.text)).toEqual([
      "Pinging the salt",
      "The ping is behind them (turn left)",
      "They are facing it",
      "Arrived: within half a meter",
      "Stopped: found",
    ]);
  });

  it("logs a status only when it changes", () => {
    const st = (ok: boolean, detail: string) => ({ type: "status", component: "mac_app", ok, detail });
    const log = run(st(true, "tracking"), st(true, "tracking"), st(false, "AirPods disconnected"));
    expect(log.map((e) => [e.who, e.text])).toEqual([
      ["AirPods app", "tracking"],
      ["AirPods app", "AirPods disconnected"],
    ]);
    expect(log[1]?.bad).toBe(true);
  });

  it("ignores high-rate position and head messages", () => {
    expect(run({ type: "head_pose", yaw: 10, pitch: 0 }, { type: "listener_pose", position: [0, 0, 1.5] })).toEqual([]);
  });
});
