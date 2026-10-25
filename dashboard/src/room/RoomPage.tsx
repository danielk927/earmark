import { useEffect, useMemo, useRef, useState } from "react";
import { clockHour, compare, horizontalDistance, roomSize, simulatorSelect, SYSTEM_NAME, type LogLine, type RoomState, type System, type Turn, type Vec3 } from "./model";
import { RoomModel, webglAvailable, type Beacon } from "./scene3d";
import { useBus } from "./useBus";
import "@fontsource/stix-two-text/latin-400.css";
import "@fontsource/stix-two-text/latin-400-italic.css";
import "@fontsource/stix-two-text/latin-600.css";
import "@fontsource/stix-two-text/latin-600-italic.css";
import "./room.css";

const STEP_M = 0.06;

const SOURCE_TEXT: Record<string, string> = {
  beacons: "Live from the sound beacons",
  sound: "Live from the sound beacons",
  uwb: "Live from the UWB anchors",
  manual: "Simulated walking",
  mat: "On the mat (no position yet)",
  steps: "From step counting",
  sim: "From a recording",
};

export function RoomPage() {
  const { state, send, echo, local } = useBus();
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<RoomModel | null>(null);
  const lastSaid = state.log.find((l) => l.kind === "said");
  const [gl] = useState(webglAvailable);
  const [simulate, setSimulate] = useState(false);
  const simPos = useRef<Vec3>([0, 0, 1.55]);
  const realFix = state.userLive && ["beacons", "sound", "uwb", "sim"].includes(state.userSource);
  const walking = simulate && !realFix; // real phone positions take over from the simulator
  const phones: Beacon[] = state.phones;
  const room = useMemo(() => roomSize(state.phones, state.places), [state.phones, state.places]);
  const roomRef = useRef(room);
  roomRef.current = room;

  useEffect(() => {
    if (!gl || !host.current) return;
    const s = new RoomModel(host.current, phones, roomRef.current);
    scene.current = s;
    return () => {
      s.dispose();
      scene.current = null;
    };
    // the scene is built once; setLayout below follows later snapshots
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gl]);

  useEffect(() => {
    scene.current?.setLayout(phones, room);
    scene.current?.update(state);
  }, [state, phones, room]);

  // Walking simulator: arrow keys or WASD move a pretend user, shift-click puts them on a spot.
  // It sends the same position message the phones do, so the ping and the voice follow it.
  useEffect(() => {
    if (!walking) {
      if (scene.current) scene.current.onFloorClick = null;
      return;
    }
    simPos.current = [state.user[0], state.user[1], 1.55];
    const select = simulatorSelect(state.positioning, Date.now() / 1000);
    if (select) send(select); // the hub only follows these poses while Sound drives the audio
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
      simPos.current = [clamp(x, roomRef.current.w / 2), clamp(y, roomRef.current.d / 2), 1.55];
    }, 50);
    const beat = setInterval(pub, 300);
    if (scene.current) {
      scene.current.onFloorClick = (x, y) => {
        simPos.current = [clamp(x, roomRef.current.w / 2), clamp(y, roomRef.current.d / 2), 1.55];
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
    // state.user and state.positioning are read once, when walking starts
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [walking, send, local]);

  return (
    <div className="room is-3d">
      <section className="room-stage" aria-label="The room, seen from above">
        {gl ? <div ref={host} className="room-canvas" /> : <p className="room-nogl">This browser cannot draw the room.</p>}
        <div className="room-viewbar" role="group" aria-label="View">
          <button type="button" onClick={() => scene.current?.view("angle")}>Angle</button>
          <button type="button" onClick={() => scene.current?.view("top")}>Top</button>
        </div>
        <p className="room-caption" aria-live="polite">
          {lastSaid ? lastSaid.text : "Ask a question, or say where you left something."}
        </p>
      </section>
      <aside className="room-panel">
        <header className="room-head">
          <h1>Earmark</h1>
          <StatusRow state={state} />
        </header>
        <GuideCard state={state} />
        <Ask onAsk={(text) => {
            send({ type: "transcript", text, is_final: true, source: "typed" });
            echo(text);
          }} />
        <PositioningCard state={state} onSelect={(active) => send({ type: "positioning_select", active })} />
        <WhereUser state={state} simulate={walking} setSimulate={setSimulate} realFix={realFix} />
        <Conversation turns={state.convo} />
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

/** The UWB / Sound switch (native radios, so arrow keys and screen readers work) and the side-by-side readout. */
export function PositioningCard({ state, onSelect }: { state: RoomState; onSelect: (s: System) => void }) {
  const p = state.positioning;
  const { lines, gap } = compare(p, state.now || Date.now() / 1000);
  return (
    <section className="room-card" aria-label="Positioning">
      <h2>Positioning</h2>
      <fieldset className="room-switch">
        <legend>Which system drives the audio</legend>
        <div className="room-seg">
          {(["uwb", "sound"] as System[]).map((sys) => (
            <label key={sys}>
              <input type="radio" name="positioning" value={sys} checked={p?.active === sys} onChange={() => onSelect(sys)} />
              <span>{SYSTEM_NAME[sys]}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <p className="room-compare" aria-live="off">
        <span>{lines.uwb}{p?.active === "uwb" ? " (active)" : ""}</span>
        <span>{lines.sound}{p?.active === "sound" ? " (active)" : ""}</span>
        <span>{gap === null ? "Apart: needs both live" : `Apart: ${gap.toFixed(2)} m`}</span>
      </p>
    </section>
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

function Conversation({ turns }: { turns: Turn[] }) {
  const end = useRef<HTMLLIElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [turns]);
  return (
    <section className="room-card room-convo">
      <h2>Conversation</h2>
      {turns.length === 0 ? (
        <p className="room-empty">Ask something and the conversation shows here.</p>
      ) : (
        <ol>
          {turns.slice(-6).map((t, i) => (
            <li key={`${t.t}-${i}`}>
              {t.q !== null && (
                <p className="convo-line convo-you">
                  <span>You</span>
                  {t.q}
                </p>
              )}
              {t.a.map((line, k) => (
                <p key={k} className="convo-line convo-earmark">
                  <span>Earmark</span>
                  {line}
                </p>
              ))}
            </li>
          ))}
          <li ref={end} aria-hidden="true" />
        </ol>
      )}
    </section>
  );
}

function Items({ state }: { state: RoomState }) {
  // Only things that have been added show here: an item counts once it has a place.
  const items = Object.values(state.items).filter((it) => it.position);
  return (
    <section className="room-card room-items">
      <h2>Items</h2>
      {items.length === 0 ? (
        <p className="room-empty">Nothing added yet. Say "I put my keys in the drawer" to add one.</p>
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
