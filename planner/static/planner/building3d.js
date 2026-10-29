"use strict";
// Construction: the Building 3D tab. The building (design.building, see ftth/building.py) is drawn in 3D with
// three.js, designed automatically from a brief (server: /building/generate) and edited by hand: walls, doors,
// windows, columns, stairs, floors and the roof. Edits go through changed() like the rest of the planner, so
// they save, undo and feed the quantities, checks and plans. Also: GLB / OBJ / STL / DXF 3D export, the
// building's footprint on the site plan, and the Overview panel.
// Building metres: x east, y north, z up. three.js: x east, y up, z south (z = -y).

const BLD = { ready: null, scene: null, cam3d: null, camPlan: null, renderer: null, controls: null, root: null,
  tool: "select", sel: null, level: 0, plan: false, draft: null, fitted: false, formMade: false };
const THREE_FILES = [  // three.js r147: the last release with plain scripts (the site's CSP has no import maps)
  ["https://unpkg.com/three@0.147.0/build/three.min.js", "sha384-vV17nr/rMaJqmeZkFUzXLpHdQ+ME5QHKdydaqqN+3Ga39RJlNrTatJxHwGV4ml2C"],
  ["https://unpkg.com/three@0.147.0/examples/js/controls/OrbitControls.js", "sha384-I0DMsfimAPIqWT8lF+oA997gRgdUi3jhidoTq3fN0zmn35smXZukD01FLnsPRU9i"],
  ["https://unpkg.com/three@0.147.0/examples/js/exporters/GLTFExporter.js", "sha384-fz8UmA1wT7KrA88we2948dh8iOo318hFy6/Azeb0sQov7fG1qhPIdOpCOwin+Fd7"],
  ["https://unpkg.com/three@0.147.0/examples/js/exporters/OBJExporter.js", "sha384-NnELFiXZTa+K9Hhvw72IjZ8Ym9IEKrvw3ldzCTkWmzq1Q87vQEfq70mJsQnCk/dp"],
  ["https://unpkg.com/three@0.147.0/examples/js/exporters/STLExporter.js", "sha384-8KqhVyaWXdIlvz2t7y+lw7mF4xAlF7mfrxo3ydZiCssnpQpn8F7azNk6pZ6KNhk9"],
];
function loadThree() {  // only when the Building 3D tab is first opened
  BLD.ready ||= THREE_FILES.reduce((p, [src, integrity]) => p.then(() => new Promise((ok, fail) => {
    const s = document.createElement("script");
    Object.assign(s, { src, integrity, crossOrigin: "anonymous", onload: ok, onerror: () => fail(new Error("Could not load the 3D viewer")) });
    document.head.appendChild(s);
  })), Promise.resolve());
  return BLD.ready;
}

const isConstruction = () => !!S.st?.sector?.construction;
const bmsg = (t) => { $("#bldMsg").textContent = t; };
function bnextId(coll, prefix) {
  const ids = new Set((S.D.building?.[coll] || []).map((x) => x.id));
  let i = 1;
  while (ids.has(prefix + String(i).padStart(3, "0"))) i++;
  return prefix + String(i).padStart(3, "0");
}
const lvlOf = (b, k) => b.levels[Math.min(k, b.levels.length - 1)];
const wallH = (b, w) => w.height || lvlOf(b, w.level).height;
const wallLen = (w) => Math.hypot(w.b[0] - w.a[0], w.b[1] - w.a[1]);

// ---- the 3D model ----------------------------------------------------------------------------------------
const MAT = {};
function mats() {
  if (MAT.wall) return MAT;
  const m = (c, o = {}) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.85, metalness: 0, ...o });
  Object.assign(MAT, { wall: m(0xe8e4dc), wallInt: m(0xf4f1ea), slab: m(0xb9bec4), glass: m(0x8fc4e8, { transparent: true, opacity: 0.45 }),
    door: m(0x9a6a3f), roofSheet: m(0x5e6b78, { side: THREE.DoubleSide }), roofTile: m(0x8a4b38, { side: THREE.DoubleSide }),
    stair: m(0xa9adb3), column: m(0x8d949c), cut: m(0x3b4148), sel: m(0x00b7ff, { emissive: 0x003a55 }), ghost: m(0x00b7ff, { transparent: true, opacity: 0.35 }) });
  return MAT;
}
let UNIT_BOX = null;  // one 1 m box, scaled, for every wall piece, step and column: a tower has thousands of them
const unitBox = () => UNIT_BOX || (UNIT_BOX = new THREE.BoxGeometry(1, 1, 1).toNonIndexed());
function boxAlong(a, b, s0, s1, z0, z1, t, mat) {  // part of a wall a->b between s0, s1 (m) and heights z0, z1
  const L = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, ux = (b[0] - a[0]) / L, uy = (b[1] - a[1]) / L;
  const mesh = new THREE.Mesh(unitBox(), mat);
  mesh.scale.set(Math.max(s1 - s0, 0.001), Math.max(z1 - z0, 0.001), t);
  const cx = a[0] + ux * (s0 + s1) / 2, cy = a[1] + uy * (s0 + s1) / 2;
  mesh.position.set(cx, (z0 + z1) / 2, -cy);
  mesh.rotation.y = Math.atan2(uy, ux);
  return mesh;
}
function tag(mesh, type, id) { mesh.userData = { type, id }; return mesh; }

function wallMeshes(b, w, group, opsByWall, cut) {  // cut: a plan, where walls are drawn dark against the floor
  const M = mats(), L = wallLen(w), base = lvlOf(b, w.level).elevation, H = wallH(b, w);
  const mat = cut ? M.cut : w.kind === "external" ? M.wall : M.wallInt;
  const ops = (opsByWall.get(w.id) || []).sort((p, q) => p.offset - q.offset);
  let s = 0;
  for (const o of ops) {
    const s0 = Math.max(0, o.offset - o.width / 2), s1 = Math.min(L, o.offset + o.width / 2);
    if (s0 > s) group.add(tag(boxAlong(w.a, w.b, s, s0, base, base + H, w.thickness, mat), "wall", w.id));
    if (o.sill > 0) group.add(tag(boxAlong(w.a, w.b, s0, s1, base, base + o.sill, w.thickness, mat), "wall", w.id));
    if (o.sill + o.height < H) group.add(tag(boxAlong(w.a, w.b, s0, s1, base + o.sill + o.height, base + H, w.thickness, mat), "wall", w.id));
    const fill = o.kind === "window" ? M.glass : M.door;
    group.add(tag(boxAlong(w.a, w.b, s0, s1, base + o.sill, base + o.sill + o.height, o.kind === "window" ? 0.03 : 0.05, fill), "opening", o.id));
    s = Math.max(s, s1);
  }
  if (L > s) group.add(tag(boxAlong(w.a, w.b, s, L, base, base + H, w.thickness, mat), "wall", w.id));
}

