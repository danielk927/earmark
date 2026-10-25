import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Ask, StatusRow } from "../room/widgets";
import { SUBSCRIBE, useBus } from "../room/useBus";
import type { Vec3 } from "../room/model";
import { MAT, MAX_OFFSET_M, clampOffset, competesForPosition, describeOffset, endsOwnPing, listenerPosition, manualTarget, nudge, offsetForNewTarget, type Offset } from "./control";
import { addEvent, type OpEvent } from "./events";
import "../room/room.css";
import "./operator.css";

/** Everything the room view hears, plus the messages only this log shows. Audio (mic_audio, speak chunks) stays off. */
const OP_SUBSCRIBE = [...SUBSCRIBE, "stt_mode", "ptt", "pickup_result", "label", "chirp"];
const FAST_MS = 100; // how often the dot position is checked
const SLOW_MS = 300; // the longest gap between positions, so the Mac app never treats it as stale
const R = MAX_OFFSET_M + 0.4;

type Msg = Record<string, unknown> & { type: string };

export function OperatorPage() {
  const [events, setEvents] = useState<OpEvent[]>([]);
  const [foreign, setForeign] = useState<{ source: string; t: number } | null>(null);
  const [offset, setOffset] = useState<Offset>([0, 1.5]);
  /** Where this page last placed the judge; a new target's dot is measured from here (see offsetForNewTarget). */
  const lastListener = useRef<Vec3>(MAT);
  /** The object id of a ping this page started, so the page can end it on arrival (the voice will not). */
  const owned = useRef<string | null>(null);
  const ownRef = useRef<(msg: Msg) => void>(() => {});
  const onMessage = useCallback((m: Msg) => {
    const now = Date.now() / 1000;
    // The hub never echoes this page's own messages, so any listener_pose here comes from someone else.
    if (competesForPosition(m)) setForeign({ source: String(m.source ?? "unknown"), t: now });
    if (m.type === "guide_start" && Array.isArray(m.target_position)) {
      owned.current = null; // the voice took over
      setOffset(clampOffset(offsetForNewTarget(m.target_position as Vec3, lastListener.current)));
    }
    if (m.type === "guide_stop") owned.current = null;
    setEvents((log) => addEvent(log, m, now));
    if (endsOwnPing(owned.current, m)) {
      ownRef.current({ type: "guide_stop", reason: "found", object_id: owned.current });
      owned.current = null;
    }
  }, []);
  const { state, send, echo, local } = useBus({ subscribe: OP_SUBSCRIBE, onMessage });
  const [control, setControl] = useState(true);
  const offsetRef = useRef(offset);
  useEffect(() => {
    offsetRef.current = offset;
  }, [offset]);
  const guide = state.guide;
  const guideRef = useRef(guide);
  useEffect(() => {
    guideRef.current = guide;
  }, [guide]);
  const [pingAs, setPingAs] = useState("manual");

  const own = useCallback(
    (msg: Msg) => {
      send(msg);
      local(msg);
      setEvents((log) => addEvent(log, msg, Date.now() / 1000));
    },
    [send, local],
  );
  useEffect(() => {
    ownRef.current = own;
  }, [own]);

  // Publish where the judge "is" so the target sounds at the dot: on every change, and at least every 300 ms.
  useEffect(() => {
    if (!control) return;
    let last = 0;
    let lastPos = "";
    const beat = setInterval(() => {
      const now = Date.now();
      const pos = listenerPosition(guideRef.current?.target ?? null, offsetRef.current);
      const key = pos.join(",");
      if (key === lastPos && now - last < SLOW_MS) return;
      send({ type: "listener_pose", position: pos, quality: "ok", beacons_heard: 0, source: "manual" });
      lastListener.current = pos;
      last = now;
      lastPos = key;
    }, FAST_MS);
    return () => clearInterval(beat);
  }, [control, send]);

  const move = (o: Offset) => setOffset(clampOffset(o));

  const start = () => {
    const name = pingAs === "manual" ? "ping" : state.items[pingAs]?.name ?? pingAs;
    owned.current = pingAs;
    own({ type: "guide_start", object_id: pingAs, name, target_position: manualTarget(offsetRef.current), precision: "exact", utterance_id: `operator_${Date.now()}` });
  };
  const stop = () => {
    if (!guide) return;
    if (owned.current) {
      own({ type: "guide_stop", reason: "cancelled", object_id: guide.objectId });
      owned.current = null;
      return;
    }
    // The voice started this ping and keeps its own timer, so ask the voice to stop (it sends guide_stop itself).
    const msg = { type: "transcript", text: "stop", is_final: true, source: "typed" };
    send(msg);
    echo("stop");
    setEvents((log) => addEvent(log, msg, Date.now() / 1000));
  };

  const fresh = foreign && state.now - foreign.t < 3 ? foreign : null;
  const items = Object.values(state.items);
  const yaw = state.headYaw;
  const { hour, distance } = describeOffset(offset, yaw ?? 0);

  return (
    <div className="room op">
      <section className="op-stage" aria-label="Drag the ping around the judge">
        <Stage offset={offset} onMove={move} yaw={yaw} pinging={!!guide} places={state.places.filter((p) => p.kind === "area").map((p) => ({ label: p.label, position: p.position }))} />
        <p className="op-hint">Drag the dot, or use the arrow keys. The judge stays at the center, facing up.</p>
      </section>
      <aside className="room-panel op-panel">
        <header className="room-head">
          <h1>
            Earmark <span>operator</span>
          </h1>
          <StatusRow state={state} />
        </header>
        {fresh && control && (
          <p className="op-warn" role="alert">
            Another position source is live ({fresh.source}). It will fight this page: stop it, or turn off control below.
          </p>
        )}
        <section className={`room-card op-ping ${guide ? "on" : ""}`}>
          <h2>Ping</h2>
          <p className="op-ping-state">{guide ? `Pinging the ${guide.name}` : "Not pinging"}</p>
          <p className="op-ping-where">
            {hour} o'clock, {distance.toFixed(1)} m
            <span>
              {Math.abs(offset[0]).toFixed(1)} m {offset[0] >= 0 ? "right" : "left"}, {Math.abs(offset[1]).toFixed(1)} m {offset[1] >= 0 ? "ahead" : "behind"}
              {yaw !== null && ` · judge facing ${Math.abs(Math.round(yaw))}° ${yaw >= 0 ? "right" : "left"}`}
            </span>
          </p>
          <div className="op-controls">
            <label>
              <span>Ping as</span>
              <select value={pingAs} disabled={!!guide} onChange={(e) => setPingAs(e.target.value)}>
                <option value="manual">just a ping</option>
                {items.map((it) => (
                  <option key={it.id} value={it.id}>
                    {it.name}
                  </option>
                ))}
              </select>
            </label>
            {guide ? (
              <button type="button" onClick={stop}>
                Stop ping
              </button>
            ) : (
              <button type="button" className="primary" onClick={start} disabled={!state.connected}>
                Start ping
              </button>
            )}
          </div>
          <label className="room-toggle">
            <input type="checkbox" checked={control} onChange={(e) => setControl(e.target.checked)} />
            <span>Control the judge's position from this page</span>
          </label>
        </section>
        <Ask
          onAsk={(text) => {
            const msg = { type: "transcript", text, is_final: true, source: "typed" };
            send(msg);
            echo(text);
            setEvents((log) => addEvent(log, msg, Date.now() / 1000));
          }}
        />
        <EventLog events={events} />
      </aside>
    </div>
  );
}

