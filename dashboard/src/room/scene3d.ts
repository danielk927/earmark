/**
 * The room drawn in the 3Blue1Brown style: near-black, flat bright colors, a math-textbook serif. No axes or numbers.
 * Earmark's (x right, y forward, z up) maps to three's (x, y up, -z forward).
 */
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import type { RoomState, Vec3 } from "./model";
import type { Beacon } from "./scene";

// Black and white: white and greys on black. Things are told apart by shape, brightness and label, not by color.
const BG = 0x050505;
const BLUE = 0xcfcfcf; // the figure and the mat: light grey
const GREEN = 0xffffff; // the beacon phones: white
const YELLOW = 0xffffff; // the item: a bright white dot
const RED = 0xffffff; // the arrow to the item

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

/** A person you would recognise: head, neck, torso, two arms, two legs, drawn as flat blue shapes with bright edges. */
function buildHuman(): THREE.Group {
  const g = new THREE.Group();
  const fill = new THREE.MeshBasicMaterial({ color: 0x161616 });
  const edge = new THREE.LineBasicMaterial({ color: BLUE });
  const part = (geo: THREE.BufferGeometry, x: number, y: number, z: number, rx = 0, rz = 0, angle = 25) => {
    const m = new THREE.Mesh(geo, fill);
    m.position.set(x, y, z);
    m.rotation.set(rx, 0, rz);
    m.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo, angle), edge));
    g.add(m);
    return m;
  };
  part(new THREE.SphereGeometry(0.115, 12, 8), 0, 1.62, 0, 0, 0, 1); // head: a few facets so its outline shows
  part(new THREE.CylinderGeometry(0.04, 0.045, 0.1, 10), 0, 1.47, 0); // neck
  part(new THREE.CylinderGeometry(0.2, 0.15, 0.58, 14), 0, 1.15, 0); // torso, broad at the shoulders
  part(new THREE.CylinderGeometry(0.15, 0.17, 0.14, 14), 0, 0.82, 0); // hips
  for (const s of [-1, 1]) {
    part(new THREE.CapsuleGeometry(0.045, 0.52, 4, 10), s * 0.265, 1.18, -0.07, -0.25, s * 0.07); // arm, hanging a little forward
    part(new THREE.CapsuleGeometry(0.06, 0.66, 4, 10), s * 0.085, 0.4, 0); // leg
    part(new THREE.BoxGeometry(0.1, 0.05, 0.2), s * 0.085, 0.025, -0.05); // foot
  }
  // A small wedge on the face shows which way the head points.
  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.03, 0.08, 10), new THREE.MeshBasicMaterial({ color: YELLOW }));
  nose.rotation.x = -Math.PI / 2;
  nose.position.set(0, 1.62, -0.14);
  g.add(nose);
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

    this.buildPlane();
    this.buildBeacons();
    this.scene.add(this.itemsGroup);

    this.figure.rotation.y = 0;
    this.personTag = tag("<i>You</i>", "m3-you");
    this.personTag.position.set(0, 1.95, 0);
    this.gaze = line([new THREE.Vector3(0, 0.01, 0), new THREE.Vector3(0, 0.01, -0.9)], YELLOW, 0.9);
    this.person.add(this.figure, this.personTag, this.gaze);
    this.scene.add(this.person);

    this.trail = line([], BLUE, 0.5);
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
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(w + 0.5, d + 0.5), new THREE.MeshBasicMaterial({ color: 0x0e0e0e }));
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.002;
    this.scene.add(floor);
    const edge = line([
      new THREE.Vector3(-w / 2, 0.004, -d / 2), new THREE.Vector3(w / 2, 0.004, -d / 2), new THREE.Vector3(w / 2, 0.004, d / 2),
      new THREE.Vector3(-w / 2, 0.004, d / 2), new THREE.Vector3(-w / 2, 0.004, -d / 2),
    ], BLUE, 0.5);
    this.scene.add(edge);
    const mat = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 0.7), new THREE.MeshBasicMaterial({ color: BLUE, transparent: true, opacity: 0.14, side: THREE.DoubleSide }));
    mat.rotation.x = -Math.PI / 2;
    mat.position.y = 0.002;
    this.scene.add(mat);
    const arrow = new THREE.ArrowHelper(new THREE.Vector3(0, 0, -1), new THREE.Vector3(0, 0.006, 0.2), 0.5, BLUE, 0.12, 0.08);
    this.scene.add(arrow);
  }

  private buildBeacons() {
    this.beacons.forEach((b, i) => {
      const top = P(b.position);
      const floor = P([b.position[0], b.position[1], 0]);
      // The phone, a small green slab at its real height, on a dotted line to the floor.
      const phone = new THREE.Mesh(new THREE.BoxGeometry(0.075, 0.15, 0.012), new THREE.MeshBasicMaterial({ color: GREEN }));
      phone.position.copy(top);
      phone.rotation.y = Math.atan2(-floor.x, -floor.z);
      this.scene.add(phone);
      this.scene.add(line([floor.clone().setY(0.005), top], GREEN, 0.5, true));
      const foot = new THREE.Mesh(new THREE.RingGeometry(0.05, 0.065, 24), new THREE.MeshBasicMaterial({ color: GREEN, side: THREE.DoubleSide }));
      foot.rotation.x = -Math.PI / 2;
      foot.position.copy(floor).setY(0.006);
      this.scene.add(foot);
      const t = tag(`<i>B</i><sub>${i + 1}</sub>`, "m3-beacon");
      t.position.copy(top).add(new THREE.Vector3(0, 0.22, 0));
      this.scene.add(t);
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
    this.yaw += (this.yawTarget - this.yaw) * 0.25;
    this.person.rotation.y = this.yaw;
    this.personTag.element.style.transform = ""; // the tag stays upright (CSS2D), only the figure turns
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
