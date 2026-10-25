/**
 * The top-down "listening field": the listener at the origin, +x to the right, +y forward,
 * spots on their measured positions, and one label chip per spot fanned outward along the
 * line from the listener. Text is sized in screen pixels (the SVG is drawn 1:1 with its box),
 * so labels stay readable on a phone; chips wrap and are pushed apart until nothing overlaps.
 * The picture is a role="img" with a text description; the table below the map has the same facts.
 */
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { LiveMap } from "@contracts/convexFunctions";
import { anchorWords, capitalize, distanceWords, poseWords, spotLabel } from "../lib/words";

type ChipKind = "object" | "unknown" | "ghost" | "floating";
interface Chip {
  key: string;
  kind: ChipKind;
  lines: { text: string; strong: boolean }[];
  /** Anchor (px) the chip grows away from, and the unit direction it grows in. */
  ax: number;
  ay: number;
  dx: number;
  dy: number;
  push: number;
  w: number;
  h: number;
  cx: number;
  cy: number;
  signature: string;
}

const PAD = 12;

function useWidth(ref: React.RefObject<HTMLElement | null>, fallback: number) {
  const [w, setW] = useState(fallback);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const next = Math.round(el.getBoundingClientRect().width);
      if (next > 0) setW(next);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

function wrap(text: string, maxChars: number): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    if (!line) line = word;
    else if ((line + " " + word).length <= maxChars) line += " " + word;
    else {
      lines.push(line);
      line = word;
    }
  }
  if (line) lines.push(line);
  return lines;
}

function overlaps(a: Chip, b: Chip, gap: number) {
  return Math.abs(a.cx - b.cx) * 2 < a.w + b.w + gap && Math.abs(a.cy - b.cy) * 2 < a.h + b.h + gap;
}

function place(c: Chip, halfWidth: number) {
  const along = Math.abs(c.dx) * (c.w / 2) + Math.abs(c.dy) * (c.h / 2) + c.push;
  c.cx = Math.max(-halfWidth + c.w / 2 + 4, Math.min(halfWidth - c.w / 2 - 4, c.ax + c.dx * along));
  c.cy = c.ay + c.dy * along;
}

export function describeMap(map: LiveMap): string {
  const parts: string[] = [];
  for (const s of [...map.spots].sort((a, b) => a.spot - b.spot)) {
    const here = map.states.filter((st) => st.status === "on_spot" && st.spot === s.spot);
    const tag = map.unknownTags.find((u) => u.spot === s.spot);
    const names = here.map((st) => map.objects.find((o) => o.objectId === st.objectId)?.name ?? st.objectId);
    if (tag) names.push("a new unlabeled item");
    parts.push(`${capitalize(s.label)} spot: ${names.length ? names.join(" and ") : "empty"}.`);
  }
  for (const st of map.states) {
    if (st.status !== "roaming") continue;
    const name = capitalize(map.objects.find((o) => o.objectId === st.objectId)?.name ?? st.objectId);
    parts.push(st.near ? `${name}: near the ${st.near} receiver${st.distanceClass ? `, ${distanceWords[st.distanceClass]}` : ""}.` : `${name}: moving around.`);
  }
  for (const a of map.anchors) parts.push(`${anchorWords(a)}.`);
  if (map.wearer) parts.push(`The person: ${poseWords[map.wearer.mode].toLowerCase()}.`);
  return `Seen from above, with the listener at the bottom facing forward. ${parts.join(" ")}`;
}

