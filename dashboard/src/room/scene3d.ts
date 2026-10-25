/**
 * The room as a small architectural model on a light table, drawn with three.js.
 * Earmark's (x right, y forward, z up) maps to three's (x, y up, -z forward), so forward points away from the camera.
 * The only motion is the sound: cobalt waves travel from the item to you while you are being guided.
 */
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import type { RoomState, Vec3 } from "./model";
import type { Beacon } from "./scene";

const INK = 0x22272b;
const PAPER = 0xe9e7e1;
const FLOOR = 0xdddad3;
const SOUND = 0x2f4bff;
const THING = 0xff5b3a;

const P = (p: Vec3, lift = 0) => new THREE.Vector3(p[0], p[2] + lift, -p[1]);

function tag(text: string, cls: string): CSS2DObject {
  const el = document.createElement("div");
  el.className = `m3-tag ${cls}`;
  el.textContent = text;
  return new CSS2DObject(el);
}

export class RoomModel {
  private renderer: THREE.WebGLRenderer;
  private labels = new CSS2DRenderer();
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(36, 1, 0.1, 60);
  private controls: OrbitControls;
  private clock = new THREE.Clock();
  private frame = 0;
  private obs: ResizeObserver;
  private state: RoomState | null = null;
  private itemsGroup = new THREE.Group();
  private itemsKey = "";
  private person = new THREE.Group();
  private gaze: THREE.Mesh;
  private personTag: CSS2DObject;
  private trail: THREE.Line;
  private route: THREE.Line;
  private stem: THREE.Mesh;
  private targetTag: CSS2DObject;
  private waves: THREE.Mesh[] = [];
  private shown = new THREE.Vector3();
  private shownTarget = new THREE.Vector3();
  private yaw = 0;
  private yawTarget = 0;
  onFloorClick: ((x: number, y: number) => void) | null = null;

  constructor(private host: HTMLElement, private beacons: Beacon[], private room = { w: 3.5, d: 3.5 }) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setClearColor(PAPER);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    host.appendChild(this.renderer.domElement);
    this.labels.domElement.className = "m3-labels";
    host.appendChild(this.labels.domElement);
    this.scene.background = new THREE.Color(PAPER);

    this.controls = new OrbitControls(this.camera, this.labels.domElement);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = Math.PI * 0.47;
    this.controls.minDistance = 2.5;
    this.controls.maxDistance = 11;
    this.view("angle");

    this.scene.add(new THREE.HemisphereLight(0xffffff, 0xcfcbc2, 1.15));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(-3.5, 7, 4.5);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.camera.left = -4;
    sun.shadow.camera.right = 4;
    sun.shadow.camera.top = 4;
    sun.shadow.camera.bottom = -4;
    sun.shadow.radius = 5;
    sun.shadow.bias = -0.0004;
    this.scene.add(sun);

    this.buildTable();
    this.buildBeacons();
    this.scene.add(this.itemsGroup);