function slabMesh(b, sl) {
  const shape = new THREE.Shape(sl.outline.map(([x, y]) => new THREE.Vector2(x, y)));
  const g = new THREE.ExtrudeGeometry(shape, { depth: sl.thickness, bevelEnabled: false });
  g.rotateX(-Math.PI / 2);  // shape x, y -> three x, -z; extrusion -> up
  const top = sl.level < b.levels.length ? lvlOf(b, sl.level).elevation : lvlOf(b, b.levels.length - 1).elevation + lvlOf(b, b.levels.length - 1).height + sl.thickness;
  const mesh = new THREE.Mesh(g, mats().slab);
  mesh.position.y = top - sl.thickness;
  return tag(mesh, "slab", sl.id);
}

// a roof as triangles, in the same geometry as ftth/building.py roof_geometry
function roofMesh(b, r) {
  if (r.kind === "flat") {  // a flat roof is its slab; its parapet, if any, is a low wall round the edge
    if (!(r.parapet > 0)) return null;
    const lv = lvlOf(b, r.level), z0 = lv.elevation + lv.height, t = 0.2, grp = new THREE.Group();
    const c = [[r.x0, r.y0], [r.x1, r.y0], [r.x1, r.y1], [r.x0, r.y1]];
    for (let i = 0; i < 4; i++) {
      const a = c[i], e = c[(i + 1) % 4], L = Math.hypot(e[0] - a[0], e[1] - a[1]);
      grp.add(tag(boxAlong(a, e, 0, L, z0, z0 + r.parapet, t, mats().wall), "roof", r.id));
    }
    return grp;
  }
  const lv = lvlOf(b, r.level), ze = lv.elevation + lv.height, o = r.overhang;
  const X0 = r.x0 - o, X1 = r.x1 + o, Y0 = r.y0 - o, Y1 = r.y1 + o;
  const t = Math.tan(r.pitch * Math.PI / 180);
  // work in (along, across) with the ridge along "along"
  const alongX = r.ridge === "x";
  const A0 = alongX ? X0 : Y0, A1 = alongX ? X1 : Y1, C0 = alongX ? Y0 : X0, C1 = alongX ? Y1 : X1;
  const P = (a, c, z) => alongX ? [a, c, z] : [c, a, z];
  const tris = [];
  const quad = (p, q, r2, s) => { tris.push([p, q, r2], [p, r2, s]); };
  if (r.kind === "shed") {  // high along C1
    const zr = ze + (C1 - C0) * t;
    quad(P(A0, C0, ze), P(A1, C0, ze), P(A1, C1, zr), P(A0, C1, zr));
    tris.push([P(A0, C0, ze), P(A0, C1, zr), P(A0, C1, ze)], [P(A1, C0, ze), P(A1, C1, ze), P(A1, C1, zr)]);
    quad(P(A0, C1, ze), P(A0, C1, zr), P(A1, C1, zr), P(A1, C1, ze));
  } else {
    const cm = (C0 + C1) / 2, zr = ze + (C1 - C0) / 2 * t;
    const h = r.kind === "hip" ? Math.min((C1 - C0) / 2, (A1 - A0) / 2) : 0;
    quad(P(A0, C0, ze), P(A1, C0, ze), P(A1 - h, cm, zr), P(A0 + h, cm, zr));
    quad(P(A1, C1, ze), P(A0, C1, ze), P(A0 + h, cm, zr), P(A1 - h, cm, zr));
    if (r.kind === "hip") tris.push([P(A0, C1, ze), P(A0, C0, ze), P(A0 + h, cm, zr)], [P(A1, C0, ze), P(A1, C1, ze), P(A1 - h, cm, zr)]);
    else tris.push([P(A0, C0, ze), P(A0, cm, zr), P(A0, C1, ze)], [P(A1, C1, ze), P(A1, cm, zr), P(A1, C0, ze)]);  // gable ends
  }
  const pos = [];
  for (const tri of tris) for (const [x, y, z] of tri) pos.push(x, z, -y);
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.computeVertexNormals();
  return tag(new THREE.Mesh(g, r.covering === "tiles" ? mats().roofTile : mats().roofSheet), "roof", r.id);
}

function stairMeshes(b, st, group) {
  const lv = lvlOf(b, st.level), n = Math.max(1, Math.ceil(lv.height / st.max_riser - 1e-9)), rise = lv.height / n;
  const a = st.angle * Math.PI / 180, ux = Math.cos(a), uy = Math.sin(a);
  for (let i = 0; i < n; i++) {  // solid steps, each reaching the ground
    const s0 = i * st.tread, s1 = s0 + st.tread;
    const m = boxAlong([st.x, st.y], [st.x + ux, st.y + uy], s0, s1, lv.elevation, lv.elevation + (i + 1) * rise, st.width, mats().stair);
    group.add(tag(m, "stair", st.id));
  }
}

function buildingGroup(b, maxLevel, only = null) {  // only: a plan of that one level (no roof, nothing above)
  const g = new THREE.Group(), M = mats();
  const show = (lv) => only === null ? lv <= maxLevel : lv === only;
  const opsByWall = new Map();
  for (const o of b.openings) (opsByWall.get(o.wall) || opsByWall.set(o.wall, []).get(o.wall)).push(o);
  for (const w of b.walls) if (show(w.level)) wallMeshes(b, w, g, opsByWall, only !== null);
  for (const sl of b.slabs) {  // the roof slab of a flat roof only with the top floor, never in a plan
    const roofSlab = sl.level >= b.levels.length;
    if (roofSlab ? only === null && maxLevel >= b.levels.length - 1 : show(sl.level)) g.add(slabMesh(b, sl));
  }
  for (const st of b.stairs) if (show(st.level)) stairMeshes(b, st, g);
  for (const c of b.columns) if (show(c.level)) {
    const lv = lvlOf(b, c.level), m = new THREE.Mesh(unitBox(), M.column);
    m.scale.set(c.size, lv.height, c.size);
    m.position.set(c.x, lv.elevation + lv.height / 2, -c.y);
    g.add(tag(m, "column", c.id));
  }
  if (only === null && maxLevel >= b.levels.length - 1) for (const r of b.roofs) { const m = roofMesh(b, r); if (m) g.add(m); }
  return g;
}

