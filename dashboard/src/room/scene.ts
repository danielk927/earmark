/**
 * The room seen from above, drawn on a plain 2D canvas. Forward (+y) is up the screen, right (+x) is right.
 * No effects: just the room, the places, the beacons, the items, and you, moving as the position updates.
 */
import type { RoomState, Vec3 } from "./model";

export interface Beacon {
  id: string;
  label: string;
  position: Vec3;
}

const COLOR = {
  bg: "#0b1418",
  room: "#121f25",
  line: "#2b4249",
  grid: "#172a30",
  text: "#e8f0ee",
  soft: "#9fb3b1",
  mat: "#2b2340",
  user: "#e7bdeb",
  beacon: "#52e0ff",
  place: "#6f8f96",
  item: "#ffc35a",
  guide: "#8bdba5",
};

export class RoomScene {
  private canvas = document.createElement("canvas");
  private ctx: CanvasRenderingContext2D;
  private frame = 0;
  private state: RoomState | null = null;
  private shown: [number, number] = [0, 0]; // where the user is drawn, eased toward the newest position
  private yaw = 0;
  private obs: ResizeObserver;
  private scale = 100;
  private origin: [number, number] = [0, 0];
  onFloorClick: ((x: number, y: number) => void) | null = null;

  constructor(private host: HTMLElement, private beacons: Beacon[], private room = { w: 3.5, d: 3.5 }) {
    this.canvas.className = "room-canvas-2d";
    this.canvas.setAttribute("role", "img");
    this.canvas.setAttribute("aria-label", "The room seen from above: you, the beacon phones, places and items.");
    host.appendChild(this.canvas);
    this.ctx = this.canvas.getContext("2d")!;
    this.obs = new ResizeObserver(() => this.resize());
    this.obs.observe(host);
    this.canvas.addEventListener("pointerdown", this.onPointer);
    this.resize();
    this.loop();
  }

  update(s: RoomState) {
    this.state = s;
  }