    // The person: a charcoal figure, with a cobalt cone on the floor showing where the head points.
    const ink = new THREE.MeshStandardMaterial({ color: INK, roughness: 0.55 });
    const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.12, 0.9, 8, 20), ink);
    body.position.y = 0.14 + 0.475;
    body.castShadow = true;
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.115, 28, 20), ink);
    head.position.y = 1.52;
    head.castShadow = true;
    const cone = new THREE.Shape();
    cone.moveTo(0, 0);
    cone.absarc(0, 0, 1.0, Math.PI / 2 - 0.38, Math.PI / 2 + 0.38, false);
    cone.lineTo(0, 0);
    this.gaze = new THREE.Mesh(
      new THREE.ShapeGeometry(cone, 28),
      new THREE.MeshBasicMaterial({ color: SOUND, transparent: true, opacity: 0.16, side: THREE.DoubleSide, depthWrite: false }),
    );
    this.gaze.rotation.x = -Math.PI / 2;
    this.gaze.position.y = 0.045;
    const foot = new THREE.Mesh(new THREE.RingGeometry(0.2, 0.235, 48), new THREE.MeshBasicMaterial({ color: INK, side: THREE.DoubleSide }));
    foot.rotation.x = -Math.PI / 2;
    foot.position.y = 0.047;
    this.personTag = tag("You", "m3-you");
    this.personTag.position.set(0, 1.85, 0);
    this.person.add(body, head, this.gaze, foot, this.personTag);
    this.scene.add(this.person);

    const lineMat = new THREE.LineBasicMaterial({ color: INK, transparent: true, opacity: 0.35 });
    this.trail = new THREE.Line(new THREE.BufferGeometry(), lineMat);
    this.scene.add(this.trail);
    this.route = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineDashedMaterial({ color: SOUND, dashSize: 0.1, gapSize: 0.07 }));
    this.scene.add(this.route);
    this.stem = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 1, 8), new THREE.MeshBasicMaterial({ color: SOUND }));
    this.scene.add(this.stem);
    this.targetTag = tag("", "m3-target");
    this.scene.add(this.targetTag);
    for (let i = 0; i < 4; i++) {
      const w = new THREE.Mesh(new THREE.TorusGeometry(1, 0.022, 8, 72), new THREE.MeshBasicMaterial({ color: SOUND, transparent: true, depthWrite: false }));
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
    if (kind === "top") this.camera.position.set(0, 8.4, 0.01);
    else this.camera.position.set(-2.9, 4.1, 5.4);
    this.controls.target.set(0, 0.35, 0);
    this.controls.update();
  }

  private buildTable() {
    const { w, d } = this.room;
    const slab = new THREE.Mesh(new THREE.BoxGeometry(w + 0.7, 0.08, d + 0.7), new THREE.MeshStandardMaterial({ color: FLOOR, roughness: 0.95 }));
    slab.position.y = -0.04;
    slab.receiveShadow = true;
    slab.name = "floor";
    this.scene.add(slab);
    // A faint grid every half meter, and the room's edge drawn as a thin charcoal outline.
    const grid = new THREE.GridHelper(Math.max(w, d), Math.round(Math.max(w, d) / 0.5), INK, INK);
    (grid.material as THREE.Material).transparent = true;
    (grid.material as THREE.Material).opacity = 0.07;
    grid.position.y = 0.002;
    this.scene.add(grid);
    const outline = new THREE.LineLoop(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(-w / 2, 0.004, -d / 2), new THREE.Vector3(w / 2, 0.004, -d / 2),
        new THREE.Vector3(w / 2, 0.004, d / 2), new THREE.Vector3(-w / 2, 0.004, d / 2),
      ]),
      new THREE.LineBasicMaterial({ color: INK, transparent: true, opacity: 0.55 }),
    );
    this.scene.add(outline);
    // The mat: a low charcoal slab with an arrow pointing forward.
    const mat = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.03, 0.7), new THREE.MeshStandardMaterial({ color: INK, roughness: 0.8 }));
    mat.position.y = 0.015;
    mat.castShadow = true;
    mat.receiveShadow = true;
    this.scene.add(mat);
    const arrow = new THREE.Shape();
    arrow.moveTo(-0.05, -0.2);
    arrow.lineTo(0.05, -0.2);
    arrow.lineTo(0.05, 0.05);
    arrow.lineTo(0.14, 0.05);
    arrow.lineTo(0, 0.26);
    arrow.lineTo(-0.14, 0.05);
    arrow.lineTo(-0.05, 0.05);
    const a = new THREE.Mesh(new THREE.ShapeGeometry(arrow), new THREE.MeshBasicMaterial({ color: PAPER }));
    a.rotation.x = -Math.PI / 2;
    a.position.y = 0.032;
    this.scene.add(a);
  }

  private buildBeacons() {
    const ink = new THREE.MeshStandardMaterial({ color: INK, roughness: 0.6 });
    this.beacons.forEach((b, i) => {
      const g = new THREE.Group();
      const base = P([b.position[0], b.position[1], 0]);
      g.position.copy(base);
      const h = Math.max(b.position[2], 0.1);
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, h, 10), ink);
      pole.position.y = h / 2;
      pole.castShadow = true;
      const foot = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.02, 24), ink);
      foot.position.y = 0.01;
      foot.castShadow = true;
      // A phone, standing up, its screen turned toward the middle of the room.
      const phone = new THREE.Mesh(new THREE.BoxGeometry(0.075, 0.155, 0.01), new THREE.MeshStandardMaterial({ color: 0x0f1316, roughness: 0.3, metalness: 0.4 }));
      phone.position.y = h + 0.08;
      phone.castShadow = true;
      phone.lookAt(new THREE.Vector3(0, h + 0.08, 0).sub(base).multiplyScalar(-1).add(new THREE.Vector3(0, 0, 0)));
      phone.rotation.y = Math.atan2(-base.x, -base.z);
      phone.rotation.x = 0;
      const light = new THREE.Mesh(new THREE.PlaneGeometry(0.06, 0.135), new THREE.MeshBasicMaterial({ color: SOUND }));
      light.position.z = 0.0056;
      phone.add(light);
      const t = tag(String(i + 1), "m3-beacon");
      t.position.set(0, h + 0.3, 0);
      g.add(pole, foot, phone, t);
      this.scene.add(g);
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
      g.position.copy(P([p[0], p[1], 0]));
      const h = Math.max(p[2], 0.08);
      const thin = new THREE.Mesh(new THREE.CylinderGeometry(0.006, 0.006, h, 6), new THREE.MeshBasicMaterial({ color: THING, transparent: true, opacity: 0.55 }));
      thin.position.y = h / 2;
      const bead = new THREE.Mesh(new THREE.SphereGeometry(0.06, 24, 16), new THREE.MeshStandardMaterial({ color: THING, roughness: 0.35 }));
      bead.position.y = h;
      bead.castShadow = true;
      const shadow = new THREE.Mesh(new THREE.CircleGeometry(0.07, 24), new THREE.MeshBasicMaterial({ color: THING, transparent: true, opacity: 0.35 }));
      shadow.rotation.x = -Math.PI / 2;
      shadow.position.y = 0.006;
      const t = tag(it.name, "m3-item");
      t.position.set(0, h + 0.17, 0);
      g.add(thin, bead, shadow, t);
      this.itemsGroup.add(g);
    }
  }

  update(s: RoomState) {
    this.state = s;
    this.rebuildItems(s);
    this.shownTarget.copy(P([s.user[0], s.user[1], 0]));
    this.yawTarget = -((s.headYaw ?? 0) * Math.PI) / 180;
    this.gaze.visible = s.headYaw !== null;
    this.personTag.element.textContent = s.userLive ? "You" : s.userSource === "mat" ? "You (on the mat)" : "You (last seen)";
    const pts = s.trail.map((p) => P([p[0], p[1], 0], 0.012));
    this.trail.geometry.dispose();
    this.trail.geometry = new THREE.BufferGeometry().setFromPoints(pts.length > 1 ? pts : []);
    const g = s.guide;
    for (const o of [this.route, this.stem, this.targetTag]) o.visible = !!g;
    if (g) {
      const to = P([g.target[0], g.target[1], 0], 0.012);
      this.route.geometry.dispose();
      this.route.geometry = new THREE.BufferGeometry().setFromPoints([this.shown.clone().setY(0.012), to]);
      this.route.computeLineDistances();
      const h = Math.max(g.target[2], 0.1);
      this.stem.scale.y = h;
      this.stem.position.copy(P([g.target[0], g.target[1], h / 2]));
      const d = Math.hypot(g.target[0] - s.user[0], g.target[1] - s.user[1]);
      this.targetTag.element.textContent = `${g.name}, ${d.toFixed(1)} m`;
      this.targetTag.position.copy(P(g.target, 0.3));
    }
  }

  private loop = () => {
    this.frame = requestAnimationFrame(this.loop);
    const t = this.clock.getElapsedTime();
    this.shown.lerp(this.shownTarget, 0.18);
    this.person.position.copy(this.shown);
    this.yaw += (this.yawTarget - this.yaw) * 0.25;
    this.gaze.rotation.z = this.yaw;
    const g = this.state?.guide;
    if (g) {
      this.route.geometry.dispose();
      this.route.geometry = new THREE.BufferGeometry().setFromPoints([this.shown.clone().setY(0.012), P([g.target[0], g.target[1], 0], 0.012)]);
      this.route.computeLineDistances();
      const from = P(g.target);
      const to = this.shown.clone().setY(1.45);
      this.waves.forEach((w, i) => {
        const k = (t * 0.65 + i / this.waves.length) % 1;
        w.visible = true;
        w.position.copy(from.clone().lerp(to, k));
        w.lookAt(to);
        w.scale.setScalar(0.1 + k * 0.3);
        (w.material as THREE.MeshBasicMaterial).opacity = Math.sin(k * Math.PI) * 0.9;
      });
    } else {
      for (const w of this.waves) w.visible = false;
    }
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