/** Top-down stage in meters: the judge at the origin, forward is up. */
function Stage({ offset, onMove, yaw, pinging, places }: { offset: Offset; onMove: (o: Offset) => void; yaw: number | null; pinging: boolean; places: { label: string; position: Vec3 }[] }) {
  const svg = useRef<SVGSVGElement>(null);
  const dragging = useRef(false);
  const toOffset = (e: ReactPointerEvent): Offset | null => {
    const el = svg.current;
    const m = el?.getScreenCTM();
    if (!el || !m) return null;
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse());
    return [p.x, -p.y];
  };
  const cone = yaw === null ? null : (yaw * Math.PI) / 180;
  const wedge = (a: number, r: number, half = 0.45) =>
    `M 0 0 L ${r * Math.sin(a - half)} ${-r * Math.cos(a - half)} A ${r} ${r} 0 0 1 ${r * Math.sin(a + half)} ${-r * Math.cos(a + half)} Z`;
  const [dx, dy] = [offset[0], -offset[1]];
  return (
    <svg
      ref={svg}
      className="op-svg"
      viewBox={`${-R} ${-R} ${2 * R} ${2 * R}`}
      tabIndex={0}
      role="application"
      aria-label={`Ping ${offset[0].toFixed(1)} m right and ${offset[1].toFixed(1)} m forward of the judge. Arrow keys move it.`}
      onKeyDown={(e) => {
        if (e.key.startsWith("Arrow")) {
          e.preventDefault();
          onMove(nudge(offset, e.key));
        }
      }}
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        const o = toOffset(e);
        if (!o) return;
        dragging.current = true;
        e.currentTarget.setPointerCapture?.(e.pointerId);
        onMove(o);
      }}
      onPointerMove={(e) => {
        if (!dragging.current) return;
        const o = toOffset(e);
        if (o) onMove(o);
      }}
      onPointerUp={() => (dragging.current = false)}
      onPointerCancel={() => (dragging.current = false)}
      onLostPointerCapture={() => (dragging.current = false)}
    >
      {[1, 2, 3, 4].map((r) => (
        <g key={r}>
          <circle r={r} className="op-ring" />
          <text x={r * 0.74} y={-r * 0.67} className="op-ring-label">
            {r} m
          </text>
        </g>
      ))}
      <circle r={0.5} className="op-arrive" />
      <text x={0} y={-R + 0.25} className="op-axis">forward</text>
      <text x={0} y={R - 0.12} className="op-axis">behind</text>
      <text x={-R + 0.1} y={0.05} className="op-axis start">left</text>
      <text x={R - 0.1} y={0.05} className="op-axis end">right</text>
      {places.map((p) => (
        <g key={p.label} className="op-place" transform={`translate(${p.position[0] - MAT[0]} ${-(p.position[1] - MAT[1])})`}>
          <circle r={0.05} />
          <text y={-0.1}>{p.label}</text>
        </g>
      ))}
      {cone !== null && <path d={wedge(cone, 1.1)} className="op-cone" />}
      <line x1={0} y1={0} x2={dx} y2={dy} className="op-line" />
      <circle r={0.2} className="op-judge" />
      {cone !== null && <path d={`M ${0.14 * Math.sin(cone - 0.5)} ${-0.14 * Math.cos(cone - 0.5)} L ${0.3 * Math.sin(cone)} ${-0.3 * Math.cos(cone)} L ${0.14 * Math.sin(cone + 0.5)} ${-0.14 * Math.cos(cone + 0.5)}`} className="op-nose" />}
      <text y={0.42} className="op-judge-label">judge</text>
      <g transform={`translate(${dx} ${dy})`} className={`op-dot ${pinging ? "on" : ""}`}>
        {pinging && <circle r={0.16} className="op-pulse" />}
        <circle r={0.16} />
      </g>
    </svg>
  );
}

function clock(t: number) {
  return new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

function EventLog({ events }: { events: OpEvent[] }) {
  const list = useRef<HTMLOListElement>(null);
  const stick = useRef(true); // follow new events only while the operator is at the bottom
  useEffect(() => {
    const el = list.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [events]);
  return (
    <section className="room-card op-log" aria-label="Everything happening">
      <h2>Everything happening</h2>
      {events.length === 0 ? (
        <p className="room-empty">Waiting for the hub. Speak, or type a question above.</p>
      ) : (
        <ol
          ref={list}
          onScroll={(e) => {
            const el = e.currentTarget;
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
          }}
        >
          {events.map((e, i) => (
            <li key={`${e.t}-${i}`} className={`op-ev op-${e.kind} ${e.partial ? "partial" : ""} ${e.bad ? "bad" : ""}`}>
              <time>{clock(e.t)}</time>
              <span className="who">{e.who}</span>
              <span className="text">{e.text}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
