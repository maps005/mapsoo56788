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
// textures drawn on a canvas (nothing to download); `tile` is the metres one texture covers: the merged meshes
// get world-space UVs (batchGroup), so bricks, sheets and grass keep their real size on every wall and roof
function canvasTex(px, draw) {
  const c = document.createElement("canvas");
  c.width = c.height = px;
  const x = c.getContext("2d");
  draw(x, px);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.encoding = THREE.sRGBEncoding;
  t.anisotropy = 8;
  return t;
}
let SEED = 7;
const rnd = () => { SEED = (SEED * 16807) % 2147483647; return (SEED - 1) / 2147483646; };
function noise(x, n, base, spread, size = 2) {  // speckle: n dots of shades round base [r, g, b]
  for (let i = 0; i < n; i++) {
    const k = (rnd() - 0.5) * spread;
    x.fillStyle = `rgb(${base[0] + k},${base[1] + k},${base[2] + k * 0.9})`;
    x.fillRect(rnd() * x.canvas.width, rnd() * x.canvas.height, size, size);
  }
}
const TEX = {
  render: () => canvasTex(256, (x, n) => { x.fillStyle = "#ece6db"; x.fillRect(0, 0, n, n); noise(x, 9000, [232, 226, 214], 22, 2); }),
  brick: () => canvasTex(512, (x, n) => {  // 16 courses of 215 x 65 mm bricks with 10 mm joints in 1.2 m
    x.fillStyle = "#cfc6b8"; x.fillRect(0, 0, n, n);
    const ch = n / 16, bw = n / 5.33;
    for (let r = 0; r < 16; r++) for (let c = -1; c < 7; c++) {
      const sh = 150 + rnd() * 40;
      x.fillStyle = `rgb(${sh},${sh * 0.45 + rnd() * 10},${sh * 0.33})`;
      x.fillRect(c * bw + (r % 2) * bw / 2 + 2, r * ch + 2, bw - 4, ch - 4);
    }
    noise(x, 6000, [150, 70, 50], 40, 1);
  }),
  stone: () => canvasTex(512, (x, n) => {
    x.fillStyle = "#9c968a"; x.fillRect(0, 0, n, n);
    let y = 0;
    while (y < n) { const h = 50 + rnd() * 40; let xx = -rnd() * 60;
      while (xx < n) { const w = 70 + rnd() * 90, sh = 175 + rnd() * 45; x.fillStyle = `rgb(${sh},${sh * 0.95},${sh * 0.86})`; x.fillRect(xx + 3, y + 3, w - 6, h - 6); xx += w; }
      y += h; }
    noise(x, 8000, [180, 172, 158], 40, 1);
  }),
  concrete: () => canvasTex(256, (x, n) => {
    x.fillStyle = "#c9c9c4"; x.fillRect(0, 0, n, n); noise(x, 7000, [200, 200, 195], 26, 2);
    x.strokeStyle = "rgba(90,90,90,.25)"; x.lineWidth = 2; x.strokeRect(1, 1, n - 2, n / 2 - 2); x.strokeRect(1, n / 2, n - 2, n / 2 - 2);
  }),
  sheet: () => canvasTex(128, (x, n) => {  // corrugations: 8 in 0.76 m
    for (let i = 0; i < n; i++) { const v = 0.5 + 0.5 * Math.sin(i / n * Math.PI * 16); const c = 70 + v * 45; x.fillStyle = `rgb(${c * 0.92},${c},${c * 1.08})`; x.fillRect(i, 0, 1, n); }
  }),
  tiles: () => canvasTex(256, (x, n) => {
    x.fillStyle = "#6e3426"; x.fillRect(0, 0, n, n);
    for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) {
      const sh = 130 + rnd() * 30, g = x.createLinearGradient(0, r * n / 4, 0, (r + 1) * n / 4);
      g.addColorStop(0, `rgb(${sh},${sh * 0.48},${sh * 0.36})`); g.addColorStop(1, `rgb(${sh * 0.7},${sh * 0.32},${sh * 0.24})`);
      x.fillStyle = g; x.fillRect(c * n / 4 + (r % 2) * n / 8 + 2, r * n / 4 + 1, n / 4 - 4, n / 4 - 3);
    }
  }),
  membrane: () => canvasTex(256, (x, n) => { x.fillStyle = "#6b6e70"; x.fillRect(0, 0, n, n); noise(x, 12000, [110, 112, 114], 40, 2); }),
  grass: () => canvasTex(256, (x, n) => { x.fillStyle = "#7d9a5c"; x.fillRect(0, 0, n, n); noise(x, 16000, [118, 150, 86], 50, 2); }),
  lawn: () => canvasTex(256, (x, n) => { x.fillStyle = "#6fa04a"; x.fillRect(0, 0, n, n); noise(x, 16000, [104, 160, 70], 44, 2);
    x.fillStyle = "rgba(255,255,255,.05)"; for (let i = 0; i < n; i += 32) x.fillRect(0, i, n, 16); }),
  paving: () => canvasTex(256, (x, n) => {  // 200 x 100 mm blocks, herringbone-ish rows
    x.fillStyle = "#8f8a80"; x.fillRect(0, 0, n, n);
    for (let r = 0; r < 8; r++) for (let c = 0; c < 5; c++) { const sh = 175 + rnd() * 25; x.fillStyle = `rgb(${sh},${sh * 0.96},${sh * 0.9})`;
      x.fillRect(c * n / 4 + (r % 2) * n / 8 + 1, r * n / 8 + 1, n / 4 - 2, n / 8 - 2); }
  }),
  soil: () => canvasTex(128, (x, n) => { x.fillStyle = "#5a3e28"; x.fillRect(0, 0, n, n); noise(x, 4000, [96, 66, 44], 40, 2); }),
  leaf: () => canvasTex(128, (x, n) => { x.fillStyle = "#3f6b2e"; x.fillRect(0, 0, n, n); noise(x, 5000, [70, 112, 50], 60, 3); }),
  floor: () => canvasTex(256, (x, n) => { x.fillStyle = "#d9d6cf"; x.fillRect(0, 0, n, n); x.strokeStyle = "rgba(0,0,0,.08)";
    for (let i = 0; i <= n; i += n / 4) { x.beginPath(); x.moveTo(i, 0); x.lineTo(i, n); x.moveTo(0, i); x.lineTo(n, i); x.stroke(); } }),
};
function mats() {
  if (MAT.wall) return MAT;
  const m = (c, o = {}) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.85, metalness: 0, envMapIntensity: 0.45, ...o });
  const tm = (tex, tile, o = {}) => { const mt = m(0xffffff, { map: TEX[tex](), ...o }); mt.userData.tile = tile; return mt; };
  Object.assign(MAT, {
    wall: tm("render", 2), wallBrick: tm("brick", 1.2), wallStone: tm("stone", 2), wallConcrete: tm("concrete", 2.4),
    wallInt: m(0xf4f1ea), slab: tm("floor", 2.4, { roughness: 0.7 }), roofFlat: tm("membrane", 4, { roughness: 0.95 }),
    glass: m(0x6b93b3, { metalness: 0.7, roughness: 0.04, envMapIntensity: 1.6, transparent: true, opacity: 0.88 }),
    frame: m(0x3a3f44, { metalness: 0.4, roughness: 0.4 }), sill: m(0xd8d4cc, { roughness: 0.6 }), coping: m(0xbdb8ae),
    door: m(0x7a4f2c, { roughness: 0.6 }), metal: m(0xc9cdd1, { metalness: 0.9, roughness: 0.25 }),
    roofSheet: tm("sheet", 0.76, { side: THREE.DoubleSide, metalness: 0.35, roughness: 0.45 }), roofTile: tm("tiles", 0.6, { side: THREE.DoubleSide }),
    stair: tm("concrete", 2.4), column: m(0x8d949c), cut: m(0x3b4148), sel: m(0x00b7ff, { emissive: 0x003a55 }), ghost: m(0x00b7ff, { transparent: true, opacity: 0.35 }),
    soil: tm("soil", 1), lawn: tm("lawn", 3), paving: tm("paving", 0.8), hedge: tm("leaf", 1.2), ground: tm("grass", 6, { roughness: 1 }),
    trunk: m(0x5b4330, { roughness: 1 }), leaves: [tm("leaf", 1.5), tm("leaf", 1.5, { color: 0xb8d68a }), tm("leaf", 1.5, { color: 0x8fb070 })],
    flowers: [m(0xe0457b), m(0xf2c230), m(0xd92e2e), m(0xf4f0f6), m(0x9b59d0)],
  });
  return MAT;
}
const wallMat = (w) => { const M = mats(); return w.kind !== "external" ? M.wallInt : { brick: M.wallBrick, stone: M.wallStone, concrete: M.wallConcrete }[w.material] || M.wall; };
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
  const mat = cut ? M.cut : wallMat(w);
  const ops = (opsByWall.get(w.id) || []).sort((p, q) => p.offset - q.offset);
  let s = 0;
  for (const o of ops) {
    const s0 = Math.max(0, o.offset - o.width / 2), s1 = Math.min(L, o.offset + o.width / 2);
    if (s0 > s) group.add(tag(boxAlong(w.a, w.b, s, s0, base, base + H, w.thickness, mat), "wall", w.id));
    if (o.sill > 0) group.add(tag(boxAlong(w.a, w.b, s0, s1, base, base + o.sill, w.thickness, mat), "wall", w.id));
    if (o.sill + o.height < H) group.add(tag(boxAlong(w.a, w.b, s0, s1, base + o.sill + o.height, base + H, w.thickness, mat), "wall", w.id));
    openingMeshes(w, o, s0, s1, base, group, cut);
    s = Math.max(s, s1);
  }
  if (L > s) group.add(tag(boxAlong(w.a, w.b, s, L, base, base + H, w.thickness, mat), "wall", w.id));
}

