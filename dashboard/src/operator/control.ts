/**
 * Manual ping control: the judge stands still on the mat and the operator drags where the ping comes from.
 * Pure math, in Earmark coordinates (meters, +x right, +y forward, +z up).
 *
 * The Mac app and the voice both place the ping at (target - listener). Re-sending the target restarts the
 * ping, so the target stays fixed and the page moves the listener instead: listener = target - offset puts
 * the target exactly at the dot, relative to the judge. The dot is at ear level (same height as the target).
 */
import { clockHour, type Vec3 } from "../room/model";

/** Where the judge stands when nothing is being guided: the mat, at ear height (as the room view assumes). */
export const MAT: Vec3 = [0, 0, 1.55];
/** The dot's reach from the judge, in meters. */
export const MAX_OFFSET_M = 4;
const NUDGE_M = 0.1;

/** Where the dot sits relative to the judge: meters right (+x) and forward (+y). */
export type Offset = [number, number];

const round = (v: number) => Math.round(v * 1000) / 1000;
const clamp = (v: number) => Math.max(-MAX_OFFSET_M, Math.min(MAX_OFFSET_M, v));

/** The position to publish so the target sounds at `offset` from the judge; the mat when nothing is guided. */
export function listenerPosition(target: Vec3 | null, offset: Offset): Vec3 {
  if (!target) return MAT;
  return [round(target[0] - offset[0]), round(target[1] - offset[1]), target[2]];
}

/** The target for a ping the operator starts by hand, chosen so the listener stays on the mat. */
export function manualTarget(offset: Offset): Vec3 {
  return [round(MAT[0] + offset[0]), round(MAT[1] + offset[1]), MAT[2]];
}

/** The dot as the judge hears it: clock hour (12 = where they face) and distance. */
export function describeOffset(offset: Offset, headYawDeg: number): { hour: number; distance: number } {
  return { hour: clockHour([0, 0, 0], headYawDeg, [offset[0], offset[1], 0]), distance: Math.hypot(offset[0], offset[1]) };
}

export function clampOffset(o: Offset): Offset {
  return [round(clamp(o[0])), round(clamp(o[1]))];
}

/** Arrow keys move the dot 10 cm in the room's directions. */
export function nudge(o: Offset, key: string): Offset {
  const [dx, dy] = key === "ArrowUp" ? [0, NUDGE_M] : key === "ArrowDown" ? [0, -NUDGE_M] : key === "ArrowLeft" ? [-NUDGE_M, 0] : key === "ArrowRight" ? [NUDGE_M, 0] : [0, 0];
  return clampOffset([o[0] + dx, o[1] + dy]);
}

/**
 * Where the dot starts for a new target: the target seen from where the judge was last published.
 * The voice computes its spoken direction from that same position, so the dot, the ping and the words agree.
 * With nothing pinged before, that position is the mat.
 */
export function offsetForNewTarget(target: Vec3, lastListener: Vec3): Offset {
  return [round(target[0] - lastListener[0]), round(target[1] - lastListener[1])];
}

/** The AirPods app reached a ping this page started: the voice will not end it, so the page must. */
export function endsOwnPing(ownedObjectId: string | null, m: Record<string, unknown>): boolean {
  return ownedObjectId !== null && m.type === "guide_feedback" && m.event === "arrived" && m.object_id === ownedObjectId;
}

/** Another client is placing the judge (the Mac app ignores `lost` fixes, so those do not compete). */
export function competesForPosition(m: Record<string, unknown>): boolean {
  return m.type === "listener_pose" && m.quality !== "lost";
}