// One mesh per material for the view: a tower is thousands of boxes, and a draw call each made it crawl (25
// floors: 7,600 calls, 7 fps). Each merged mesh keeps its parts' triangle ranges, so a click still finds the
// wall, opening, slab... it hit (partAt). Exports keep the separate, tagged meshes.
function batchGroup(g) {
  const byMat = new Map(), out = new THREE.Group();
  g.updateMatrixWorld(true);
  for (const o of g.children) if (o.isMesh) (byMat.get(o.material) || byMat.set(o.material, []).get(o.material)).push(o);
  const v = new THREE.Vector3(), nm = new THREE.Matrix3();
  for (const [mat, list] of byMat) {
    const geos = list.map((o) => o.geometry.index ? o.geometry.toNonIndexed() : o.geometry);
    const n = geos.reduce((a, x) => a + x.attributes.position.count, 0);
    const pos = new Float32Array(n * 3), nor = new Float32Array(n * 3), parts = [];
    let k = 0;
    geos.forEach((x, i) => {
      const P = x.attributes.position, N = x.attributes.normal, M = list[i].matrixWorld;
      nm.getNormalMatrix(M);
      for (let j = 0; j < P.count; j++, k++) {
        v.fromBufferAttribute(P, j).applyMatrix4(M); pos[k * 3] = v.x; pos[k * 3 + 1] = v.y; pos[k * 3 + 2] = v.z;
        v.fromBufferAttribute(N, j).applyMatrix3(nm).normalize(); nor[k * 3] = v.x; nor[k * 3 + 1] = v.y; nor[k * 3 + 2] = v.z;
      }
      parts.push({ end: k / 3, type: list[i].userData.type, id: list[i].userData.id });  // end: first triangle after it
    });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("normal", new THREE.BufferAttribute(nor, 3));
    const m = new THREE.Mesh(geo, mat);
    m.userData.parts = parts;
    out.add(m);
  }
  return out;
}
function partAt(hit) {  // the {type, id} of the part of a merged mesh that a ray hit
  const p = hit.object.userData.parts;
  if (!p) return { type: hit.object.userData.type, id: hit.object.userData.id };
  let lo = 0, hi = p.length - 1;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (p[mid].end > hit.faceIndex) hi = mid; else lo = mid + 1; }
  return { type: p[lo].type, id: p[lo].id };
}

// ---- view ------------------------------------------------------------------------------------------------
function setupScene() {
  const box = $("#bld3d");
  BLD.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  BLD.renderer.setPixelRatio(window.devicePixelRatio || 1);
  box.appendChild(BLD.renderer.domElement);
  BLD.scene = new THREE.Scene();
  BLD.scene.background = new THREE.Color(0xdfe7ef);
  BLD.scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 0.85));
  const sun = new THREE.DirectionalLight(0xffffff, 0.75);
  sun.position.set(30, 50, 20);
  BLD.scene.add(sun);
  BLD.cam3d = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
  BLD.camPlan = new THREE.OrthographicCamera(-20, 20, 20, -20, -1000, 1000);
  BLD.controls = new THREE.OrbitControls(BLD.cam3d, BLD.renderer.domElement);
  BLD.controls.addEventListener("change", draw);
  BLD.grid = new THREE.GridHelper(200, 200, 0x9aa7b4, 0xc5cdd6);
  BLD.scene.add(BLD.grid);
  BLD.preview = new THREE.Group();
  BLD.scene.add(BLD.preview);
  new ResizeObserver(() => { resize(); draw(); }).observe(box);
  bindPointer(BLD.renderer.domElement);
  resize();
}
function camera() { return BLD.plan ? BLD.camPlan : BLD.cam3d; }
function resize() {
  const box = $("#bld3d"), w = box.clientWidth || 600, h = box.clientHeight || 420;
  BLD.renderer.setSize(w, h);
  BLD.cam3d.aspect = w / h;
  BLD.cam3d.updateProjectionMatrix();
  const k = (BLD.camPlan.top - BLD.camPlan.bottom) / 2;
  Object.assign(BLD.camPlan, { left: -k * w / h, right: k * w / h });
  BLD.camPlan.updateProjectionMatrix();
}
function draw() { if (BLD.renderer) BLD.renderer.render(BLD.scene, camera()); }
function extent(b) {
  const pts = b.walls.flatMap((w) => [w.a, w.b]);
  if (!pts.length) return { cx: 0, cy: 0, size: 20, top: 3 };
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const top = Math.max(...b.levels.map((l) => l.elevation + l.height));
  return { cx: (Math.min(...xs) + Math.max(...xs)) / 2, cy: (Math.min(...ys) + Math.max(...ys)) / 2, size: Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 8), top };
}
function fit() {
  const e = extent(S.D.building), t = new THREE.Vector3(e.cx, e.top / 2, -e.cy);
  const r = Math.hypot(e.size, e.top) / 2 * 1.15;  // the whole building in view, a bungalow or a tower
  BLD.cam3d.position.copy(t).addScaledVector(new THREE.Vector3(1.1, 0.9, 1.3).normalize(), r / Math.sin(BLD.cam3d.fov * Math.PI / 360));
  BLD.controls.target.copy(t);
  const elev = lvlOf(S.D.building, BLD.level).elevation;
  BLD.camPlan.position.set(e.cx, elev + 200, -e.cy);
  BLD.camPlan.up.set(0, 0, -1);
  BLD.camPlan.lookAt(e.cx, elev, -e.cy);
  const k = e.size * 0.7;
  Object.assign(BLD.camPlan, { top: k, bottom: -k });
  resize();
  BLD.controls.update();
  draw();
}
function setPlan(on) {
  BLD.plan = on;
  $("#bld3dBtn").classList.toggle("active", !on); $("#bldPlanBtn").classList.toggle("active", on);
  BLD.controls.object = camera();
  BLD.controls.enableRotate = !on;
  BLD.controls.mouseButtons.LEFT = on ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE;
  if (on) { const e = extent(S.D.building); BLD.controls.target.set(e.cx, lvlOf(S.D.building, BLD.level).elevation, -e.cy); }
  rebuild(); fit();
}

