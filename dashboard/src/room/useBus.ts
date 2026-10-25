import { useCallback, useEffect, useReducer, useRef } from "react";
import { initialState, MAX_LOG, reduce, tick, type RoomState } from "./model";

/** Message types the room view shows. `speak` is listed so spoken Cartesia text arrives (its audio is ignored). */
const SUBSCRIBE = [
  "snapshot", "registry_update", "state_update", "listener_pose", "head_pose", "guide_start", "guide_stop",
  "guide_feedback", "transcript", "speak", "speak_text", "speak_cached", "place_item", "pickup", "status", "reset",
];

export function busUrl(): string {
  const env = import.meta.env.VITE_BUS_URL as string | undefined;
  if (env) return env;
  const host = !window.location.hostname || window.location.hostname === "localhost" ? "127.0.0.1" : window.location.hostname;
  return `ws://${host}:8765`;
}

type Action = { kind: "echo"; text: string } | { kind: "local"; msg: Record<string, unknown> & { type: string } } | { kind: "msg"; msg: Record<string, unknown> & { type: string } } | { kind: "tick" } | { kind: "down" };

function reducer(s: RoomState, a: Action): RoomState {
  const now = Date.now() / 1000;
  if (a.kind === "echo") return { ...s, now, log: [{ t: now, kind: "heard" as const, text: a.text }, ...s.log].slice(0, MAX_LOG) };
  if (a.kind === "local") return { ...reduce(s, a.msg, now), now };
  if (a.kind === "msg") return { ...reduce(s, a.msg, now), now };
  if (a.kind === "down") return { ...s, connected: false };
  return tick(s, now);
}

/** Live room state from the Earmark bus, plus `send` for messages the page itself publishes. */
export function useBus(): {
  state: RoomState;
  send: (msg: Record<string, unknown>) => void;
  /** Show something the user typed in the conversation (the hub does not echo messages back to their sender). */
  echo: (text: string) => void;
  /** Feed a message to this page only (for the walking simulator, whose own position the hub does not echo back). */
  local: (msg: Record<string, unknown>) => void;
} {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    let stopped = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let delay = 500;
    const open = () => {
      const sock = new WebSocket(busUrl());
      ws.current = sock;
      sock.onopen = () => {
        delay = 500;
        sock.send(JSON.stringify({ type: "hello", component: "dashboard", subscribe: SUBSCRIBE, t: Date.now() / 1000 }));
      };
      sock.onmessage = (ev) => {
        try {
          const msg = JSON.parse(String(ev.data));
          if (msg && typeof msg.type === "string") dispatch({ kind: "msg", msg });
        } catch {
          // not JSON: ignore
        }
      };
      sock.onclose = () => {
        dispatch({ kind: "down" });
        if (!stopped) retry = setTimeout(open, (delay = Math.min(delay * 2, 4000)));
      };
    };
    open();
    const t = setInterval(() => dispatch({ kind: "tick" }), 250);
    return () => {
      stopped = true;
      clearInterval(t);
      if (retry) clearTimeout(retry);
      ws.current?.close();
    };
  }, []);

  const send = useCallback((msg: Record<string, unknown>) => {
    const sock = ws.current;
    if (sock && sock.readyState === WebSocket.OPEN) sock.send(JSON.stringify({ t: Date.now() / 1000, ...msg }));
  }, []);

  const echo = useCallback((text: string) => dispatch({ kind: "echo", text }), []);
  const local = useCallback((msg: Record<string, unknown>) => dispatch({ kind: "local", msg: msg as { type: string } }), []);
  return { state, send, echo, local };
}
