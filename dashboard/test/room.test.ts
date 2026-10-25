import { describe, expect, it } from "vitest";
import { beaconsFromStatus, clockHour, initialState, reduce, tick, type RoomState } from "../src/room/model";

const snapshot = {
  type: "snapshot",
  space: {
    areas: [{ area: "drawer", label: "the drawer", position: [1.5, 0, 0.4] }],
    spots: [{ spot: 3, label: "center right", position: [0.16, 0.58, 0] }],
  },
  objects: [
    { object_id: "keys", name: "keys" },
    { object_id: "sugar", name: "sugar" },
  ],
  states: [{ object_id: "sugar", status: "on_spot", location: { spot: 3, position: [0.16, 0.58, 0] } }],
};

function run(...msgs: Record<string, unknown>[]): RoomState {
  let s = initialState();
  msgs.forEach((m, i) => (s = reduce(s, m as { type: string }, 100 + i)));
  return s;
}

describe("room model", () => {
  it("takes the beacon positions the room setup found from the phone service", () => {
    expect(beaconsFromStatus(run({ type: "status", component: "locator", ok: false, detail: "not set up" }))).toBeNull();
    const s = run({
      type: "status", component: "locator", ok: true, detail: "calibrated",
      info: { B1_x: 0.02, B1_y: 1.31, B1_z: 0.75, B2_x: 1.25, B2_y: 0.04, B2_z: 0.75 },
    });
    expect(beaconsFromStatus(s)).toEqual([
      { id: "B1", position: [0.02, 1.31, 0.75] },
      { id: "B2", position: [1.25, 0.04, 0.75] },
    ]);
  });


  it("builds places and items from the snapshot", () => {
    const s = run(snapshot);
    expect(s.connected).toBe(true);
    expect(s.places.map((p) => p.id)).toEqual(["drawer", "spot3"]);
    expect(s.items.sugar).toMatchObject({ name: "sugar", position: [0.16, 0.58, 0], where: "on spot 3" });
    expect(s.items.keys).toMatchObject({ position: null, where: "not detected" });
  });

  it("follows the user and keeps a trail, ignoring lost fixes", () => {
    const pose = (x: number, y: number, quality = "ok") => ({ type: "listener_pose", position: [x, y, 1.5], quality, beacons_heard: 3, source: "beacons" });
    const s = run(snapshot, pose(0, 0), pose(0, 0.5), pose(0, 0.51), pose(9, 9, "lost"));
    expect(s.user).toEqual([0, 0.51, 1.5]);
    expect(s.trail).toHaveLength(2); // the 1 cm move is too small to add a point
    expect(s.userLive).toBe(false);
    expect(s.userSource).toBe("beacons");
  });

  it("falls back to the mat after 5 s without a position", () => {
    let s = run(snapshot, { type: "listener_pose", position: [1, 1, 1.5], quality: "ok", beacons_heard: 3, source: "beacons" });
    s = tick(s, 103);
    expect(s.userLive).toBe(false);
    expect(s.user).toEqual([1, 1, 1.5]);
    s = tick(s, 107);
    expect(s.userSource).toBe("mat");
    expect(s.user[0]).toBe(0);
  });

  it("records guidance, speech and memory", () => {
    const s = run(
      snapshot,
      { type: "transcript", text: "I put my keys in the drawer", is_final: true, source: "typed" },
      { type: "place_item", object_id: "keys", area: "drawer" },
      { type: "state_update", object_id: "keys", status: "roaming", location: { area: "drawer", position: [1.5, 0, 0.4] } },
      { type: "speak_text", text: "Got it, the keys are in the drawer.", utterance_id: "u1" },
      { type: "guide_start", object_id: "keys", name: "keys", target_position: [1.5, 0, 0.4], precision: "area", utterance_id: "u2" },
    );
    expect(s.log.map((l) => [l.kind, l.text])).toEqual([
      ["said", "Got it, the keys are in the drawer."],
      ["memory", "Remembered: the keys is in the drawer"],
      ["heard", "I put my keys in the drawer"],
    ]);
    expect(s.convo.map((t) => [t.q, t.a])).toEqual([["I put my keys in the drawer", ["Got it, the keys are in the drawer."]]]);
    expect(s.items.keys).toMatchObject({ where: "in the drawer", position: [1.5, 0, 0.4] });
    expect(s.guide).toMatchObject({ objectId: "keys", target: [1.5, 0, 0.4] });
    expect(reduce(s, { type: "guide_stop", reason: "found", object_id: "keys" }, 200).guide).toBeNull();
  });

  it("pairs each answer with its question even when questions come faster than answers", () => {
    const said = (text: string) => ({ type: "speak_text", text, utterance_id: "u" });
    const heard = (text: string) => ({ type: "transcript", text, is_final: true, source: "typed" });
    const s = run(snapshot, heard("first?"), heard("second?"), said("answer one"), said("answer two"), said("more on two"));
    expect(s.convo.map((t) => [t.q, t.a])).toEqual([
      ["first?", ["answer one"]],
      ["second?", ["answer two", "more on two"]],
    ]);
    expect(run(snapshot, said("hello")).convo).toEqual([{ t: 101, q: null, a: ["hello"] }]);
  });

  it("gives the clock direction from where the user stands and faces", () => {
    expect(clockHour([0, 0, 1], 0, [0, 2, 0])).toBe(12);
    expect(clockHour([0, 0, 1], 0, [2, 0, 0])).toBe(3);
    expect(clockHour([0, 0, 1], 90, [2, 0, 0])).toBe(12);
    expect(clockHour([1, 1, 1], 0, [1, -1, 0])).toBe(6);
  });
});