function rebuild() {
  const b = S.D.building;
  if (!b || !BLD.scene) return;
  if (BLD.root) { BLD.scene.remove(BLD.root); BLD.root.traverse((o) => o.geometry?.dispose()); }
  const maxLevel = !$("#bldAllLevels").checked ? BLD.level : b.levels.length - 1;
  const g = buildingGroup(b, maxLevel, BLD.plan ? BLD.level : null);
  for (const o of g.children) {  // the selection in blue
    if (BLD.sel && o.userData.type === BLD.sel.type && o.userData.id === BLD.sel.id) o.material = mats().sel;
  }
  BLD.root = batchGroup(g);
  BLD.scene.add(BLD.root);
  BLD.grid.position.y = lvlOf(b, BLD.level).elevation + 0.002;
  draw();
}

// ---- picking and tools -----------------------------------------------------------------------------------
const ray = () => new THREE.Raycaster();
function ndc(e) {
  const r = BLD.renderer.domElement.getBoundingClientRect();
  return new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
}
function pickMesh(e) {  // the nearest hit, with the {type, id} of the part it hit
  const rc = ray();
  rc.setFromCamera(ndc(e), camera());
  const hit = rc.intersectObjects(BLD.root ? BLD.root.children : [], false)[0];
  return hit ? { ...hit, part: partAt(hit) } : null;
}
function floorPoint(e, snap = true) {  // the clicked point on the working level, in building metres
  const rc = ray();
  rc.setFromCamera(ndc(e), camera());
  const elev = lvlOf(S.D.building, BLD.level).elevation;
  const hit = new THREE.Vector3();
  if (!rc.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -elev), hit)) return null;
  let p = [hit.x, -hit.z];
  if (!snap) return p;
  const ends = S.D.building.walls.filter((w) => w.level === BLD.level).flatMap((w) => [w.a, w.b]);
  const near = ends.find((q) => Math.hypot(q[0] - p[0], q[1] - p[1]) < 0.3);
  if (near) return [...near];
  p = p.map((v) => Math.round(v * 10) / 10);
  const from = BLD.draft?.a;
  if (from && e.shiftKey) p = Math.abs(p[0] - from[0]) >= Math.abs(p[1] - from[1]) ? [p[0], from[1]] : [from[0], p[1]];  // Shift: ortho
  return p;
}
function setTool(t) {
  BLD.tool = t; BLD.draft = null; clearPreview();
  $$("[data-bt]").forEach((x) => x.classList.toggle("active", x.dataset.bt === t));
  bmsg({ select: "Click to select; drag the selection to move it. Del deletes.", wall: "Wall: click its start, then its end (chains on; Esc stops; Shift keeps it square).",
    door: "Door: click on a wall.", window: "Window: click on a wall.", column: "Column: click on the floor.",
    stair: "Stair: click its foot, then a point in the direction it climbs." }[t] || "");
}
function clearPreview() { while (BLD.preview?.children.length) BLD.preview.remove(BLD.preview.children[0]); draw(); }
function previewWall(a, p) {
  clearPreview();
  const lv = lvlOf(S.D.building, BLD.level);
  if (Math.hypot(p[0] - a[0], p[1] - a[1]) > 0.05) BLD.preview.add(boxAlong(a, p, 0, Math.hypot(p[0] - a[0], p[1] - a[1]), lv.elevation, lv.elevation + lv.height, 0.15, mats().ghost));
  draw();
  bmsg(`Wall: ${Math.hypot(p[0] - a[0], p[1] - a[1]).toFixed(2)} m. Click its end (Esc stops).`);
}

