import { useEffect, useRef, useState } from "react";
import beaconConfig from "../../../config/beacons.json";
import { clockHour, horizontalDistance, type LogLine, type RoomState, type Vec3 } from "./model";
import { RoomScene, webglAvailable, type Beacon } from "./scene";
import { RoomModel } from "./scene3d";
import { useBus } from "./useBus";
import "./room.css";

const BEACONS: Beacon[] = beaconConfig.beacons.map((b) => ({ id: b.id, label: b.label, position: b.position as Vec3 }));
const ROOM = { w: beaconConfig.room.width_m, d: beaconConfig.room.depth_m };
const STEP_M = 0.06;

const SOURCE_TEXT: Record<string, string> = {
  beacons: "Live from the phones",
  manual: "Simulated walking",
  mat: "On the mat (no position yet)",
  steps: "From step counting",
  sim: "From a recording",
};

interface Stage {
  update(s: RoomState): void;
  dispose(): void;
  onFloorClick: ((x: number, y: number) => void) | null;
  view?(kind: "angle" | "top"): void;
}

type Mode = "2d" | "3d";

function initialMode(): Mode {
  const q = new URLSearchParams(window.location.search).get("view");
  if (q === "2d" || q === "3d") return q;
  try {
    return window.localStorage.getItem("room-mode") === "3d" ? "3d" : "2d";
  } catch {
    return "2d";
  }
}

