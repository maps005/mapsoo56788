"use strict";
// Dam tab (dams sector): the survey, hydrology and design inputs of the earthfill dam (S.D.dam, ftth/dam.py), and
// the server's design (S.st.summary.dam): levels, the stability checks, and previews of the maximum cross-section,
// the long section on the axis and the area-capacity curve.
const isDam = () => !!S.st?.sector?.dam;

const DAM_FORM = [
  ["Survey", [["name", "Dam name", "text"], ["river", "River", "text"],
    ["axis", "Axis profile: chainage m, ground level m, depth to firm ground m (one point a line)", "rows"],
    ["reservoir", "Reservoir: level m, water area m2 (from the contour survey, one a line)", "rows"]]],
  ["Hydrology and use", [["catchment_km2", "Catchment (km2)"], ["stream_km", "Longest watercourse (km)"],
    ["stream_slope", "Its slope (%)"], ["rain_24h", "Design storm, 24 h, 1 in 100 (mm)"], ["rain_annual", "Mean annual rainfall (mm)"],
    ["runoff_flood", "Flood runoff coefficient C"], ["runoff_annual", "Annual runoff share"], ["evaporation", "Open-water evaporation (mm/yr)"],
    ["demand", "Draw-off (m3/day)"], ["compensation", "Compensation / reserve flow (m3/day)"],
    ["design_flood", "Design flood (m3/s, 0 = Rational method)"], ["rain_cv", "CV of annual 24 h maxima"],
    ["sediment_yield", "Sediment yield (t/km2/yr)"], ["sediment_years", "Sediment design life (years)"]]],
  ["Dam safety", [["hazard", "Hazard class (breach consequence)", ["high", "significant", "low"]],
    ["seismic_kh", "Pseudo-static seismic coefficient kh"], ["fetch_km", "Effective fetch (km, 0 = estimate)"]]],
  ["Reservoir levels", [["fsl", "Full supply level (m, 0 = from target storage)"], ["target_storage", "Target storage (m3)"],
    ["outlet_level", "Outlet invert / MOL (m, 0 = bed + 1.5)"]]],
  ["Embankment", [["crest_width", "Crest width (m, 0 = USBR)"], ["slope_us", "Upstream slope (H:1V)"], ["slope_ds", "Downstream slope (H:1V)"],
    ["core_top", "Core top width (m)"], ["core_slope", "Core side slopes (H:1V)"], ["filter_width", "Chimney filter (m)"],
    ["riprap", "Minimum riprap thickness (m)"], ["cutoff_width", "Cut-off trench width (m)"], ["wind_kmh", "Design wind (km/h)"]]],
  ["Materials (geotechnical report)", [["shell_phi", "Shell friction angle (deg)"], ["shell_c", "Shell effective cohesion c' (kPa)"],
    ["shell_gamma", "Shell unit weight (kN/m3)"], ["core_k", "Core permeability (m/s)"]]],
  ["Spillway", [["spillway_width", "Width (m, 0 = for the head below)"], ["spillway_head", "Design head (m)"],
    ["spillway_c", "Weir coefficient C"], ["spillway_side", "Abutment", ["right", "left"]]]],
];
const DAM_DEFAULT = { name: "Earth dam", river: "", axis: [], reservoir: [], catchment_km2: 0, stream_km: 0, stream_slope: 0,
  rain_24h: 0, rain_annual: 0, runoff_flood: 0.5, runoff_annual: 0.1, evaporation: 1800, demand: 0, design_flood: 0, fsl: 0,
  target_storage: 0, outlet_level: 0, crest_width: 0, slope_us: 3, slope_ds: 2.5, core_top: 3, core_slope: 0.5, filter_width: 1,
  riprap: 0.6, cutoff_width: 4, wind_kmh: 80, shell_phi: 30, shell_c: 0, shell_gamma: 19.5, core_k: 1e-8, spillway_width: 0,
  spillway_head: 1, spillway_c: 1.7, spillway_side: "right", hazard: "high", rain_cv: 0.35, sediment_yield: 300,
  sediment_years: 50, fetch_km: 0, compensation: 0, seismic_kh: 0.05 };