function bindPointer(cv) {
  let down = null;
  cv.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    down = { x: e.clientX, y: e.clientY, moved: false };
    if (BLD.tool === "select" && BLD.sel && ["wall", "column", "stair", "opening"].includes(BLD.sel.type)) {
      const hit = pickMesh(e);
      if (hit && hit.part.type === BLD.sel.type && hit.part.id === BLD.sel.id) {
        down.drag = { start: floorPoint(e, false), snapshot: JSON.stringify(selObj()) };
        BLD.controls.enabled = false;
      }
    }
  }, true);  // capture: before the orbit controls start turning the view
  cv.addEventListener("pointermove", (e) => {
    const b = S.D?.building;
    if (!b) return;
    const p = floorPoint(e, BLD.tool !== "select");
    if (p) $("#bldCoord").textContent = `X ${p[0].toFixed(2)} m  Y ${p[1].toFixed(2)} m  ·  ${lvlOf(b, BLD.level).name}`;
    if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4) down.moved = true;
    if (down?.drag && p) { dragSelection(down.drag, p); return; }
    if (BLD.tool === "wall" && BLD.draft?.a && p) previewWall(BLD.draft.a, p);
  });
  cv.addEventListener("pointerup", (e) => {
    BLD.controls.enabled = true;
    if (!down) return;
    const d = down;
    down = null;
    if (d.drag) { if (d.moved) changed(); return; }
    if (!d.moved) toolClick(e);
  });
}
function selObj() {
  const b = S.D.building, s = BLD.sel;
  if (!b || !s) return null;
  return ({ wall: b.walls, opening: b.openings, column: b.columns, stair: b.stairs, slab: b.slabs, roof: b.roofs }[s.type] || []).find((x) => x.id === s.id);
}
function dragSelection(drag, p) {  // move by the dragged distance, on the 0.1 m grid
  const o = selObj(), was = JSON.parse(drag.snapshot);
  if (!o || !drag.start) return;
  const dx = Math.round((p[0] - drag.start[0]) * 10) / 10, dy = Math.round((p[1] - drag.start[1]) * 10) / 10;
  if (BLD.sel.type === "wall") { o.a = [was.a[0] + dx, was.a[1] + dy]; o.b = [was.b[0] + dx, was.b[1] + dy]; }
  else if (BLD.sel.type === "opening") {  // along its wall
    const w = S.D.building.walls.find((x) => x.id === o.wall), L = wallLen(w) || 1;
    const s = ((p[0] - w.a[0]) * (w.b[0] - w.a[0]) + (p[1] - w.a[1]) * (w.b[1] - w.a[1])) / L;
    o.offset = Math.round(Math.min(L - o.width / 2, Math.max(o.width / 2, s)) * 100) / 100;
  } else { o.x = was.x + dx; o.y = was.y + dy; }
  rebuild();
}
function toolClick(e) {
  const b = S.D.building;
  if (!b) return;
  const lv = BLD.level;
  if (BLD.tool === "select") {
    const hit = pickMesh(e);
    BLD.sel = hit ? hit.part : null;
    rebuild(); renderBldProps();
    return;
  }
  if (BLD.tool === "door" || BLD.tool === "window") {
    const hit = pickMesh(e);
    const w = hit && hit.part.type === "wall" && b.walls.find((x) => x.id === hit.part.id);
    if (!w) return toast("Click on a wall");
    const L = wallLen(w), door = BLD.tool === "door", width = door ? 0.9 : 1.2;
    const p = [hit.point.x, -hit.point.z];
    const s = ((p[0] - w.a[0]) * (w.b[0] - w.a[0]) + (p[1] - w.a[1]) * (w.b[1] - w.a[1])) / (L || 1);
    const o = { id: bnextId("openings", "O"), wall: w.id, kind: door ? "door" : "window", offset: Math.round(Math.min(L - width / 2 - 0.05, Math.max(width / 2 + 0.05, s)) * 100) / 100,
      width, height: door ? 2.1 : 1.2, sill: door ? 0 : 0.9, style: door ? "single" : "casement" };
    b.openings.push(o);
    BLD.sel = { type: "opening", id: o.id };
    return changed();
  }
  const p = floorPoint(e);
  if (!p) return;
  if (BLD.tool === "column") {
    const c = { id: bnextId("columns", "C"), level: lv, x: p[0], y: p[1], size: 0.3 };
    b.columns.push(c); BLD.sel = { type: "column", id: c.id };
    return changed();
  }
  if (BLD.tool === "stair") {
    if (!BLD.draft) { BLD.draft = { a: p }; return bmsg("Stair: now click a point in the direction it climbs."); }
    const a = BLD.draft.a, ang = Math.atan2(p[1] - a[1], p[0] - a[0]) * 180 / Math.PI;
    const st = { id: bnextId("stairs", "ST"), level: lv, x: a[0], y: a[1], angle: Math.round(ang), width: 1.0, tread: 0.28, max_riser: 0.175 };
    b.stairs.push(st); BLD.draft = null; BLD.sel = { type: "stair", id: st.id };
    return changed();
  }
  if (BLD.tool === "wall") {
    if (!BLD.draft?.a) { BLD.draft = { a: p }; return bmsg("Wall: click its end."); }
    const a = BLD.draft.a;
    if (Math.hypot(p[0] - a[0], p[1] - a[1]) < 0.1) return;
    const w = { id: bnextId("walls", "W"), level: lv, a, b: p, thickness: 0.15, height: null, kind: "internal", material: "block" };
    b.walls.push(w);
    BLD.draft = { a: p };  // chain on from the end, like a polyline
    BLD.sel = { type: "wall", id: w.id };
    clearPreview();
    return changed();
  }
}
function deleteSel() {
  const b = S.D.building, s = BLD.sel;
  if (!b || !s) return toast("Select something to delete");
  const coll = { wall: "walls", opening: "openings", column: "columns", stair: "stairs", slab: "slabs", roof: "roofs" }[s.type];
  b[coll] = b[coll].filter((x) => x.id !== s.id);
  if (s.type === "wall") b.openings = b.openings.filter((o) => o.wall !== s.id);  // its doors and windows go with it
  BLD.sel = null;
  changed();
}

// ---- properties ------------------------------------------------------------------------------------------
const PROPS = {
  wall: [["kind", ["external", "internal"]], ["material", ["block", "brick", "stone", "concrete"]], ["thickness", "number"], ["height", "number"],
    ["a", "pt"], ["b", "pt"]],
  opening: [["kind", ["door", "window"]], ["style", ["single", "double", "sliding", "arched", "fixed", "casement", "hung"]], ["width", "number"],
    ["height", "number"], ["sill", "number"], ["offset", "number"]],
  column: [["size", "number"], ["x", "number"], ["y", "number"]],
  stair: [["width", "number"], ["angle", "number"], ["tread", "number"], ["max_riser", "number"], ["x", "number"], ["y", "number"]],
  slab: [["thickness", "number"]],
  roof: [["kind", ["gable", "hip", "shed", "flat"]], ["pitch", "number"], ["overhang", "number"], ["ridge", ["x", "y"]],
    ["covering", ["iron sheets", "tiles", "concrete"]]],
};
function renderBldProps() {
  const box = $("#bldProps"), o = selObj(), b = S.D.building;
  if (!o) {
    const lv = b ? lvlOf(b, BLD.level) : null;
    box.innerHTML = lv ? `<h4>${esc(lv.name)}</h4><div class="form"><label>Name<input data-lv="name" value="${esc(lv.name)}"></label>
      <label>Floor level (m)<input data-lv="elevation" type="number" step="0.05" value="${lv.elevation}"></label>
      <label>Height (m)<input data-lv="height" type="number" step="0.05" value="${lv.height}"></label></div>` : "";
    $$("[data-lv]", box).forEach((inp) => inp.addEventListener("change", () => { lv[inp.dataset.lv] = inp.dataset.lv === "name" ? inp.value : +inp.value; changed(); }));
    return;
  }
  const info = BLD.sel.type === "wall" ? `Length ${wallLen(o).toFixed(2)} m` : BLD.sel.type === "stair" ? (() => {
    const lv = lvlOf(b, o.level), n = Math.ceil(lv.height / o.max_riser - 1e-9);
    return `${n} risers of ${(lv.height / n * 1000).toFixed(0)} mm, going ${((n - 1) * o.tread).toFixed(2)} m`; })() : "";
  box.innerHTML = `<h4>${esc(BLD.sel.type[0].toUpperCase() + BLD.sel.type.slice(1))} ${esc(o.id)}</h4>${info ? `<p class="muted">${info}</p>` : ""}<div class="form">` +
    PROPS[BLD.sel.type].map(([f, k]) => {
      const v = o[f];
      if (Array.isArray(k)) return `<label>${f}<select data-bp="${f}">${k.map((x) => `<option ${x === v ? "selected" : ""}>${x}</option>`).join("")}</select></label>`;
      if (k === "pt") return `<label>${f === "a" ? "Start" : "End"} x, y (m)<input data-bp="${f}" data-pt value="${v.map((c) => c.toFixed(2)).join(", ")}"></label>`;
      return `<label>${f.replace("_", " ")}${f === "height" && BLD.sel.type === "wall" ? " (empty: the level's)" : ""}<input data-bp="${f}" type="number" step="any" value="${v ?? ""}"></label>`;
    }).join("") + `</div>`;
  $$("[data-bp]", box).forEach((inp) => inp.addEventListener("change", () => {
    const f = inp.dataset.bp;
    if (inp.dataset.pt !== undefined) {
      const xy = inp.value.split(/[,\s]+/).map(Number);
      if (xy.length !== 2 || xy.some(isNaN)) return toast("Type x, y in metres");
      o[f] = xy;
    } else if (inp.tagName === "SELECT") o[f] = inp.value;
    else o[f] = inp.value === "" ? null : +inp.value;
    if (BLD.sel.type === "opening" && f === "kind") { o.style = o.kind === "door" ? "single" : "casement"; o.sill = o.kind === "door" ? 0 : 0.9; }
    changed();
  }));
}