function openingMeshes(w, o, s0, s1, base, group, cut) {
  const M = mats(), z0 = base + o.sill, z1 = z0 + o.height, t = w.thickness;
  const add = (a0, a1, h0, h1, d, mat) => group.add(tag(boxAlong(w.a, w.b, a0, a1, h0, h1, d, mat), "opening", o.id));
  if (cut) { add(s0, s1, z0, z1, o.kind === "window" ? 0.03 : 0.05, o.kind === "window" ? M.glass : M.door); return; }
  const f = 0.06, fd = Math.min(0.1, t * 0.7);
  add(s0, s1, z1 - f, z1, fd, M.frame);  // head and jambs
  add(s0, s0 + f, z0, z1, fd, M.frame);
  add(s1 - f, s1, z0, z1, fd, M.frame);
  if (o.kind === "window") {
    add(s0, s1, z0, z0 + f, fd, M.frame);
    add(s0 - 0.04, s1 + 0.04, z0 - 0.05, z0, t + 0.1, M.sill);  // sill, standing out from both faces
    add(s0 + f, s1 - f, z0 + f, z1 - f, 0.02, M.glass);
    const panes = Math.max(1, Math.round((s1 - s0) / 0.8));  // glazing bars, and a transom on tall windows
    for (let i = 1; i < panes; i++) { const c = s0 + (s1 - s0) * i / panes; add(c - 0.025, c + 0.025, z0 + f, z1 - f, fd * 0.8, M.frame); }
    if (o.height > 1.4) { const zt = z1 - Math.min(0.5, o.height * 0.3); add(s0 + f, s1 - f, zt - 0.025, zt + 0.025, fd * 0.8, M.frame); }
  } else {
    const glazed = o.style === "sliding";
    const leaves = o.style === "double" || o.style === "sliding" ? 2 : 1, lw = (s1 - s0 - 2 * f) / leaves;
    for (let i = 0; i < leaves; i++) {
      const a0 = s0 + f + i * lw + (leaves > 1 ? 0.005 : 0), a1 = a0 + lw - (leaves > 1 ? 0.01 : 0);
      add(a0, a1, z0, z1 - f, 0.05, glazed ? M.glass : M.door);
      if (!glazed) {  // two raised panels and a handle
        add(a0 + 0.1, a1 - 0.1, z0 + 0.15, z0 + (z1 - z0) * 0.45, 0.07, M.door);
        add(a0 + 0.1, a1 - 0.1, z0 + (z1 - z0) * 0.52, z1 - f - 0.15, 0.07, M.door);
      }
      const hx = leaves > 1 ? (i === 0 ? a1 - 0.08 : a0 + 0.08) : a1 - 0.08;
      add(hx - 0.02, hx + 0.02, z0 + 1.0, z0 + 1.08, 0.12, M.metal);
    }
  }
}