  private resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = this.host.clientWidth || 1;
    const h = this.host.clientHeight || 1;
    this.canvas.width = w * dpr;
    this.canvas.height = h * dpr;
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const pad = 70;
    this.scale = Math.max(20, Math.min((w - pad * 2) / (this.room.w + 0.8), (h - pad * 2) / (this.room.d + 0.8)));
    this.origin = [w / 2, h / 2];
  }

  private px(x: number, y: number): [number, number] {
    return [this.origin[0] + x * this.scale, this.origin[1] - y * this.scale];
  }

  private onPointer = (ev: PointerEvent) => {
    if (!this.onFloorClick) return;
    const r = this.canvas.getBoundingClientRect();
    const x = (ev.clientX - r.left - this.origin[0]) / this.scale;
    const y = -(ev.clientY - r.top - this.origin[1]) / this.scale;
    this.onFloorClick(x, y);
  };

  private tag(text: string, x: number, y: number, color: string, above = true) {
    const c = this.ctx;
    c.font = '600 13px "Atkinson Hyperlegible Next", system-ui, sans-serif';
    c.textAlign = "center";
    c.textBaseline = "middle";
    const w = c.measureText(text).width + 14;
    const ty = above ? y - 16 : y + 16;
    c.fillStyle = "rgba(11,20,24,0.85)";
    c.beginPath();
    c.roundRect(x - w / 2, ty - 10, w, 20, 10);
    c.fill();
    c.strokeStyle = color;
    c.lineWidth = 1;
    c.stroke();
    c.fillStyle = color;
    c.fillText(text, x, ty + 0.5);
  }

  private draw() {
    const c = this.ctx;
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    c.clearRect(0, 0, w, h);
    c.fillStyle = COLOR.bg;
    c.fillRect(0, 0, w, h);
    const s = this.state;

    // The room and a faint grid every half meter.
    const [rx, ry] = this.px(-this.room.w / 2, this.room.d / 2);
    const rw = this.room.w * this.scale;
    const rh = this.room.d * this.scale;
    c.fillStyle = COLOR.room;
    c.fillRect(rx, ry, rw, rh);
    c.strokeStyle = COLOR.grid;
    c.lineWidth = 1;
    for (let m = -this.room.w / 2 + 0.5; m < this.room.w / 2; m += 0.5) {
      const [gx] = this.px(m, 0);
      c.beginPath();
      c.moveTo(gx, ry);
      c.lineTo(gx, ry + rh);
      c.stroke();
    }
    for (let m = -this.room.d / 2 + 0.5; m < this.room.d / 2; m += 0.5) {
      const [, gy] = this.px(0, m);
      c.beginPath();
      c.moveTo(rx, gy);
      c.lineTo(rx + rw, gy);
      c.stroke();
    }
    c.strokeStyle = COLOR.line;
    c.lineWidth = 2;
    c.strokeRect(rx, ry, rw, rh);

    // The mat, with an arrow pointing forward.
    const [mx, my] = this.px(0, 0);
    c.fillStyle = COLOR.mat;
    c.fillRect(mx - 0.45 * this.scale, my - 0.35 * this.scale, 0.9 * this.scale, 0.7 * this.scale);
    c.fillStyle = COLOR.user;
    c.globalAlpha = 0.7;
    c.beginPath();
    c.moveTo(mx, my - 0.28 * this.scale);
    c.lineTo(mx + 0.13 * this.scale, my - 0.08 * this.scale);
    c.lineTo(mx + 0.05 * this.scale, my - 0.08 * this.scale);
    c.lineTo(mx + 0.05 * this.scale, my + 0.22 * this.scale);
    c.lineTo(mx - 0.05 * this.scale, my + 0.22 * this.scale);
    c.lineTo(mx - 0.05 * this.scale, my - 0.08 * this.scale);
    c.lineTo(mx - 0.13 * this.scale, my - 0.08 * this.scale);
    c.closePath();
    c.fill();
    c.globalAlpha = 1;
    c.fillStyle = COLOR.soft;
    c.font = '12px "Atkinson Hyperlegible Next", system-ui, sans-serif';
    c.textAlign = "center";
    c.fillText("FORWARD", mx, ry - 12);

    if (!s) return;

    // Places (cupboard, drawer, ...): small squares with a name.
    for (const p of s.places) {
      if (p.kind !== "area") continue;
      const [x, y] = this.px(p.position[0], p.position[1]);
      c.fillStyle = "rgba(111,143,150,0.25)";
      c.strokeStyle = COLOR.place;
      c.lineWidth = 1.5;
      c.beginPath();
      c.roundRect(x - 16, y - 16, 32, 32, 5);
      c.fill();
      c.stroke();
      this.tag(p.label.replace(/^the /, ""), x, y + 6, COLOR.soft, false);
    }

    // Beacon phones.
    this.beacons.forEach((b, i) => {
      const [x, y] = this.px(b.position[0], b.position[1]);
      c.fillStyle = COLOR.beacon;
      c.beginPath();
      c.roundRect(x - 5, y - 9, 10, 18, 3);
      c.fill();
      this.tag(`Beacon ${i + 1}`, x, y - 8, COLOR.beacon);
    });

    // Items that have a position.
    for (const it of Object.values(s.items)) {
      if (!it.position) continue;
      const [x, y] = this.px(it.position[0], it.position[1]);
      c.fillStyle = COLOR.item;
      c.beginPath();
      c.arc(x, y, 7, 0, Math.PI * 2);
      c.fill();
      this.tag(it.name, x, y - 6, COLOR.item);
    }

    // The sound target and the line from you to it.
    const ease = 0.25;
    this.shown[0] += (s.user[0] - this.shown[0]) * ease;
    this.shown[1] += (s.user[1] - this.shown[1]) * ease;
    const target = s.headYaw === null ? 0 : s.headYaw;
    this.yaw += (target - this.yaw) * ease;
    const [ux, uy] = this.px(this.shown[0], this.shown[1]);
    if (s.guide) {
      const [gx, gy] = this.px(s.guide.target[0], s.guide.target[1]);
      c.strokeStyle = COLOR.guide;
      c.lineWidth = 2;
      c.setLineDash([8, 6]);
      c.beginPath();
      c.moveTo(ux, uy);
      c.lineTo(gx, gy);
      c.stroke();
      c.setLineDash([]);
      c.strokeStyle = COLOR.guide;
      c.beginPath();
      c.arc(gx, gy, 14, 0, Math.PI * 2);
      c.stroke();
      const d = Math.hypot(s.guide.target[0] - this.shown[0], s.guide.target[1] - this.shown[1]);
      this.tag(`${s.guide.name} · ${d.toFixed(1)} m`, gx, gy - 8, COLOR.guide);
    }

    // Where you have been.
    if (s.trail.length > 1) {
      c.strokeStyle = COLOR.user;
      c.globalAlpha = 0.45;
      c.lineWidth = 2;
      c.beginPath();
      s.trail.forEach((p, i) => {
        const [x, y] = this.px(p[0], p[1]);
        if (i === 0) c.moveTo(x, y);
        else c.lineTo(x, y);
      });
      c.stroke();
      c.globalAlpha = 1;
    }

    // You: a dot, with a short line showing which way your head points.
    c.fillStyle = COLOR.user;
    c.beginPath();
    c.arc(ux, uy, 11, 0, Math.PI * 2);
    c.fill();
    if (s.headYaw !== null) {
      const a = (this.yaw * Math.PI) / 180;
      c.strokeStyle = COLOR.user;
      c.lineWidth = 3;
      c.beginPath();
      c.moveTo(ux, uy);
      c.lineTo(ux + Math.sin(a) * 28, uy - Math.cos(a) * 28);
      c.stroke();
    }
    this.tag(s.userLive ? "You" : s.userSource === "mat" ? "You (on the mat)" : "You (last seen)", ux, uy - 8, COLOR.user);
  }

  private loop = () => {
    this.frame = requestAnimationFrame(this.loop);
    this.draw();
  };

  dispose() {
    cancelAnimationFrame(this.frame);
    this.obs.disconnect();
    this.canvas.remove();
  }
}

export function webglAvailable(): boolean {
  return !!document.createElement("canvas").getContext("2d");
}