function renderDamForm() {
  const box = $("#damForm");
  if (!S.D.dam) {
    box.innerHTML = `<p class="muted">No dam in this project yet.</p><button id="damCreate" class="primary">Start the dam design</button>`;
    $("#damCreate").onclick = () => { S.D.dam = JSON.parse(JSON.stringify(DAM_DEFAULT)); changed(false); renderDam(true); };
    return;
  }
  const dm = S.D.dam;
  const rows = (k) => (dm[k] || []).map((r) => r.join(", ")).join("\n");
  box.innerHTML = DAM_FORM.map(([title, fields]) => `<h3>${esc(title)}</h3>` + fields.map(([k, label, kind]) =>
    Array.isArray(kind) ? `<label>${esc(label)}<select data-dam="${k}">${kind.map((x) => `<option ${x === dm[k] ? "selected" : ""}>${x}</option>`).join("")}</select></label>`
    : kind === "rows" ? `<label>${esc(label)}<textarea data-dam="${k}" rows="6" spellcheck="false">${esc(rows(k))}</textarea></label>`
    : kind === "text" ? `<label>${esc(label)}<input data-dam="${k}" value="${esc(dm[k] ?? "")}"></label>`
    : `<label>${esc(label)}<input data-dam="${k}" type="number" step="any" value="${esc(dm[k] ?? 0)}"></label>`).join("")).join("");
  $$("[data-dam]").forEach((i) => i.addEventListener("change", () => {
    const k = i.dataset.dam, kind = DAM_FORM.flatMap(([, f]) => f).find((f) => f[0] === k)?.[2];
    if (kind === "rows") {
      dm[k] = i.value.split(/\n/).map((l) => l.split(/[,;\t ]+/).map((x) => parseFloat(x)).filter((x) => !isNaN(x)))
        .filter((r) => r.length >= 2).slice(0, 500);
    } else if (kind === "text" || Array.isArray(kind)) dm[k] = i.value;
    else dm[k] = +i.value || 0;
    changed(false);
  }));
}

function damSvgSection(z) {
  // the maximum section, natural scale: shells, core, levels
  const h = z.height, W = z.crest_width, su = z.slope_us, sd = z.slope_ds, up = W / 2 + su * h, dn = W / 2 + sd * h;
  const w = 560, ht = 220, k = Math.min((w - 40) / (up + dn + 10), (ht - 40) / (h + 4));
  const X = (x) => 20 + (x + up + 5) * k, Y = (y) => ht - 20 - y * k;
  const core = z.core_top_level - z.bed, ct = 1.5, cs = 0.5;
  const pts = (a) => a.map(([x, y]) => `${X(x).toFixed(1)},${Y(y).toFixed(1)}`).join(" ");
  const fsl = z.fsl - z.bed, mfl = z.mfl - z.bed;
  return `<svg viewBox="0 0 ${w} ${ht}" class="damsvg"><rect x="0" y="${Y(0)}" width="${w}" height="${ht - Y(0)}" fill="#e8dccb"/>
    <polygon points="${pts([[-up - 5, 0], [-up, 0], [-(W / 2 + su * (h - fsl)), fsl], [-up - 5, fsl]])}" fill="#cfe3f7"/>
    <polygon points="${pts([[-up, 0], [dn, 0], [W / 2, h], [-W / 2, h]])}" fill="#d9c7a3" stroke="#22313f"/>
    <polygon points="${pts([[-ct - cs * core, 0], [ct + cs * core, 0], [ct, core], [-ct, core]])}" fill="#a1887f" stroke="#22313f"/>
    ${[[h, `Crest ${z.crest.toFixed(2)}`, "#22313f"], [mfl, `MFL ${z.mfl.toFixed(2)}`, "#1565c0"], [fsl, `FSL ${z.fsl.toFixed(2)}`, "#1565c0"]]
      .map(([y, t, c]) => `<line x1="${X(-up - 5)}" x2="${X(dn + 5)}" y1="${Y(y)}" y2="${Y(y)}" stroke="${c}" stroke-dasharray="3 2" stroke-width=".6"/>
        <text x="${X(dn + 4)}" y="${Y(y) - 2}" font-size="9" fill="${c}" text-anchor="end">${t}</text>`).join("")}
    <text x="${X(-up / 2)}" y="${Y(h / 2)}" font-size="10" text-anchor="end">1:${su}</text>
    <text x="${X(dn / 2)}" y="${Y(h / 2)}" font-size="10">1:${sd}</text>
    <text x="${X(0)}" y="${Y(h) - 4}" font-size="9" text-anchor="middle">${W} m</text></svg>`;
}