function slabMesh(b, sl) {
  const shape = new THREE.Shape(sl.outline.map(([x, y]) => new THREE.Vector2(x, y)));
  const g = new THREE.ExtrudeGeometry(shape, { depth: sl.thickness, bevelEnabled: false });
  g.rotateX(-Math.PI / 2);  // shape x, y -> three x, -z; extrusion -> up
  const top = sl.level < b.levels.length ? lvlOf(b, sl.level).elevation : lvlOf(b, b.levels.length - 1).elevation + lvlOf(b, b.levels.length - 1).height + sl.thickness;
  const mesh = new THREE.Mesh(g, sl.level >= b.levels.length ? mats().roofFlat : mats().slab);
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
      grp.add(tag(boxAlong(a, e, -0.05, L + 0.05, z0 + r.parapet, z0 + r.parapet + 0.06, t + 0.1, mats().coping), "roof", r.id));
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

// landscaping in the compound: beds of soil with plants and flowers in them, lawns and paving, leafy hedges, and
// trees with a trunk and a crown of a few overlapping spheres (each tree a little different)
let TREE_G = null;
const treeGeos = () => TREE_G || (TREE_G = { trunk: new THREE.CylinderGeometry(0.1, 0.17, 1, 7), ball: new THREE.IcosahedronGeometry(1, 1), dot: new THREE.IcosahedronGeometry(1, 0) });
function landscapeMeshes(b, g) {
  const M = mats(), G = treeGeos();
  const box = (x0, y0, x1, y1, z0, z1, mat) => {
    const m = new THREE.Mesh(unitBox(), mat);
    m.scale.set(Math.max(x1 - x0, 0.05), z1 - z0, Math.max(y1 - y0, 0.05));
    m.position.set((x0 + x1) / 2, (z0 + z1) / 2, -(y0 + y1) / 2);
    return m;
  };
  const ball = (geo, mat, x, y, z, sx, sy = sx, sz = sx) => { const m = new THREE.Mesh(geo, mat); m.scale.set(sx, sy, sz); m.position.set(x, z, -y); return m; };
  for (const x of b.landscape || []) {
    const P = x.points, xs = P.map((q) => q[0]), ys = P.map((q) => q[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    SEED = 1 + [...x.id].reduce((a, ch) => a * 31 + ch.charCodeAt(0), 7) % 100000;
    const add = (m) => g.add(tag(m, "landscape", x.id));
    if (x.kind === "flower_bed" || x.kind === "shrub_bed") {
      add(box(x0, y0, x1, y1, 0, 0.18, M.soil));
      add(box(x0 - 0.06, y0 - 0.06, x1 + 0.06, y0, 0, 0.22, M.coping));  // edging
      add(box(x0 - 0.06, y1, x1 + 0.06, y1 + 0.06, 0, 0.22, M.coping));
      add(box(x0 - 0.06, y0, x0, y1, 0, 0.22, M.coping));
      add(box(x1, y0, x1 + 0.06, y1, 0, 0.22, M.coping));
      const A = (x1 - x0) * (y1 - y0);
      if (x.kind === "shrub_bed") {
        for (let i = 0, n = Math.min(120, Math.ceil(A / 1.2)); i < n; i++) {
          const r = 0.35 + rnd() * 0.25;
          add(ball(G.ball, M.leaves[i % 3], x0 + r + rnd() * Math.max(0, x1 - x0 - 2 * r), y0 + r + rnd() * Math.max(0, y1 - y0 - 2 * r), 0.18 + r * 0.8, r, r * 0.85));
        }
      } else {
        for (let i = 0, n = Math.min(240, Math.ceil(A * 1.4)); i < n; i++) {  // low leaves, then the flowers on them
          const px = x0 + 0.15 + rnd() * Math.max(0, x1 - x0 - 0.3), py = y0 + 0.15 + rnd() * Math.max(0, y1 - y0 - 0.3);
          add(ball(G.ball, M.leaves[i % 3], px, py, 0.25, 0.22, 0.16));
          add(ball(G.dot, M.flowers[Math.floor(rnd() * M.flowers.length)], px + (rnd() - 0.5) * 0.2, py + (rnd() - 0.5) * 0.2, 0.42, 0.07));
          if (i % 2) add(ball(G.dot, M.flowers[Math.floor(rnd() * M.flowers.length)], px + (rnd() - 0.5) * 0.3, py + (rnd() - 0.5) * 0.3, 0.38, 0.06));
        }
      }
    } else if (x.kind === "lawn") add(box(x0, y0, x1, y1, 0, 0.03, M.lawn));
    else if (x.kind === "paving") add(box(x0, y0, x1, y1, 0, 0.06, M.paving));
    else if (x.kind === "hedge") for (let i = 1; i < P.length; i++) {
      const L = Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]);
      add(boxAlong(P[i - 1], P[i], 0, L, 0, 1.0, 0.6, M.hedge));
      for (let s = 0.3; s < L; s += 0.5) {  // a rounded, uneven top
        const t = s / L, cx = P[i - 1][0] + (P[i][0] - P[i - 1][0]) * t, cy = P[i - 1][1] + (P[i][1] - P[i - 1][1]) * t;
        add(ball(G.ball, M.leaves[0], cx, cy, 1.0, 0.36 + rnd() * 0.08, 0.28, 0.36));
      }
    } else if (x.kind === "tree") {
      const [tx, ty] = P[0], hgt = 4.5 + rnd() * 2.5, crown = 1.6 + rnd() * 0.8;
      add(ball(G.trunk, M.trunk, tx, ty, hgt * 0.32, 1, hgt * 0.64, 1));
      const leaf = M.leaves[Math.floor(rnd() * 3)];
      add(ball(G.ball, leaf, tx, ty, hgt * 0.62 + crown * 0.4, crown, crown * 0.85));
      for (let k = 0; k < 4; k++) {
        const a = rnd() * Math.PI * 2, d = crown * (0.45 + rnd() * 0.25), r = crown * (0.55 + rnd() * 0.2);
        add(ball(G.ball, leaf, tx + Math.cos(a) * d, ty + Math.sin(a) * d, hgt * 0.55 + rnd() * crown * 0.7, r, r * 0.85));
      }
    }
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
    const lv = lvlOf(b, c.level), m = new THREE.Mesh(unitBox(), only === null ? M.wall : M.column);  // in the walls: rendered like them
    m.scale.set(c.size, lv.height, c.size);
    m.position.set(c.x, lv.elevation + lv.height / 2, -c.y);
    g.add(tag(m, "column", c.id));
  }
  if (only === null && maxLevel >= b.levels.length - 1) for (const r of b.roofs) { const m = roofMesh(b, r); if (m) g.add(m); }
  if (only === null || only === 0) landscapeMeshes(b, g);
  return g;
}

// One mesh per material for the view: a tower is thousands of boxes, and a draw call each made it crawl (25
// floors: 7,600 calls, 7 fps). Each merged mesh keeps its parts' triangle ranges, so a click still finds the
// wall, opening, slab... it hit (partAt). Exports keep the separate, tagged meshes.
function batchGroup(g) {
  const byMat = new Map(), out = new THREE.Group();
  g.updateMatrixWorld(true);
  g.traverse((o) => { if (o.isMesh) (byMat.get(o.material) || byMat.set(o.material, []).get(o.material)).push(o); });  // parapets are a group
  const v = new THREE.Vector3(), nm = new THREE.Matrix3();
  for (const [mat, list] of byMat) {
    const geos = list.map((o) => o.geometry.index ? o.geometry.toNonIndexed() : o.geometry);
    const n = geos.reduce((a, x) => a + x.attributes.position.count, 0);
    const pos = new Float32Array(n * 3), nor = new Float32Array(n * 3), uv = new Float32Array(n * 2), parts = [];
    const tile = mat.userData?.tile || 1;
    let k = 0;
    geos.forEach((x, i) => {
      const P = x.attributes.position, N = x.attributes.normal, M = list[i].matrixWorld;
      nm.getNormalMatrix(M);
      for (let j = 0; j < P.count; j++, k++) {
        v.fromBufferAttribute(P, j).applyMatrix4(M); pos[k * 3] = v.x; pos[k * 3 + 1] = v.y; pos[k * 3 + 2] = v.z;
        v.fromBufferAttribute(N, j).applyMatrix3(nm).normalize(); nor[k * 3] = v.x; nor[k * 3 + 1] = v.y; nor[k * 3 + 2] = v.z;
        // the texture laid on the face from its main direction, at real size: walls (x or z, y), floors (x, z)
        const ax = Math.abs(v.x), ay = Math.abs(v.y), az = Math.abs(v.z), px = pos[k * 3], py = pos[k * 3 + 1], pz = pos[k * 3 + 2];
        uv[k * 2] = (ay >= ax && ay >= az ? px : ax > az ? pz : px) / tile;
        uv[k * 2 + 1] = (ay >= ax && ay >= az ? pz : py) / tile;
      }
      parts.push({ end: k / 3, type: list[i].userData.type, id: list[i].userData.id });  // end: first triangle after it
    });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("normal", new THREE.BufferAttribute(nor, 3));
    geo.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
    const m = new THREE.Mesh(geo, mat);
    m.castShadow = m.receiveShadow = mat !== mats().glass;
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
  BLD.renderer.outputEncoding = THREE.sRGBEncoding;
  BLD.renderer.toneMapping = THREE.ACESFilmicToneMapping;
  BLD.renderer.toneMappingExposure = 1.05;
  BLD.renderer.shadowMap.enabled = true;
  BLD.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  box.appendChild(BLD.renderer.domElement);
  BLD.scene = new THREE.Scene();
  // the sky: a dome shaded from blue overhead to a pale horizon; also the light the glass reflects
  const sky = new THREE.SphereGeometry(1800, 32, 16), col = [];
  const top = new THREE.Color(0x5e8fc9), hor = new THREE.Color(0xdfe9f2), low = new THREE.Color(0xb7b9a6);
  for (let i = 0; i < sky.attributes.position.count; i++) {
    const y = sky.attributes.position.getY(i) / 1800, c = y > 0 ? hor.clone().lerp(top, Math.pow(y, 0.6)) : hor.clone().lerp(low, Math.min(1, -y * 4));
    col.push(c.r, c.g, c.b);
  }
  sky.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  BLD.sky = new THREE.Mesh(sky, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide, depthWrite: false }));
  const envScene = new THREE.Scene();
  envScene.add(BLD.sky.clone());
  const pmrem = new THREE.PMREMGenerator(BLD.renderer);
  BLD.scene.environment = pmrem.fromScene(envScene, 0.02).texture;
  BLD.scene.add(BLD.sky);
  BLD.scene.background = new THREE.Color(0xdfe9f2);
  BLD.scene.add(new THREE.HemisphereLight(0xf4f8ff, 0x8a8f78, 0.35));
  BLD.sun = new THREE.DirectionalLight(0xfff4e2, 1.6);
  BLD.sun.position.set(40, 60, 25);
  BLD.sun.castShadow = true;
  BLD.sun.shadow.mapSize.set(2048, 2048);
  BLD.sun.shadow.bias = -0.0004;
  BLD.sun.shadow.normalBias = 0.03;
  BLD.scene.add(BLD.sun, BLD.sun.target);
  BLD.cam3d = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
  BLD.camPlan = new THREE.OrthographicCamera(-20, 20, 20, -20, -1000, 1000);
  BLD.controls = new THREE.OrbitControls(BLD.cam3d, BLD.renderer.domElement);
  BLD.controls.addEventListener("change", draw);
  // the ground: a soft site surface with a faint 1 m grid (for drawing) and stronger 5 m lines
  const gg = new THREE.PlaneGeometry(600, 600), guv = gg.attributes.uv;
  for (let i = 0; i < guv.count; i++) guv.setXY(i, guv.getX(i) * 100, guv.getY(i) * 100);  // grass at 6 m a tile
  BLD.ground = new THREE.Mesh(gg, mats().ground);
  BLD.ground.receiveShadow = true;
  BLD.ground.rotation.x = -Math.PI / 2;
  BLD.ground.position.y = -0.02;
  BLD.scene.add(BLD.ground);
  const fine = new THREE.GridHelper(200, 200, 0xc9d0c4, 0xc9d0c4), major = new THREE.GridHelper(200, 40, 0xaeb8ad, 0xaeb8ad);
  for (const g of [fine, major]) { g.material.transparent = true; g.material.opacity = g === fine ? 0.18 : 0.3; }
  BLD.grid = new THREE.Group();
  BLD.grid.add(fine, major);
  BLD.scene.add(BLD.grid);
  BLD.labels = new THREE.Group();
  BLD.scene.add(BLD.labels);
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
  const pts = b.walls.flatMap((w) => [w.a, w.b]).concat((b.landscape || []).flatMap((x) => x.points));
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
  // the plan: the level's walls fill the view (with room round them), whatever its shape
  const lw = S.D.building.walls.filter((w) => w.level === BLD.level).flatMap((w) => [w.a, w.b]);
  const px = lw.length ? lw.map((q) => q[0]) : [e.cx - e.size / 2, e.cx + e.size / 2];
  const py = lw.length ? lw.map((q) => q[1]) : [e.cy - e.size / 2, e.cy + e.size / 2];
  const pcx = (Math.min(...px) + Math.max(...px)) / 2, pcy = (Math.min(...py) + Math.max(...py)) / 2;
  const box = $("#bld3d"), aspect = (box.clientWidth || 600) / (box.clientHeight || 420);
  BLD.camPlan.position.set(pcx, elev + 200, -pcy);
  BLD.camPlan.up.set(0, 0, -1);
  BLD.camPlan.lookAt(pcx, elev, -pcy);
  if (BLD.plan) BLD.controls.target.set(pcx, elev, -pcy);
  const k = Math.max((Math.max(...py) - Math.min(...py)) / 2, (Math.max(...px) - Math.min(...px)) / 2 / aspect, 4) * 1.15;
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
  BLD.grid.children[0].visible = !on;  // the plan keeps the 5 m lines only
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
  roomLabels(b);
  const e = extent(b), r = Math.max(e.size, e.top) * 0.85 + 12;
  BLD.sun.target.position.set(e.cx, 0, -e.cy);
  BLD.sun.position.set(e.cx + r * 0.7, r * 1.1, -e.cy + r * 0.45);
  Object.assign(BLD.sun.shadow.camera, { left: -r, right: r, top: r, bottom: -r, near: 1, far: r * 4 });
  BLD.sun.shadow.camera.updateProjectionMatrix();
  BLD.sky.visible = BLD.ground.visible = !BLD.plan;
  BLD.scene.background = new THREE.Color(BLD.plan ? 0xf7f8fa : 0xdfe9f2);
  BLD.grid.position.y = lvlOf(b, BLD.level).elevation + 0.002;
  draw();
}