// ---- auto design, levels, roof ---------------------------------------------------------------------------
const AUTO = [["width", "Width east-west (m)", 12], ["depth", "Depth north-south (m)", 9], ["floors", "Floors", 1], ["floor_height", "Floor to floor (m)", 3],
  ["rooms_x", "Rooms across", 2], ["rooms_y", "Rooms deep", 2], ["external_wall", "External wall (m)", 0.2], ["internal_wall", "Internal wall (m)", 0.15],
  ["material", "Walls", ["block", "brick", "stone", "concrete"]], ["window_spacing", "A window every (m)", 3], ["window_width", "Window width (m)", 1.2],
  ["window_height", "Window height (m)", 1.2], ["window_style", "Windows", ["casement", "sliding", "fixed", "hung"]], ["door_style", "Main door", ["single", "double", "sliding", "arched"]],
  ["roof", "Roof", ["gable", "hip", "shed", "flat"]], ["pitch", "Roof pitch (deg)", 25], ["overhang", "Overhang (m)", 0.6],
  ["covering", "Covering", ["iron sheets", "tiles", "concrete"]], ["parapet", "Parapet on a flat roof (m)", 1.0],
  ["columns", "Concrete frame (columns)", false]];
const BLOCK = [["x", "Block corner x, east (m)", 0], ["y", "Block corner y, north (m)", 0], ["start_floor", "Starts at floor (0 = ground)", 0]];
function makeAutoForm() {
  $("#bldAuto").innerHTML = AUTO.map(([k, t, d]) => Array.isArray(d)
    ? `<label>${t}<select data-ap="${k}">${d.map((x) => `<option>${x}</option>`).join("")}</select></label>`
    : typeof d === "boolean" ? `<label class="inline"><input type="checkbox" data-ap="${k}"> ${t}</label>`
    : `<label>${t}<input data-ap="${k}" type="number" step="any" value="${d}"></label>`).join("") +
    `<label class="inline"><input type="checkbox" id="bldAddBlock"> Add as a new block (wing, or a tower on a podium) instead of replacing</label>
     <div id="bldBlock" class="form" hidden>${BLOCK.map(([k, t, d]) => `<label>${t}<input data-ap="${k}" type="number" step="any" value="${d}"></label>`).join("")}</div>`;
  $("#bldAddBlock").addEventListener("change", (e) => { $("#bldBlock").hidden = !e.target.checked; });
  BLD.formMade = true;
}
$("#bldGenerate").onclick = async () => {
  const add = $("#bldAddBlock")?.checked;
  if (add && !S.D.building?.walls?.length) return toast("Design the first block first, then add wings or towers to it");
  if (!add && S.D.building?.walls?.length && !confirm("Replace the current building with a new design?")) return;
  const body = { mode: add ? "add" : "replace" };
  $$("[data-ap]").forEach((i) => {
    if (!add && i.closest("#bldBlock")) return;
    body[i.dataset.ap] = i.type === "checkbox" ? i.checked : i.tagName === "SELECT" ? i.value : +i.value;
  });
  try {
    let st = await serverOp(`/api/projects/${S.pid}/building/generate`, jsonBody(body));
    // a design started from a 3D model also gets the parts found on top of it (a tower, stair towers, plant rooms)
    const parts = !add && $("#bldModelParts")?.checked ? BLD.modelBlocks || [] : [];
    for (const [k, blk] of parts.entries()) {
      bmsg(`Adding part ${k + 1} of ${parts.length} from the model…`);
      const { what, ...p } = blk;
      st = await serverOp(`/api/projects/${S.pid}/building/generate`, jsonBody({ ...body, ...p, mode: "add" }));
    }
    if (parts.length) bmsg("");
    BLD.sel = null; BLD.level = 0; BLD.fitted = false;
    toast(`${add ? "Block added" : "Designed"}${parts.length ? ` with ${parts.length} part(s) from the model` : ""}: ${st.result.levels} floor(s), ${st.result.walls} walls, ${st.result.openings} doors and windows`);
  } catch (e) { toast(e.message, 7000); }
};
// measure a 3D model on the server and fill the brief; the units and up axis it guessed can be changed and re-measured
async function measureModel(f, unit, up) {
  const fd = new FormData();
  fd.append("file", f);
  if (unit) fd.append("unit", unit);
  if (up) fd.append("up", up);
  try {
    bmsg(`Measuring ${f.name}…`);
    const r = await api(`/api/projects/${S.pid}/building/measure`, { method: "POST", body: fd });
    for (const [k, v] of Object.entries(r.brief)) {
      const i = $(`[data-ap="${k}"]`);
      if (!i || i.closest("#bldBlock")) continue;
      if (i.type === "checkbox") i.checked = !!v; else i.value = v;
    }
    const opt = (vals, cur) => vals.map((v) => `<option${v === cur ? " selected" : ""}>${esc(v)}</option>`).join("");
    $("#bldModelInfo").innerHTML = `<b>${esc(f.name)}</b>: ${esc(r.summary)}` +
      (r.notes.length ? `<br><span class="muted">${r.notes.map(esc).join("<br>")}</span>` : "") +
      `<div class="row">Wrong size? <label>Units <select id="bldModelUnit">${opt(r.units, r.unit)}</select></label>
       <label>Up axis <select id="bldModelUp">${opt(["z", "y"], r.up)}</select></label></div>` +
      (r.blocks.length ? `<label class="inline"><input type="checkbox" id="bldModelParts" checked> Also add the
        ${r.blocks.length} part(s) found on top (${esc([...new Set(r.blocks.map((b) => b.what))].join(", "))})</label>` : "");
    BLD.modelBlocks = r.blocks;
    const again = () => measureModel(f, $("#bldModelUnit").value, $("#bldModelUp").value);
    $("#bldModelUnit").onchange = again;
    $("#bldModelUp").onchange = again;
    bmsg("Brief filled from the model: check it, then press Design the building");
    if (S.D.building && r.turn_deg != null) $("#bldRot").value = r.turn_deg;
  } catch (err) { toast(err.message, 8000); bmsg(""); }
}
$("#bldModelFile").addEventListener("change", (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  if (f.size > 60 * 1024 * 1024) return toast("3D models must be smaller than 60 MB");
  measureModel(f);
});
$("#bldAddLevel").onclick = () => {
  const b = S.D.building;
  if (!b) return;
  const top = b.levels[b.levels.length - 1], k = b.levels.length;
  b.levels.push({ name: `Floor ${k}`, elevation: Math.round((top.elevation + top.height) * 1000) / 1000, height: top.height, slab: top.slab });
  for (const w of b.walls.filter((x) => x.level === k - 1 && x.kind === "external")) {
    const nw = { ...JSON.parse(JSON.stringify(w)), id: bnextId("walls", "W"), level: k };
    b.walls.push(nw);
    for (const o of b.openings.filter((x) => x.wall === w.id && x.kind === "window")) b.openings.push({ ...o, id: bnextId("openings", "O"), wall: nw.id });
  }
  const s0 = b.slabs.find((s) => s.level === k - 1);
  if (s0) b.slabs.push({ ...JSON.parse(JSON.stringify(s0)), id: bnextId("slabs", "S"), level: k });
  for (const r of b.roofs) if (r.level === k - 1) r.level = k;  // the roof goes up
  for (const s of b.slabs) if (s.level === k && s !== b.slabs[b.slabs.length - 1] && s.id.startsWith("SR")) s.level = k + 1;
  BLD.level = k;
  changed();
  toast(`Added ${b.levels[k].name} with the outside walls and windows of the floor below`);
};
$("#bldRoofBtn").onclick = () => {
  const b = S.D.building;
  if (!b?.walls.length) return toast("Design or draw the walls first");
  const top = b.levels.length - 1, ext = b.walls.filter((w) => w.level === top);
  const half = (w) => w.thickness / 2;
  const x0 = Math.min(...ext.map((w) => Math.min(w.a[0], w.b[0]) - half(w))), x1 = Math.max(...ext.map((w) => Math.max(w.a[0], w.b[0]) + half(w)));
  const y0 = Math.min(...ext.map((w) => Math.min(w.a[1], w.b[1]) - half(w))), y1 = Math.max(...ext.map((w) => Math.max(w.a[1], w.b[1]) + half(w)));
  let r = b.roofs.find((x) => x.level === top);
  if (!r) { r = { id: bnextId("roofs", "R"), level: top, x0, y0, x1, y1, kind: "gable", pitch: 25, overhang: 0.6, ridge: x1 - x0 >= y1 - y0 ? "x" : "y", covering: "iron sheets" }; b.roofs.push(r); }
  else Object.assign(r, { x0, y0, x1, y1 });
  BLD.sel = { type: "roof", id: r.id };
  changed();
  bmsg("Roof: set its type, pitch and covering in the properties.");
};