export function RoomPage() {
  const { state, send, echo, local } = useBus();
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<Stage | null>(null);
  const [mode, setMode] = useState<Mode>(initialMode);
  const chooseMode = (m: Mode) => {
    setMode(m);
    try {
      window.localStorage.setItem("room-mode", m);
    } catch {
      // no storage: the choice just is not remembered
    }
  };
  const lastSaid = state.log.find((l) => l.kind === "said");
  const [gl] = useState(webglAvailable);
  const [simulate, setSimulate] = useState(false);
  const simPos = useRef<Vec3>([0, 0, 1.55]);
  const realFix = state.userLive && state.userSource === "beacons";
  const walking = simulate && !realFix; // real phone positions take over from the simulator

  useEffect(() => {
    if (!gl || !host.current) return;
    const s: Stage = mode === "3d" ? new RoomModel(host.current, BEACONS, ROOM) : new RoomScene(host.current, BEACONS, ROOM);
    scene.current = s;
    return () => {
      s.dispose();
      scene.current = null;
    };
  }, [gl, mode]);

  useEffect(() => {
    scene.current?.update(state);
  }, [state, mode]);

  // Walking simulator: arrow keys or WASD move a pretend user, shift-click puts them on a spot.
  // It sends the same position message the phones do, so the ping and the voice follow it.
  useEffect(() => {
    if (!walking) {
      if (scene.current) scene.current.onFloorClick = null;
      return;
    }
    simPos.current = [state.user[0], state.user[1], 1.55];
    const pub = () => {
      const msg = { type: "listener_pose", position: simPos.current.map((v) => Math.round(v * 1000) / 1000), quality: "ok", beacons_heard: 0, source: "manual" };
      send(msg);
      local(msg); // the hub does not send a message back to whoever sent it
    };
    const clamp = (v: number, half: number) => Math.max(-half, Math.min(half, v));
    const keys = new Set<string>();
    const down = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      const k = e.key.toLowerCase();
      if (["arrowup", "arrowdown", "arrowleft", "arrowright", "w", "a", "s", "d"].includes(k)) {
        e.preventDefault();
        keys.add(k);
      }
    };
    const up = (e: KeyboardEvent) => keys.delete(e.key.toLowerCase());
    const move = setInterval(() => {
      const p = simPos.current;
      let [x, y] = [p[0], p[1]];
      if (keys.has("arrowup") || keys.has("w")) y += STEP_M;
      if (keys.has("arrowdown") || keys.has("s")) y -= STEP_M;
      if (keys.has("arrowleft") || keys.has("a")) x -= STEP_M;
      if (keys.has("arrowright") || keys.has("d")) x += STEP_M;
      simPos.current = [clamp(x, ROOM.w / 2), clamp(y, ROOM.d / 2), 1.55];
    }, 50);
    const beat = setInterval(pub, 300);
    if (scene.current) {
      scene.current.onFloorClick = (x, y) => {
        simPos.current = [clamp(x, ROOM.w / 2), clamp(y, ROOM.d / 2), 1.55];
        pub();
      };
    }
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    pub();
    return () => {
      clearInterval(move);
      clearInterval(beat);
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
    // state.user is read once, when walking starts
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [walking, send, local, mode]);

  return (
    <div className={`room ${mode === "3d" ? "is-3d" : ""}`}>
      <section className="room-stage" aria-label="The room, seen from above">
        {gl ? <div ref={host} className="room-canvas" /> : <p className="room-nogl">This browser cannot draw the room.</p>}
        <div className="room-viewbar" role="group" aria-label="View">
          <button type="button" aria-pressed={mode === "2d"} onClick={() => chooseMode("2d")}>2D</button>
          <button type="button" aria-pressed={mode === "3d"} onClick={() => chooseMode("3d")}>3D</button>
          {mode === "3d" && (
            <>
              <span className="room-viewgap" />
              <button type="button" onClick={() => scene.current?.view?.("angle")}>Angle</button>
              <button type="button" onClick={() => scene.current?.view?.("top")}>Top</button>
            </>
          )}
        </div>
        {mode === "3d" && (
          <p className="room-caption" aria-live="polite">
            {lastSaid ? lastSaid.text : "Ask a question, or say where you left something."}
          </p>
        )}
        {mode === "2d" && <Legend />}
      </section>
      <aside className="room-panel">
        <header className="room-head">
          <h1>Earmark <span>live room</span></h1>
          <StatusRow state={state} />
        </header>
        <GuideCard state={state} />
        <Ask onAsk={(text) => {
            send({ type: "transcript", text, is_final: true, source: "typed" });
            echo(text);
          }} />
        <WhereUser state={state} simulate={walking} setSimulate={setSimulate} realFix={realFix} />
        <Log title="Conversation" lines={state.log.filter((l) => l.kind === "heard" || l.kind === "said")} empty="Ask something and the conversation shows here." />
        <Log title="Memory" lines={state.log.filter((l) => l.kind === "memory" || l.kind === "found" || l.kind === "info")} empty='Say "I put my keys in the drawer".' />
        <Items state={state} />
      </aside>
    </div>
  );
}

function Pill({ ok, label, detail }: { ok: boolean | null; label: string; detail: string }) {
  return (
    <li className={`room-pill ${ok === null ? "idle" : ok ? "ok" : "bad"}`} title={detail}>
      <span aria-hidden="true" className="dot" />
      <span>{label}</span>
    </li>
  );
}

function StatusRow({ state }: { state: RoomState }) {
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

function GuideCard({ state }: { state: RoomState }) {
  const g = state.guide;
  if (!g) {
    return (
      <section className="room-card room-guide idle">
        <h2>Guiding</h2>
        <p>Nothing right now. Ask "Where are my keys?"</p>
      </section>
    );
  }
  const d = horizontalDistance(state.user, g.target);
  const hour = clockHour(state.user, state.headYaw ?? 0, g.target);
  return (
    <section className="room-card room-guide">
      <h2>Guiding to</h2>
      <p className="room-guide-name">{g.name}</p>
      <dl className="room-guide-facts">
        <div><dt>Distance</dt><dd>{d.toFixed(1)} m</dd></div>
        <div><dt>Direction</dt><dd>{hour} o'clock</dd></div>
        <div><dt>Height</dt><dd>{g.target[2].toFixed(1)} m</dd></div>
      </dl>
      <div className="room-meter" aria-hidden="true"><span style={{ width: `${Math.max(4, 100 - (d / 4) * 100)}%` }} /></div>
    </section>
  );
}

function Ask({ onAsk }: { onAsk: (text: string) => void }) {
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

function WhereUser({ state, simulate, setSimulate, realFix }: { state: RoomState; simulate: boolean; setSimulate: (v: boolean) => void; realFix: boolean }) {
  const [x, y] = state.user;
  return (
    <section className="room-card">
      <h2>Where you are</h2>
      <p className="room-where">
        <strong>{SOURCE_TEXT[state.userSource] ?? state.userSource}</strong>
        <span>{x >= 0 ? `${x.toFixed(1)} m right` : `${(-x).toFixed(1)} m left`}, {y >= 0 ? `${y.toFixed(1)} m forward` : `${(-y).toFixed(1)} m back`} of the mat</span>
        {state.headYaw !== null && <span>Facing {Math.round(state.headYaw)}° {state.headYaw >= 0 ? "right" : "left"} of forward</span>}
      </p>
      <label className="room-toggle">
        <input type="checkbox" checked={simulate} disabled={realFix} onChange={(e) => setSimulate(e.target.checked)} />
        <span>{realFix ? "Phones are tracking you" : "Simulate walking (arrow keys, or click the floor)"}</span>
      </label>
    </section>
  );
}

function clock(t: number) {
  return new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function Log({ title, lines, empty }: { title: string; lines: LogLine[]; empty: string }) {
  return (
    <section className="room-card room-log">
      <h2>{title}</h2>
      {lines.length === 0 ? (
        <p className="room-empty">{empty}</p>
      ) : (
        <ol>
          {lines.slice(0, 8).map((l, i) => (
            <li key={`${l.t}-${i}`} className={`log-${l.kind}`}>
              <span className="who">{l.kind === "heard" ? "You" : l.kind === "said" ? "Earmark" : clock(l.t)}</span>
              <span>{l.text}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function Items({ state }: { state: RoomState }) {
  const items = Object.values(state.items);
  return (
    <section className="room-card room-items">
      <h2>Items</h2>
      {items.length === 0 ? (
        <p className="room-empty">Waiting for the hub.</p>
      ) : (
        <ul>
          {items.map((it) => (
            <li key={it.id}>
              <span className="name">{it.name}</span>
              <span className="where">{it.where}</span>
              {it.position && <span className="dist">{horizontalDistance(state.user, it.position).toFixed(1)} m</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Legend() {
  return (
    <ul className="room-legend" aria-label="Key">
      <li><span className="sw sw-user" />You</li>
      <li><span className="sw sw-beacon" />Beacon phone</li>
      <li><span className="sw sw-place" />Place</li>
      <li><span className="sw sw-item" />Item</li>
      <li><span className="sw sw-guide" />Sound target</li>
    </ul>
  );
}