function damSvgLong(z) {
  const p = z.profile; if (!p?.length) return "";
  const w = 560, ht = 180, c0 = p[0][0], c1 = p[p.length - 1][0];
  const lo = Math.min(...p.map((r) => r[2])) - 2, hi = z.crest + 3;
  const X = (c) => 30 + (c - c0) / Math.max(c1 - c0, 1) * (w - 60), Y = (v) => ht - 20 - (v - lo) / Math.max(hi - lo, 1) * (ht - 35);
  const ground = p.map(([c, g]) => `${X(c).toFixed(1)},${Y(g).toFixed(1)}`).join(" ");
  const dam = p.filter(([, g]) => g <= z.crest + 1e-6);
  const fill = dam.length ? `<polygon points="${X(dam[0][0])},${Y(z.crest)} ${dam.map(([c, g]) => `${X(c).toFixed(1)},${Y(g).toFixed(1)}`).join(" ")} ${X(dam[dam.length - 1][0])},${Y(z.crest)}" fill="#d9c7a3" stroke="#22313f"/>` : "";
  const cut = dam.length ? `<polyline points="${dam.map(([c, , f]) => `${X(c).toFixed(1)},${Y(f).toFixed(1)}`).join(" ")}" fill="none" stroke="#8d6e63" stroke-width="1.5"/>` : "";
  return `<svg viewBox="0 0 ${w} ${ht}" class="damsvg">${fill}${cut}
    <polyline points="${ground}" fill="none" stroke="#22313f" stroke-width="1.4"/>
    <line x1="${X(c0)}" x2="${X(c1)}" y1="${Y(z.fsl)}" y2="${Y(z.fsl)}" stroke="#1565c0" stroke-dasharray="4 2"/>
    <text x="${X(c1)}" y="${Y(z.fsl) - 3}" font-size="9" fill="#1565c0" text-anchor="end">FSL ${z.fsl.toFixed(2)}</text>
    <text x="${X(c0)}" y="12" font-size="9">Long section on the axis (cut-off trench brown), ch ${c0}-${c1} m</text></svg>`;
}

function damSvgCap(z) {
  const cap = z.capacity; if (!cap?.length) return "";
  const w = 270, ht = 180, l0 = cap[0][0], l1 = cap[cap.length - 1][0], vmax = cap[cap.length - 1][2] || 1;
  const X = (v) => 30 + v / vmax * (w - 45), Y = (l) => ht - 20 - (l - l0) / Math.max(l1 - l0, 1e-6) * (ht - 35);
  return `<svg viewBox="0 0 ${w} ${ht}" class="damsvg"><rect x="30" y="15" width="${w - 45}" height="${ht - 35}" fill="none" stroke="#cbd2d9"/>
    <polyline points="${cap.map(([l, , v]) => `${X(v).toFixed(1)},${Y(l).toFixed(1)}`).join(" ")}" fill="none" stroke="#1565c0" stroke-width="1.5"/>
    <line x1="30" x2="${w - 15}" y1="${Y(z.fsl)}" y2="${Y(z.fsl)}" stroke="#22313f" stroke-dasharray="3 2"/>
    <text x="34" y="${Y(z.fsl) - 3}" font-size="9">FSL ${(z.storage / 1e6).toFixed(2)} Mm3</text>
    <text x="30" y="12" font-size="9">Capacity curve (level against volume)</text></svg>`;
}

