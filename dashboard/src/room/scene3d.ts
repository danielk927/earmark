/**
 * The room drawn in the 3Blue1Brown style: near-black, flat bright colors, a math-textbook serif. No axes or numbers.
 * Earmark's (x right, y forward, z up) maps to three's (x, y up, -z forward).
 */
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { fixLive, SYSTEM_NAME, type RoomState, type Vec3 } from "./model";
export interface Beacon {
  id: string;
  label: string;
  position: Vec3;
}

export function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

// Black on white. Things are told apart by shape and label, not by color.
const BG = 0xffffff;
const BLUE = 0x000000; // the room outline and the mat arrow
const GREEN = 0x000000; // the beacon phones
const YELLOW = 0x000000; // the item
const RED = 0x000000; // the arrow to the item

const P = (p: Vec3, lift = 0) => new THREE.Vector3(p[0], p[2] + lift, -p[1]);

function tag(html: string, cls: string): CSS2DObject {
  const el = document.createElement("div");
  el.className = `m3-tag ${cls}`;
  el.innerHTML = html;
  return new CSS2DObject(el);
}

function line(points: THREE.Vector3[], color: number, opacity = 1, dashed = false): THREE.Line {
  const mat = dashed
    ? new THREE.LineDashedMaterial({ color, transparent: true, opacity, dashSize: 0.08, gapSize: 0.06 })
    : new THREE.LineBasicMaterial({ color, transparent: true, opacity });
  const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), mat);
  if (dashed) l.computeLineDistances();
  return l;
}

/** A rounded rectangle from (x0, y0) to (x1, y1), all four corners rounded by r. */
function roundedRect(x0: number, y0: number, x1: number, y1: number, r: number): THREE.Shape {
  const s = new THREE.Shape();
  s.moveTo(x0 + r, y0);
  s.lineTo(x1 - r, y0);
  s.quadraticCurveTo(x1, y0, x1, y0 + r);
  s.lineTo(x1, y1 - r);
  s.quadraticCurveTo(x1, y1, x1 - r, y1);
  s.lineTo(x0 + r, y1);
  s.quadraticCurveTo(x0, y1, x0, y1 - r);
  s.lineTo(x0, y0 + r);
  s.quadraticCurveTo(x0, y0, x0 + r, y0);
  return s;
}

/**
 * A person standing in the room, built from rounded 3D parts. From the front it matches a sign-style figure (measured from
 * a reference, 1.8 m tall): a round head floating above one body, arms parted from the torso by a thin gap, and two
 * legs with a thin gap between them. From the side you see a round head and a rounded body, arms and legs.
 */
function buildHuman(): THREE.Group {
  const g = new THREE.Group();
  const mat = new THREE.MeshStandardMaterial({ color: 0x121212, roughness: 0.55 });
  const add = (geo: THREE.BufferGeometry, x: number, y: number, z: number, scaleZ = 1, rotZ = 0) => {
    const m = new THREE.Mesh(geo, mat);
    m.position.set(x, y, z);
    m.scale.z = scaleZ;
    m.rotation.z = rotZ;
    g.add(m);
  };
  // Head: a sphere, 0.04 m above the shoulders.
  add(new THREE.SphereGeometry(0.1335, 32, 24), 0, 1.664, 0);
  // Torso: a rounded block as wide as the two legs together. The bevel rounds every edge, and the outline is drawn
  // slightly inside so the finished width is exact.
  const bevel = 0.04;
  const torso = new THREE.ExtrudeGeometry(roundedRect(-0.181 + bevel, 0.7 + bevel, 0.181 - bevel, 1.49 - bevel, 0.05), {
    depth: 0.06, bevelEnabled: true, bevelThickness: 0.07, bevelSize: bevel, bevelSegments: 8, curveSegments: 16,
  });
  torso.translate(0, 0, -0.03);
  add(torso, 0, 0, 0);
  // Shoulders: a rounded bar across the top, joining the two arms to the torso above the point where they part.
  add(new THREE.CapsuleGeometry(0.11, 0.448, 8, 20), 0, 1.38, 0, 0.8, Math.PI / 2);
  for (const s of [-1, 1]) {
    // Arm: hangs free of the torso below the shoulder, ending in a round tip.
    add(new THREE.CapsuleGeometry(0.0645, 0.55, 8, 16), s * 0.2695, 1.15, 0, 1.1);
    // Leg: a rounded column; the gap between the legs runs from the feet to 42% of the height.
    add(new THREE.CapsuleGeometry(0.0845, 0.63, 8, 18), s * 0.0965, 0.4, 0, 0.95);
  }
  return g;
}

