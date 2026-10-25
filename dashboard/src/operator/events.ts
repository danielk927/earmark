/** A readable, newest-last log of everything happening on the bus, for the operator page. Pure. */
export interface OpEvent {
  t: number;
  kind: "heard" | "said" | "guide" | "memory" | "system";
  who: string;
  text: string;
  /** A transcript that is still being spoken. */
  partial?: boolean;
  bad?: boolean;
}

type Msg = Record<string, unknown> & { type: string };

export const MAX_EVENTS = 300;

const COMPONENT: Record<string, string> = {
  hub: "Hub",
  concierge: "Voice",
  mac_app: "AirPods app",
  locator: "Phones",
  dashboard: "Dashboard",
  memory_agent: "Memory agent",
  simulator: "Simulator",
};
const SOURCE: Record<string, string> = { cartesia: "Heard (Cartesia)", apple: "Heard (Apple)", typed: "Typed" };
const FEEDBACK: Record<string, (m: Msg) => string> = {
  behind: (m) => `The ping is behind them${m.turn ? ` (turn ${m.turn})` : ""}`,
  front: () => "The ping is in front again",
  locked: () => "They are facing it",
  arrived: () => "Arrived: within half a meter",
};

function push(log: OpEvent[], e: OpEvent): OpEvent[] {
  return [...log, e].slice(-MAX_EVENTS);
}

/** Last status line logged per component, so repeats of the same status are skipped. */
function lastStatus(log: OpEvent[], who: string): OpEvent | undefined {
  for (let i = log.length - 1; i >= 0; i--) {
    const e = log[i];
    if (e && e.kind === "system" && e.who === who) return e;
  }
  return undefined;
}

export function addEvent(log: OpEvent[], m: Msg, now: number): OpEvent[] {
  const s = (k: string) => (typeof m[k] === "string" ? (m[k] as string) : "");
  switch (m.type) {
    case "transcript": {
      const final = Boolean(m.is_final);
      const who = SOURCE[s("source")] ?? "Heard";
      const last = log[log.length - 1];
      const e: OpEvent = { t: now, kind: "heard", who, text: s("text"), partial: !final };
      return last?.kind === "heard" && last.partial ? [...log.slice(0, -1), e] : push(log, e);
    }
    case "speak":
      return m.seq === 0 && s("text") ? push(log, { t: now, kind: "said", who: "Earmark", text: s("text") }) : log;
    case "speak_text":
    case "speak_cached":
      return s("text") ? push(log, { t: now, kind: "said", who: "Earmark", text: s("text") }) : log;
    case "guide_start":
      return push(log, { t: now, kind: "guide", who: "Guidance", text: `Pinging the ${s("name") || s("object_id")}` });
    case "guide_stop":
      return push(log, { t: now, kind: "guide", who: "Guidance", text: `Stopped: ${s("reason")}` });
    case "guide_feedback": {
      const f = FEEDBACK[s("event")];
      return f ? push(log, { t: now, kind: "guide", who: "AirPods", text: f(m) }) : log;
    }
    case "stt_mode":
      return push(log, { t: now, kind: "system", who: "Speech to text", text: `${s("engine")}${s("reason") ? ` (${s("reason")})` : ""}` });
    case "ptt":
      return push(log, { t: now, kind: "system", who: "Push to talk", text: s("state") === "start" ? "Listening" : "Released" });
    case "place_item":
      return push(log, { t: now, kind: "memory", who: "Memory", text: `Saved: ${s("object_id")}${s("area") ? ` in ${s("area")}` : " at a position"}` });
    case "pickup":
      return push(log, { t: now, kind: "memory", who: "Pickup", text: `Picked up: ${s("object_id")}` });
    case "pickup_result":
      return push(log, { t: now, kind: "memory", who: "Pickup", text: m.correct ? `Right item: ${s("actual")}` : `Wrong item: ${s("actual")} (wanted ${s("expected")})`, bad: !m.correct });
    case "label":
      return push(log, { t: now, kind: "memory", who: "Memory", text: `Named a tag: ${s("name")}` });
    case "chirp":
      return push(log, { t: now, kind: "system", who: "Fob", text: `Chirp ${s("action")}` });
    case "reset":
      return push(log, { t: now, kind: "system", who: "Reset", text: "Back to the starting state" });
    case "status": {
      const who = COMPONENT[s("component")] ?? s("component");
      const text = s("detail") || (m.ok ? "ok" : "problem");
      const prev = lastStatus(log, who);
      if (prev && prev.text === text && prev.bad === !m.ok) return log;
      return push(log, { t: now, kind: "system", who, text, bad: !m.ok });
    }
    default:
      return log;
  }
}