function renderDamResults() {
  const z = S.st?.summary?.dam, box = $("#damResults");
  if (!z?.designed) {
    box.innerHTML = `<p class="muted">Enter the axis profile (two points at least) and the reservoir table: the design follows.</p>`;
    return;
  }
  const row = (a, b) => `<tr><td>${a}</td><td class="num">${b}</td></tr>`;
  box.innerHTML = `<div class="damgrid"><table class="ovtable">
      ${row("Crest level", `${z.crest.toFixed(2)} m (+${z.camber} camber)`)}${row("Height", `${z.height} m (${z.foundation_height} m from foundation)`)}
      ${row("Crest", `${z.crest_length} m x ${z.crest_width} m`)}${row("Slopes", `1:${z.slope_us} u/s, 1:${z.slope_ds} d/s`)}
      ${row("FSL / MFL / MOL", `${z.fsl.toFixed(2)} / ${z.mfl.toFixed(2)} / ${z.mol.toFixed(2)}`)}
      ${row("Storage at FSL", `${fmt(z.storage)} m3 (live ${fmt(z.live)})`)}${row(`Design flood 1:${fmt(z.T_design)}`, `${z.q100} m3/s`)}
      ${row(`Check flood 1:${fmt(z.T_check)}`, `${z.q_check} m3/s`)}${row("50-yr sediment level", `${z.sediment_level.toFixed(2)} m`)}
      ${row("Spillway", `${z.spillway_width} m, ${z.h100} m head; basin ${z.basin_len} m`)}${row("Riprap", `${z.riprap} m`)}${row("Embankment fill", `${fmt(z.fill)} m3`)}
      ${row("Seepage", `${z.seepage_m3_day} m3/day`)}${row("Outlet", `DN${z.outlet_dn}`)}
      ${row("Water balance", z.yield_ok ? "OK" : "<b class='err'>short</b>")}${row("Class", z.large_dam ? "Large dam (ICOLD)" : "Small dam")}</table>
    <table class="ovtable"><tr><th>Stability (Bishop)</th><th>F</th><th>min</th></tr>
      ${z.stability.map((s) => `<tr><td>${esc(s.case)} (${s.face})</td><td class="num ${s.ok ? "" : "err"}">${s.F}</td><td class="num">${s.need}</td></tr>`).join("")}</table></div>
    ${z.notes.length ? `<ul class="muted">${z.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
    <div class="damsvgs">${damSvgSection(z)}${damSvgCap(z)}${damSvgLong(z)}</div>`;
}

function renderDam(full) {
  if (!isDam()) return;
  if (full || !$("#damForm").contains(document.activeElement)) renderDamForm();
  renderDamResults();
}

function renderOvDam() {
  const box = $("#ovDam");
  if (!box || !isDam()) return;
  const z = S.st?.summary?.dam;
  if (!z?.designed) { box.innerHTML = `<p class="muted" style="padding:10px">No dam yet: open Dam design and enter the survey.</p>`; return; }
  box.innerHTML = `<table>${[["Height", `${z.height} m`], ["Crest", `${z.crest.toFixed(2)} m, ${z.crest_length} m long`],
    ["Full supply level", `${z.fsl.toFixed(2)} m`], ["Storage", `${fmt(z.storage)} m3`], ["Design flood", `${z.q100} m3/s`],
    ["Spillway", `${z.spillway_width} m wide`], ["Fill", `${fmt(z.fill)} m3`],
    ["Stability", z.stability.every((x) => x.ok) ? "all cases OK" : "FAILING"]].map(([k, v]) => `<tr><td>${k}</td><td class="num">${v}</td></tr>`).join("")}</table>`;
}