export class RoomModel {
  private renderer: THREE.WebGLRenderer;
  private labels = new CSS2DRenderer();
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(34, 1, 0.1, 80);
  private controls: OrbitControls;
  private clock = new THREE.Clock();
  private frame = 0;
  private obs: ResizeObserver;
  private state: RoomState | null = null;
  private itemsGroup = new THREE.Group();
  private itemsKey = "";
  private person = new THREE.Group();
  private figure = buildHuman();
  private gaze: THREE.Line;
  private personTag: CSS2DObject;
  private trail: THREE.Line;
  private arrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, -1), new THREE.Vector3(), 1, YELLOW, 0.14, 0.08);
  private waves: THREE.Mesh[] = [];
  private shown = new THREE.Vector3();
  private shownTarget = new THREE.Vector3();
  private yaw = 0;
  private yawTarget = 0;
  onFloorClick: ((x: number, y: number) => void) | null = null;

  private layout = new THREE.Group();
  private ghost = new THREE.Group();
  private ghostTag: CSS2DObject;
  private ghostShown = new THREE.Vector3();
  private ghostTarget = new THREE.Vector3();
  private layoutKey = "";

  constructor(private host: HTMLElement, private beacons: Beacon[], private room = { w: 3.5, d: 3.5 }) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setClearColor(BG);
    host.appendChild(this.renderer.domElement);
    this.labels.domElement.className = "m3-labels";
    host.appendChild(this.labels.domElement);

    this.controls = new OrbitControls(this.camera, this.labels.domElement);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = Math.PI * 0.49;
    this.controls.minDistance = 2.5;
    this.controls.maxDistance = 12;
    this.view("angle");

    // Only the person is lit (everything else is drawn flat), so the rounded body reads from every side.
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x9a9a9a, 1.6));
    const key = new THREE.DirectionalLight(0xffffff, 1.4);
    key.position.set(-3, 6, 4);
    this.scene.add(key);

    this.scene.add(this.layout);
    this.buildPlane();
    this.buildBeacons();
    this.scene.add(this.itemsGroup);

    // The other positioning system: a hollow ring on the floor, an open ring at head height, a dashed stem between, and a label.
    const ghostMat = new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.45, side: THREE.DoubleSide, depthWrite: false });
    const gHead = new THREE.Mesh(new THREE.TorusGeometry(0.12, 0.01, 8, 36), ghostMat);
    gHead.position.y = 1.55;
    const gFoot = new THREE.Mesh(new THREE.RingGeometry(0.16, 0.18, 36), ghostMat);
    gFoot.rotation.x = -Math.PI / 2;
    gFoot.position.y = 0.007;
    const gStem = line([new THREE.Vector3(0, 0.01, 0), new THREE.Vector3(0, 1.55, 0)], 0x000000, 0.35, true);
    this.ghostTag = tag("<i>Sound</i>", "m3-ghost");
    this.ghostTag.position.set(0, 1.8, 0);
    this.ghost.add(gHead, gFoot, gStem, this.ghostTag);
    this.ghost.visible = false;
    this.scene.add(this.ghost);

    this.figure.rotation.y = 0;
    this.personTag = tag("<i>You</i>", "m3-you");
    this.personTag.position.set(0, 1.95, 0);
    this.gaze = line([new THREE.Vector3(0, 0.01, 0), new THREE.Vector3(0, 0.01, -0.9)], YELLOW, 0.9);
    this.person.add(this.figure, this.personTag, this.gaze);
    this.scene.add(this.person);

    this.trail = line([], BLUE, 0.7);
    this.scene.add(this.trail);
    this.arrow.visible = false;
    this.scene.add(this.arrow);
    for (let i = 0; i < 4; i++) {
      const w = new THREE.Mesh(new THREE.TorusGeometry(1, 0.016, 8, 72), new THREE.MeshBasicMaterial({ color: BLUE, transparent: true, depthWrite: false }));
      w.visible = false;
      this.waves.push(w);
      this.scene.add(w);
    }

    this.labels.domElement.addEventListener("pointerdown", this.onPointer);
    this.obs = new ResizeObserver(() => this.resize());
    this.obs.observe(host);
    this.resize();
    this.loop();
  }

  view(kind: "angle" | "top") {
    if (kind === "top") this.camera.position.set(0, 8.6, 0.01);
    else this.camera.position.set(-3.1, 4.3, 5.3);
    this.controls.target.set(0, 0.45, 0);
    this.controls.update();
  }

  /** The floor: a plain dark slab with a thin outline, and the mat with its arrow. */
  private buildPlane() {
    const { w, d } = this.room;
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(w + 0.5, d + 0.5), new THREE.MeshBasicMaterial({ color: 0xf2f2f2 }));
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.002;
    this.layout.add(floor);
    const edge = line([
      new THREE.Vector3(-w / 2, 0.004, -d / 2), new THREE.Vector3(w / 2, 0.004, -d / 2), new THREE.Vector3(w / 2, 0.004, d / 2),
      new THREE.Vector3(-w / 2, 0.004, d / 2), new THREE.Vector3(-w / 2, 0.004, -d / 2),
    ], BLUE, 0.7);
    this.layout.add(edge);
    const mat = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 0.7), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.08, side: THREE.DoubleSide }));
    mat.rotation.x = -Math.PI / 2;
    mat.position.y = 0.002;
    this.layout.add(mat);
    const arrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, -1), new THREE.Vector3(0, 0.006, 0.2), 0.5, BLUE, 0.12, 0.08);
    this.layout.add(arrow);
  }

  /** Redraw the floor and the fixed phones when their layout changes (the hub's snapshot arrives after the scene exists). */
  setLayout(beacons: Beacon[], room: { w: number; d: number }) {
    const key = JSON.stringify([beacons, room]);
    if (key === this.layoutKey) return;
    this.layoutKey = key;
    this.beacons = beacons;
    this.room = room;
    for (const child of [...this.layout.children]) child.traverse((o) => o instanceof CSS2DObject && o.element.remove());
    this.layout.clear();
    this.buildPlane();
    this.buildBeacons();
  }

  private buildBeacons() {
    this.beacons.forEach((b, i) => {
      const top = P(b.position);
      const floor = P([b.position[0], b.position[1], 0]);
      // The phone, a small green slab at its real height, on a dotted line to the floor.
      const phone = new THREE.Mesh(new THREE.BoxGeometry(0.075, 0.15, 0.012), new THREE.MeshBasicMaterial({ color: GREEN }));
      phone.position.copy(top);
      phone.rotation.y = Math.atan2(-floor.x, -floor.z);
      this.layout.add(phone);
      this.layout.add(line([floor.clone().setY(0.005), top], GREEN, 0.5, true));
      const foot = new THREE.Mesh(new THREE.RingGeometry(0.05, 0.065, 24), new THREE.MeshBasicMaterial({ color: GREEN, side: THREE.DoubleSide }));
      foot.rotation.x = -Math.PI / 2;
      foot.position.copy(floor).setY(0.006);
      this.layout.add(foot);
      const t = tag(`<i>B</i><sub>${i + 1}</sub>`, "m3-beacon");
      t.element.title = b.label;
      t.position.copy(top).add(new THREE.Vector3(0, 0.22, 0));
      this.layout.add(t);
    });
  }

  private rebuildItems(s: RoomState) {
    const shown = Object.values(s.items).filter((i) => i.position);
    const key = JSON.stringify(shown.map((i) => [i.id, i.name, i.position]));
    if (key === this.itemsKey) return;
    this.itemsKey = key;
    for (const child of [...this.itemsGroup.children]) child.traverse((o) => o instanceof CSS2DObject && o.element.remove());
    this.itemsGroup.clear();
    for (const it of shown) {
      const p = it.position!;
      const g = new THREE.Group();
      const floor = P([p[0], p[1], 0]);
      g.position.copy(floor);
      const h = Math.max(p[2], 0.06);
      const stem = line([new THREE.Vector3(0, 0.004, 0), new THREE.Vector3(0, h, 0)], YELLOW, 0.5, true);
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.055, 20, 14), new THREE.MeshBasicMaterial({ color: YELLOW }));
      dot.position.y = h;
      const ring = new THREE.Mesh(new THREE.RingGeometry(0.07, 0.085, 28), new THREE.MeshBasicMaterial({ color: YELLOW, side: THREE.DoubleSide }));
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = 0.006;
      const t = tag(`<i>${it.name}</i>`, "m3-item");
      t.position.set(0, h + 0.17, 0);
      g.add(stem, dot, ring, t);
      this.itemsGroup.add(g);
    }
  }

  update(s: RoomState) {
    this.state = s;
    this.rebuildItems(s);
    const other = s.positioning ? (s.positioning.active === "uwb" ? "sound" : "uwb") : null;
    const og = other ? s.positioning![other] : null;
    this.ghost.visible = fixLive(og, s.now);
    if (other && og) {
      this.ghostTarget.copy(P([og.position[0], og.position[1], 0]));
      this.ghostTag.element.innerHTML = `<i>${SYSTEM_NAME[other]} (not driving audio)</i>`;
    }
    this.shownTarget.copy(P([s.user[0], s.user[1], 0]));
    this.yawTarget = -((s.headYaw ?? 0) * Math.PI) / 180;
    this.gaze.visible = s.headYaw !== null;
    this.personTag.element.innerHTML = `<i>${s.userLive ? "You" : s.userSource === "mat" ? "You (on the mat)" : "You (last seen)"}</i>`;
    const pts = s.trail.map((p) => P([p[0], p[1], 0], 0.01));
    this.trail.geometry.dispose();
    this.trail.geometry = new THREE.BufferGeometry().setFromPoints(pts.length > 1 ? pts : []);
  }

  private follow(t: number) {
    const s = this.state;
    this.shown.lerp(this.shownTarget, 0.18);
    this.person.position.copy(this.shown);
    this.ghostShown.lerp(this.ghostTarget, 0.18);
    this.ghost.position.copy(this.ghostShown);
    this.yaw += (this.yawTarget - this.yaw) * 0.25;
    this.person.rotation.y = this.yaw;
    const chest = this.shown.clone().setY(1.3);
    const g = s?.guide;
    if (g && s) {
      const to = P([g.target[0], g.target[1], 0], 0.02);
      const from = this.shown.clone().setY(0.02);
      const dir = to.clone().sub(from);
      const len = dir.length();
      this.arrow.visible = len > 0.15;
      if (len > 0.15) {
        this.arrow.position.copy(from);
        this.arrow.setDirection(dir.clone().normalize());
        this.arrow.setLength(len, 0.16, 0.09);
        this.arrow.setColor(RED);
      }
      const src = P(g.target);
      const dst = chest;
      this.waves.forEach((w, i) => {
        const k = (t * 0.65 + i / this.waves.length) % 1;
        w.visible = true;
        w.position.copy(src.clone().lerp(dst, k));
        w.lookAt(dst);
        w.scale.setScalar(0.1 + k * 0.32);
        (w.material as THREE.MeshBasicMaterial).opacity = Math.sin(k * Math.PI) * 0.95;
      });
    } else {
      this.arrow.visible = false;
      for (const w of this.waves) w.visible = false;
    }
  }

  private loop = () => {
    this.frame = requestAnimationFrame(this.loop);
    this.follow(this.clock.getElapsedTime());
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.labels.render(this.scene, this.camera);
  };

  private onPointer = (ev: PointerEvent) => {
    if (!this.onFloorClick || !ev.shiftKey) return;
    const r = this.labels.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, this.camera);
    const hit = new THREE.Vector3();
    if (ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), hit)) this.onFloorClick(hit.x, -hit.z);
  };

  private resize() {
    const w = this.host.clientWidth || 1;
    const h = this.host.clientHeight || 1;
    this.renderer.setSize(w, h);
    this.labels.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  dispose() {
    cancelAnimationFrame(this.frame);
    this.obs.disconnect();
    this.controls.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.labels.domElement.remove();
  }
}