// ---- exports ---------------------------------------------------------------------------------------------
function exportGroup() {  // the whole building, every level and the roof
  const g = buildingGroup(S.D.building, S.D.building.levels.length - 1);
  g.updateMatrixWorld(true);
  return g;
}
function bldFile(ext) { return `${(S.D.info.name || "building").replace(/[^\w-]+/g, "_")}_3D.${ext}`; }
function dxf3d(g) {  // 3DFACE entities, metres, z up (as the building's own coordinates)
  const out = ["0", "SECTION", "2", "ENTITIES"], v = new THREE.Vector3();
  g.traverse((o) => {
    if (!o.isMesh) return;
    const geo = o.geometry.index ? o.geometry.toNonIndexed() : o.geometry, p = geo.attributes.position, layer = (o.userData.type || "MODEL").toUpperCase();
    for (let i = 0; i + 2 < p.count; i += 3) {
      const c = [0, 1, 2].map((k) => { v.fromBufferAttribute(p, i + k).applyMatrix4(o.matrixWorld); return [v.x, -v.z, v.y]; });
      out.push("0", "3DFACE", "8", layer);
      [c[0], c[1], c[2], c[2]].forEach((q, k) => out.push(`1${k}`, q[0].toFixed(4), `2${k}`, q[1].toFixed(4), `3${k}`, q[2].toFixed(4)));
    }
  });
  out.push("0", "ENDSEC", "0", "EOF");
  return out.join("\n");
}
$$("[data-bx]").forEach((btn) => btn.addEventListener("click", async () => {
  if (!S.D.building?.walls.length) return toast("Design the building first");
  await loadThree();
  const g = exportGroup(), kind = btn.dataset.bx;
  try {
    if (kind === "glb") new THREE.GLTFExporter().parse(g, (res) => saveBlob(new Blob([res], { type: "model/gltf-binary" }), bldFile("glb")), (e) => toast(String(e)), { binary: true });
    if (kind === "obj") saveBlob(new Blob([new THREE.OBJExporter().parse(g)], { type: "text/plain" }), bldFile("obj"));
    if (kind === "stl") {  // a 1:100 scale model in millimetres, z up, for 3D printing
      g.rotation.x = Math.PI / 2; g.scale.setScalar(10); g.updateMatrixWorld(true);
      saveBlob(new Blob([new THREE.STLExporter().parse(g, { binary: true })], { type: "model/stl" }), bldFile("stl"));
    }
    if (kind === "dxf") saveBlob(new Blob([dxf3d(g)], { type: "image/vnd.dxf" }), bldFile("dxf"));
  } catch (e) { toast(`Export failed: ${e.message}`, 6000); }
}));