// room names and areas on the plan of a level (sprites drawn over everything, sized to their room)
const LABELS = new Map();
function labelTexture(name, area) {
  const key = `${name}|${area}`;
  if (LABELS.has(key)) return LABELS.get(key);
  const c = document.createElement("canvas");
  c.width = 512; c.height = 160;
  const x = c.getContext("2d");
  x.textAlign = "center"; x.fillStyle = "#1f2933";
  let size = 62;
  const text = name === "Corridor" ? name : name.toUpperCase();
  do { x.font = `700 ${size}px Inter, Arial, sans-serif`; size -= 4; } while (x.measureText(text).width > 500 && size > 20);
  x.fillText(text, 256, area ? 72 : 100);
  if (area) { x.font = "400 44px Inter, Arial, sans-serif"; x.fillStyle = "#5d6874"; x.fillText(`${area} m²`, 256, 132); }
  const t = new THREE.CanvasTexture(c);
  LABELS.set(key, t);
  return t;
}
function roomLabels(b) {
  BLD.labels.clear();
  if (!BLD.plan) return;
  const lv = lvlOf(b, BLD.level);
  for (const r of b.rooms || []) {
    if (r.level !== BLD.level || r.name === "Stair") continue;
    const w = Math.max(1.2, Math.min(r.w || 4, 6)) * 0.9;
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: labelTexture(r.name, r.area), depthTest: false, transparent: true }));
    sp.scale.set(w, w * 160 / 512, 1);
    sp.position.set(r.x, lv.elevation + lv.height + 1, -r.y);
    sp.renderOrder = 10;
    BLD.labels.add(sp);
  }
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
  return ({ wall: b.walls, opening: b.openings, column: b.columns, stair: b.stairs, slab: b.slabs, roof: b.roofs, landscape: b.landscape || [] }[s.type] || []).find((x) => x.id === s.id);
}
function dragSelection(drag, p) {  // move by the dragged distance, on the 0.1 m grid
  const o = selObj(), was = JSON.parse(drag.snapshot);
  if (!o || !drag.start) return;
  const dx = Math.round((p[0] - drag.start[0]) * 10) / 10, dy = Math.round((p[1] - drag.start[1]) * 10) / 10;
  if (BLD.sel.type === "wall") { o.a = [was.a[0] + dx, was.a[1] + dy]; o.b = [was.b[0] + dx, was.b[1] + dy]; }
  else if (BLD.sel.type === "landscape") o.points = was.points.map((q) => [q[0] + dx, q[1] + dy]);
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
  const coll = { wall: "walls", opening: "openings", column: "columns", stair: "stairs", slab: "slabs", roof: "roofs", landscape: "landscape" }[s.type];
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
  landscape: [["kind", ["flower_bed", "lawn", "shrub_bed", "paving", "hedge", "tree"]]],
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
const AUTO = [["use", "Building use (names the rooms)", ["general", "house", "office", "hospital", "school", "apartments"]],
  ["corridor", "Corridor (rooms off it)", ["auto", "none", "1.5", "1.8", "2.4", "3.0"]], ["width", "Width east-west (m)", 12], ["depth", "Depth north-south (m)", 9], ["floors", "Floors", 1], ["floor_height", "Floor to floor (m)", 3],
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
  if (body.corridor === "auto") delete body.corridor;  // 1.8 m (2.4 m in a hospital), none for a house
  else if (body.corridor === "none") body.corridor = 0;
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
