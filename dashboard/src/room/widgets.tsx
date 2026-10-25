import { useState } from "react";
import type { RoomState } from "./model";

/** Small pieces shared by the room view and the operator page (kept apart so the operator page does not load three.js). */
function Pill({ ok, label, detail }: { ok: boolean | null; label: string; detail: string }) {
  return (
    <li className={`room-pill ${ok === null ? "idle" : ok ? "ok" : "bad"}`} title={detail}>
      <span aria-hidden="true" className="dot" />
      <span>{label}</span>
    </li>
  );
}

export function StatusRow({ state }: { state: RoomState }) {
  const now = state.now;
  const fresh = (c: string) => {
    const s = state.status[c];
    return s && now - s.t < 30 ? s : null;
  };
  const mac = fresh("mac_app");
  const loc = fresh("locator");
  const con = fresh("concierge");
  return (
    <ul className="room-pills" aria-label="Status">
      <Pill ok={state.connected} label={state.connected ? "Connected" : "Not connected"} detail="The Earmark hub on this Mac" />
      <Pill ok={con ? con.ok : null} label="Voice" detail={con?.detail ?? "The voice service has not reported yet"} />
      <Pill ok={mac ? mac.ok : null} label="AirPods app" detail={mac?.detail ?? "The Mac app is not running"} />
      <Pill ok={loc?.ok ? true : null} label="Phones" detail={loc?.detail ?? "The phone position service is not running"} />
    </ul>
  );
}

export function Ask({ onAsk }: { onAsk: (text: string) => void }) {
  const [text, setText] = useState("");
  return (
    <form
      className="room-ask"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) onAsk(text.trim());
        setText("");
      }}
    >
      <label htmlFor="room-ask">Ask Earmark</label>
      <div>
        <input id="room-ask" value={text} onChange={(e) => setText(e.target.value)} placeholder="Where are my keys?" autoComplete="off" />
        <button type="submit">Ask</button>
      </div>
    </form>
  );
}