// ---- tab entry, keys, level list ---------------------------------------------------------------------------
async function renderBuilding(full) {
  if (!isConstruction()) return;
  if (!BLD.formMade) makeAutoForm();
  const b = S.D.building;
  $("#bldLevel").innerHTML = (b?.levels || [{ name: "Ground floor" }]).map((l, k) => `<option value="${k}" ${k === BLD.level ? "selected" : ""}>${esc(l.name)}</option>`).join("");
  if (!b?.walls?.length) { $("#bldProps").innerHTML = ""; bmsg("No building yet: set the brief and press Design the building, or draw the walls."); }
  else if ($("#bldMsg").textContent.startsWith("No building")) bmsg("");
  try { await loadThree(); } catch (e) { return bmsg(`${e.message}: check the internet connection, then reopen the tab.`); }
  if (!BLD.renderer) setupScene();
  if (!S.D.building) { S.D.building = { origin: null, rotation: 0, levels: [{ name: "Ground floor", elevation: 0, height: 3, slab: 0.15 }], walls: [], openings: [], slabs: [], roofs: [], stairs: [], columns: [], spec: {} }; }
  BLD.level = Math.min(BLD.level, S.D.building.levels.length - 1);
  rebuild();
  if (!BLD.fitted || full) { fit(); BLD.fitted = true; }
  renderBldProps();
}
$("#bldLevel").addEventListener("change", (e) => { BLD.level = +e.target.value; BLD.sel = null; rebuild(); renderBldProps(); if (BLD.plan) fit(); });
$("#bldAllLevels").addEventListener("change", rebuild);
$$("[data-bt]").forEach((x) => x.addEventListener("click", () => setTool(x.dataset.bt)));
$("#bldDelete").onclick = deleteSel;
$("#bld3dBtn").onclick = () => setPlan(false);
$("#bldPlanBtn").onclick = () => setPlan(true);
$("#bldFit").onclick = fit;
document.addEventListener("keydown", (e) => {
  if (activeTab() !== "building" || ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
  if (e.key === "Escape") { if (BLD.draft) { BLD.draft = null; clearPreview(); bmsg(""); } else setTool("select"); }
  if (e.key === "Delete") deleteSel();
});

// ---- site plan (map tab) and overview -----------------------------------------------------------------------
function bldToLatLon(b, x, y) {  // ftth/building.py to_latlon
  const r = (b.rotation || 0) * Math.PI / 180, X = x * Math.cos(r) - y * Math.sin(r), Y = x * Math.sin(r) + y * Math.cos(r);
  const [lat0, lon0] = b.origin;
  return [lat0 + Y / 111195.08, lon0 + X / (111195.08 * Math.cos(lat0 * Math.PI / 180))];
}
function buildingOnMap(layer) {  // the footprint on the site plan; returns its points for fitting the map
  const b = S.D?.building;
  if (!isConstruction()) return [];
  $("#bldRot").value = b?.rotation || 0;
  if (!b?.origin || !b.walls.length) return [];
  const pts = b.walls.filter((w) => w.level === 0).flatMap((w) => [w.a, w.b]);
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const box = [[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.min(...ys)], [Math.max(...xs), Math.max(...ys)], [Math.min(...xs), Math.max(...ys)]];
  const ll = box.map(([x, y]) => bldToLatLon(b, x, y));
  L.polygon(ll, { color: "#e01b24", weight: 2, fillColor: "#e01b24", fillOpacity: 0.25, interactive: false }).addTo(layer);
  for (const w of b.walls.filter((x) => x.level === 0)) L.polyline([bldToLatLon(b, ...w.a), bldToLatLon(b, ...w.b)], { color: "#7a1015", weight: 2, interactive: false }).addTo(layer);
  return ll;
}
function placeBuilding(lat, lon) {
  if (!S.D.building) return toast("Design the building first (Building 3D)");
  S.D.building.origin = [lat, lon];
  changed();
  toast("Building placed: its south-west corner (x = y = 0) is here. Turn it with the angle box.");
}
$("#bldRot").addEventListener("change", (e) => { if (S.D.building) { S.D.building.rotation = +e.target.value || 0; changed(); } });
function renderOvBuilding() {
  const box = $("#ovBuilding");
  if (!box || !isConstruction()) return;
  const b = S.D.building;
  if (!b?.walls.length) { box.innerHTML = `<p class="muted" style="padding:10px">No building yet: open Building 3D and press Design the building.</p>`; return; }
  const area = (poly) => Math.abs(poly.reduce((a, p, k) => { const q = poly[(k + 1) % poly.length]; return a + p[0] * q[1] - q[0] * p[1]; }, 0)) / 2;
  const floor = b.slabs.filter((s) => s.level < b.levels.length).reduce((a, s) => a + area(s.outline), 0);
  box.innerHTML = `<table>${[["Floors", b.levels.length], ["Gross floor area", `${fmt(floor, 1)} m²`], ["Walls", b.walls.length],
    ["Doors", b.openings.filter((o) => o.kind === "door").length], ["Windows", b.openings.filter((o) => o.kind === "window").length],
    ["Roof", b.roofs.map((r) => `${r.kind} ${r.pitch}°`).join(", ") || "none"], ["On the site plan", b.origin ? "placed" : "not yet"]]
    .map(([k, v]) => `<tr><td>${k}</td><td class="num">${v}</td></tr>`).join("")}</table>`;
}