export function MapField({ map }: { map: LiveMap }) {
  const box = useRef<HTMLDivElement>(null);
  const width = useWidth(box, 760);
  const titleId = useId();
  const descId = useId();
  const glowId = `glow${useId().replace(/[^a-zA-Z0-9]/g, "")}`;

  const compact = width < 560;
  const fs = compact ? 15 : 17;
  const lh = Math.round(fs * 1.25);
  const charW = fs * 0.6;
  const padX = compact ? 9 : 12;
  const padY = compact ? 6 : 8;
  const half = width / 2;
  const baseS = width / (compact ? 1.36 : 1.56); // px per meter across the width
  // The anchors and the person can be a meter or two off to the side: zoom out just enough to fit them.
  const reach = Math.max(0, ...map.anchors.map((a) => Math.abs(a.position[0]!)), map.wearer ? Math.abs(map.wearer.position[0]!) : 0);
  const s = reach > 0 ? Math.max(Math.min(baseS, (half - 22) / reach), Math.min(baseS, 70)) : baseS;
  const pr = Math.max(15, Math.min(26, 0.045 * s));
  const P = (pos: readonly number[]) => ({ x: pos[0]! * s, y: -pos[1]! * s });

  const name = (id: string) => capitalize(map.objects.find((o) => o.objectId === id)?.name ?? id);

  // Build one chip per spot.
  const chips: Chip[] = [];
  const emptySpots = new Set<number>();
  for (const spot of map.spots) {
    const p = P(spot.position);
    const len = Math.hypot(p.x, p.y) || 1;
    const dx = p.x / len;
    const dy = p.y / len;
    const here = map.states.filter((st) => st.status === "on_spot" && st.spot === spot.spot);
    const tag = map.unknownTags.find((u) => u.spot === spot.spot);
    let kind: ChipKind = "object";
    let texts: { text: string; strong: boolean }[] = here.map((st) => ({ text: name(st.objectId), strong: true }));
    if (tag) {
      kind = here.length ? "object" : "unknown";
      texts.push({ text: "New item", strong: true }, { text: "not labeled", strong: false });
    }
    if (!texts.length) {
      const away = map.states.find((st) => st.homeSpot === spot.spot && st.status === "held");
      if (away) {
        kind = "ghost";
        texts = [
          { text: name(away.objectId), strong: true },
          { text: "picked up", strong: false },
        ];
      } else {
        emptySpots.add(spot.spot);
        continue;
      }
    }
    chips.push({
      key: `spot-${spot.spot}`,
      kind,
      lines: texts,
      ax: p.x + dx * (pr + 8),
      ay: p.y + dy * (pr + 8),
      dx,
      dy,
      push: 0,
      w: 0,
      h: 0,
      cx: 0,
      cy: 0,
      signature: `${kind}:${texts.map((t) => t.text).join("|")}`,
    });
  }

  // Objects placed by area or receiver proximity float near that position, toward the listener.
  const floating = new Map<string, { x: number; y: number; lines: { text: string; strong: boolean }[] }>();
  for (const st of map.states) {
    if (st.status === "on_spot" && st.spot != null) continue;
    if (!st.position || (st.status !== "roaming" && st.status !== "on_spot")) continue;
    const k = st.position.map((v) => v.toFixed(2)).join(",");
    const entry = floating.get(k) ?? { ...P(st.position), lines: [] };
    entry.lines.push({ text: name(st.objectId), strong: true });
    entry.lines.push({
      text:
        st.status === "roaming"
          ? st.distanceClass
            ? distanceWords[st.distanceClass]
            : st.area
              ? `in ${map.areas.find((a) => a.area === st.area)?.label ?? "a saved place"}`
              : st.precision === "exact"
                ? "where you left it"
                : "nearby"
          : `somewhere on ${map.areas.find((a) => a.area === st.area)?.label ?? "the counter"}`,
      strong: false,
    });
    floating.set(k, entry);
  }
  const markers: { key: string; x: number; y: number }[] = [];
  for (const [k, f] of floating) {
    markers.push({ key: k, x: f.x, y: f.y });
    chips.push({
      key: `float-${k}`,
      kind: "floating",
      lines: f.lines,
      ax: f.x,
      ay: f.y + 14,
      dx: 0,
      dy: 1,
      push: 0,
      w: 0,
      h: 0,
      cx: 0,
      cy: 0,
      signature: `floating:${f.lines.map((l) => l.text).join("|")}`,
    });
  }

  const headR = Math.max(16, Math.min(24, 0.05 * s));
  // UWB anchors: triangles with a two-line label above (or below, when behind the listener) them.
  // The label grows toward the middle so it never leaves the picture.
  const triR = Math.max(11, Math.min(16, 0.035 * s));
  const af = fs * 0.85;
  const anchorShapes = map.anchors.map((a) => {
    const p = P(a.position);
    const above = a.position[1]! >= 0;
    const align = a.position[0]! < -0.15 ? "start" : a.position[0]! > 0.15 ? "end" : "middle";
    const w = Math.ceil(Math.max(a.label.length, 10) * af * 0.58);
    const h = af * 2.4 + 4;
    const tx = align === "start" ? p.x - triR : align === "end" ? p.x + triR : Math.max(-half + w / 2 + 4, Math.min(half - w / 2 - 4, p.x));
    const x1 = align === "start" ? tx : align === "end" ? tx - w : tx - w / 2;
    const y1 = above ? p.y - triR - 6 - h : p.y + triR + 6;
    return { a, p, above, align: align as "start" | "middle" | "end", w, h, tx, x1, y1 };
  });
  // The person: a dot with the mode in words under it.
  const dotR = Math.max(9, Math.min(14, 0.025 * s));
  const person = map.wearer
    ? (() => {
        const p = P(map.wearer.position);
        const lines = wrap(poseWords[map.wearer.mode], 16);
        const w = Math.ceil(Math.max(...lines.map((l) => l.length)) * fs * 0.58);
        const tx = Math.max(-half + w / 2 + 4, Math.min(half - w / 2 - 4, p.x));
        return { p, lines, w, h: lines.length * fs * 1.2, tx, y1: p.y + dotR + 6 };
      })()
    : null;

  // Spot labels wrap to the room between neighboring pucks, so "center left" and "center right" never collide.
  const labelCharW = fs * 0.85 * 0.58;
  const spotXs = map.spots.map((sp) => P(sp.position).x);
  const labels = new Map<number, string[]>();
  const obstacles: { x1: number; x2: number; y1: number; y2: number }[] = [];
  for (const sp of map.spots) {
    const p = P(sp.position);
    const room = Math.min(...spotXs.filter((x) => x !== p.x).map((x) => Math.abs(x - p.x)), width) - 8;
    const lines = wrap(spotLabel(map.spots, sp.spot) ?? "", Math.max(4, Math.floor(room / labelCharW)));
    if (emptySpots.has(sp.spot)) lines.push("empty");
    labels.set(sp.spot, lines);
    const halfW = Math.max(pr, (Math.max(...lines.map((l) => l.length)) * labelCharW) / 2) + 2;
    obstacles.push({ x1: p.x - halfW, x2: p.x + halfW, y1: p.y - pr - 2, y2: p.y + pr + 6 + lines.length * fs * 1.05 });
  }
  for (const m of markers) obstacles.push({ x1: m.x - 9, x2: m.x + 9, y1: m.y - 9, y2: m.y + 9 });
  for (const a of anchorShapes) {
    obstacles.push({ x1: Math.min(a.x1, a.p.x - triR), x2: Math.max(a.x1 + a.w, a.p.x + triR), y1: Math.min(a.y1, a.p.y - triR), y2: Math.max(a.y1 + a.h, a.p.y + triR) });
  }
  if (person) {
    // The listening mark and its label stay clear of the item chips.
    obstacles.push({ x1: -Math.max(headR, fs * 4.5), x2: Math.max(headR, fs * 4.5), y1: -headR, y2: headR * 0.6 + fs * 1.6 });
    obstacles.push({ x1: Math.min(person.tx - person.w / 2, person.p.x - dotR), x2: Math.max(person.tx + person.w / 2, person.p.x + dotR), y1: person.p.y - dotR, y2: person.y1 + person.h });
  }

  // Size chips: wrap to the space between neighbors, then push apart until nothing overlaps.
  const spotChips = chips.filter((c) => c.kind !== "floating");
  for (const c of chips) {
    const others = spotChips.filter((o) => o !== c).map((o) => Math.abs(o.ax - c.ax));
    const room = c.kind === "floating" ? width * 0.42 : Math.min(...others, width) - 10;
    const maxW = Math.max(compact ? 76 : 96, Math.min(compact ? 150 : 240, room));
    const maxChars = Math.max(5, Math.floor((maxW - padX * 2) / charW));
    const lines = c.lines.flatMap((l) => wrap(l.text, maxChars).map((text) => ({ text, strong: l.strong })));
    c.lines = lines;
    const longest = Math.max(...lines.map((l) => l.text.length));
    c.w = Math.ceil(longest * charW + padX * 2);
    c.h = lines.length * lh + padY * 2;
    place(c, half);
  }
  const hitsObstacle = (c: Chip) =>
    obstacles.some((o) => c.cx + c.w / 2 + 4 > o.x1 && c.cx - c.w / 2 - 4 < o.x2 && c.cy + c.h / 2 + 4 > o.y1 && c.cy - c.h / 2 - 4 < o.y2);
  for (let round = 0; round < 60; round++) {
    let moved = false;
    for (const c of chips) {
      if (hitsObstacle(c)) {
        c.push += 6;
        place(c, half);
        moved = true;
      }
    }
    for (let i = 0; i < chips.length; i++) {
      for (let j = i + 1; j < chips.length; j++) {
        const a = chips[i]!;
        const b = chips[j]!;
        if (!overlaps(a, b, 8)) continue;
        // Push the chip that is closer to the listener outward along its own ray.
        const target = a.kind === "floating" ? a : b.kind === "floating" ? b : Math.abs(a.dy) < Math.abs(b.dy) ? b : a;
        target.push += 6;
        place(target, half);
        moved = true;
      }
    }
    if (!moved) break;
  }

  // Signatures that changed since the last render get one gentle pulse (skipped with reduced motion).
  const prevSig = useRef<Map<string, string> | null>(null);
  const [pulses, setPulses] = useState<string[]>([]);
  const sigKey = chips.map((c) => `${c.key}=${c.signature}`).join(";") + `;empty=${[...emptySpots].join(",")}`;
  useEffect(() => {
    const now = new Map(sigKey.split(";").map((kv) => kv.split("=") as [string, string]));
    if (prevSig.current) {
      const changed = [...now].filter(([k, v]) => prevSig.current!.get(k) !== v).map(([k]) => k);
      for (const [k] of prevSig.current) if (!now.has(k)) changed.push(k);
      if (changed.length) setPulses(changed);
    }
    prevSig.current = now;
  }, [sigKey]);

  // Bounds: everything drawn, plus the listener.
  const listenerBottom = headR + fs * 2.2;
  let top = -0.84 * s;
  for (const c of chips) top = Math.min(top, c.cy - c.h / 2);
  for (const sp of map.spots) top = Math.min(top, P(sp.position).y - pr);
  let bottom = listenerBottom;
  for (const a of anchorShapes) {
    top = Math.min(top, a.above ? a.y1 : a.p.y - triR);
    bottom = Math.max(bottom, a.above ? a.p.y + triR : a.y1 + a.h);
  }
  if (person) {
    top = Math.min(top, person.p.y - dotR);
    bottom = Math.max(bottom, person.y1 + person.h);
  }
  top -= PAD + 6;
  const height = Math.ceil(bottom + PAD - top);

  const ripples = [0.2, 0.4, 0.6, 0.8];
  const arc = (r: number) => {
    const a = (62 * Math.PI) / 180;
    const R = r * s;
    return `M ${-R * Math.sin(a)} ${-R * Math.cos(a)} A ${R} ${R} 0 0 1 ${R * Math.sin(a)} ${-R * Math.cos(a)}`;
  };

  return (
    <div className="map-field" ref={box}>
      <svg
        role="img"
        aria-labelledby={`${titleId} ${descId}`}
        width={width}
        height={height}
        viewBox={`${-half} ${top} ${width} ${height}`}
        className={compact ? "map compact" : "map"}
      >
        <title id={titleId}>Map of the spots</title>
        <desc id={descId}>{describeMap(map)}</desc>
        <defs>
          <radialGradient id={glowId}>
            <stop offset="0" className="glow-in" />
            <stop offset="1" className="glow-out" />
          </radialGradient>
        </defs>
        <circle cx={0} cy={0} r={0.95 * s} fill={`url(#${glowId})`} />

        <g className="ripples">
          {ripples.map((r) => (
            <g key={r}>
              <path d={arc(r)} />
              {!compact && (
                <text x={r * s * Math.sin((62 * Math.PI) / 180) + 6} y={-r * s * Math.cos((62 * Math.PI) / 180) + 4}>
                  {Math.round(r * 100)} cm
                </text>
              )}
            </g>
          ))}
        </g>

        {markers.map((m) => (
          <g key={m.key} className="receiver">
            <rect x={m.x - 6} y={m.y - 6} width="12" height="12" transform={`rotate(45 ${m.x} ${m.y})`} />
          </g>
        ))}

        {map.spots.map((spot) => {
          const p = P(spot.position);
          const empty = emptySpots.has(spot.spot);
          const pulse = pulses.includes(`spot-${spot.spot}`) || (empty && pulses.some((k) => k.startsWith("empty")));
          return (
            <g key={spot.spot} className={empty ? "spot empty" : "spot"}>
              {pulse && <circle key={sigKey} className="pulse" cx={p.x} cy={p.y} r={pr} />}
              <circle className="puck" cx={p.x} cy={p.y} r={pr} />
              <text className="puck-number" x={p.x} y={p.y + fs * 0.32} textAnchor="middle" fontSize={fs * 0.9}>
                {spot.spot}
              </text>
              {(labels.get(spot.spot) ?? []).map((line, i) => (
                <text
                  key={i}
                  className="spot-label"
                  x={p.x}
                  y={p.y + pr + fs * 1.05 * (i + 1)}
                  textAnchor="middle"
                  fontSize={fs * 0.85}
                >
                  {line}
                </text>
              ))}
            </g>
          );
        })}

        {chips.map((c) => (
          <g key={c.key} className={`chip chip-${c.kind}`}>
            {c.kind === "floating" && <line className="tether" x1={c.ax} y1={c.ay - 6} x2={c.cx} y2={c.cy - c.h / 2} />}
            <rect x={c.cx - c.w / 2} y={c.cy - c.h / 2} width={c.w} height={c.h} rx={Math.min(12, c.h / 2)} />
            {c.lines.map((l, i) => (
              <text
                key={i}
                x={c.cx}
                y={c.cy - c.h / 2 + padY + lh * i + lh * 0.78}
                textAnchor="middle"
                fontSize={l.strong ? fs : fs * 0.88}
                className={l.strong ? "strong" : "soft"}
              >
                {l.text}
              </text>
            ))}
          </g>
        ))}

        {person ? (
          // With a person on the map, the origin is just the listening mark they walk toward.
          <g className="listen-spot">
            <circle cx={0} cy={0} r={headR * 0.6} />
            {Math.hypot(person.p.x, person.p.y) > headR * 3 && (
              <text x={0} y={headR * 0.6 + fs * 1.1} textAnchor="middle" fontSize={fs * 0.9}>
                Listening spot
              </text>
            )}
          </g>
        ) : (
          <g className="listener">
            <circle cx={-headR * 0.98} cy={0} r={headR * 0.3} />
            <circle cx={headR * 0.98} cy={0} r={headR * 0.3} />
            <circle cx={0} cy={0} r={headR} />
            <path d={`M ${-headR * 0.32} ${-headR * 0.9} L 0 ${-headR * 1.45} L ${headR * 0.32} ${-headR * 0.9} Z`} />
            <text x={0} y={headR + fs * 1.3} textAnchor="middle" fontSize={fs * 0.9}>
              Listener
            </text>
          </g>
        )}

        {anchorShapes.map(({ a, p, align, tx, y1 }) => {
          const on = a.online;
          return (
            <g key={a.anchorId} className={on ? "anchor anchor-on" : "anchor anchor-off"}>
              <path
                className="anchor-shape"
                d={`M ${p.x} ${p.y - triR} L ${p.x + triR * 0.95} ${p.y + triR * 0.7} L ${p.x - triR * 0.95} ${p.y + triR * 0.7} Z`}
              />
              <text className="anchor-name" x={tx} y={y1 + af * 1.0} textAnchor={align} fontSize={af}>
                {a.label}
              </text>
              <text className="anchor-state" x={tx} y={y1 + af * 2.25} textAnchor={align} fontSize={af}>
                {on ? "\u2713 Online" : "\u2715 Offline"}
              </text>
            </g>
          );
        })}

        {person && map.wearer && (
          <g className={`person person-${map.wearer.mode}`}>
            <circle className="person-ring" cx={person.p.x} cy={person.p.y} r={dotR + 4} />
            <circle className="person-dot" cx={person.p.x} cy={person.p.y} r={dotR} />
            {person.lines.map((line, i) => (
              <text key={i} className="person-label" x={person.tx} y={person.y1 + fs * 1.0 + fs * 1.2 * i} textAnchor="middle" fontSize={fs}>
                {line}
              </text>
            ))}
          </g>
        )}
      </svg>
    </div>
  );
}
