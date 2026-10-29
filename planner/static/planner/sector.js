"use strict";
// Sector: the planner speaks the project's sector (fibre, water, pipelines, electricity, sanitation). Names of
// features, the seven workflow steps and the editor tools follow S.st.sector; fibre-only tools are hidden for the
// other sectors. Settings can switch the project to another sector.
const SECTOR_ORIG = {};

function applySector() {
  const t = S.st?.sector;
  const fibre = !t || t.fibre_tools;
  document.body.dataset.sector = t?.key || "fibre";
  $$("[data-fibre-only], [data-tab='splicing']").forEach((e) => { e.hidden = !fibre; });
  // construction: a building instead of a network (Building 3D tab, site plan, no LLD / network tools)
  const build = !!t?.construction;
  $$("[data-network-only]").forEach((e) => { e.hidden = build; });
  $$("[data-construction-only]").forEach((e) => { e.hidden = !build; });
  if ((build && ["lld", "splicing"].includes(activeTab())) || (!build && activeTab() === "building")) $("[data-tab='overview']").click();

  // workflow steps
  $$("#steps > li").forEach((li, i) => {
    const b = li.querySelector(".stxt > b"), ul = li.querySelector(".stxt > ul");
    if (!SECTOR_ORIG.steps) SECTOR_ORIG.steps = [];
    if (!SECTOR_ORIG.steps[i]) SECTOR_ORIG.steps[i] = [b.innerHTML, ul.innerHTML];
    const s = t?.steps?.[i];
    if (s) { b.textContent = s[0]; ul.innerHTML = s[1].map((x) => `<li>${esc(x)}</li>`).join(""); }
    else [b.innerHTML, ul.innerHTML] = SECTOR_ORIG.steps[i];
  });

  // tabs and editor tools
  const relabel = (sel, text) => { const e = $(sel); if (!e) return; SECTOR_ORIG[sel] ??= e.textContent; e.textContent = text ?? SECTOR_ORIG[sel]; };
  relabel("[data-tab='map']", fibre ? null : build ? "Site plan" : "Network map");
  relabel("[data-tab='lld']", fibre ? null : "Detailed drawing");
  relabel("[data-tab='schedules']", fibre ? null : build ? "BOM · BOQ" : `${t.support} summary · BOM · BOQ`);
  relabel("[data-mode='pole']", fibre ? null : `+ ${t.support}`);
  relabel("#ovPolesTitle", fibre ? null : `${t.support} schedule`.toUpperCase());
  relabel("#ovPolesAll", fibre ? null : `All ${t.support.toLowerCase()}s`);
  relabel("#schPolesTitle", fibre ? null : `${t.support} schedule`);
  relabel("[data-mode='home']", fibre ? null : `+ ${t.premise.split("/")[0].trim()}`);
  $$("#nodeKind option").forEach((o) => {
    SECTOR_ORIG["k" + o.value] ??= o.textContent;
    o.textContent = fibre ? SECTOR_ORIG["k" + o.value] : (t.kinds[o.value] || o.value);
  });
  $$("#cableKind option").forEach((o) => {
    SECTOR_ORIG["c" + o.value] ??= o.textContent;
    o.textContent = fibre ? SECTOR_ORIG["c" + o.value] : (t.lines[o.value] || o.value);
  });
  // line sizes: fibre cores, pipe diameters (DN mm) or conductor sizes (mm²)
  const sizes = t?.sizes || [2, 4, 6, 8, 12, 24, 48, 72, 96, 144], unit = t?.size_unit || "C";
  const defaults = t?.size_defaults || { main: 48, spur: 12, drop: 2 };
  const sel = $("#cableCores"), key = sizes.join(",");
  if (sel && sel.dataset.sizes !== key) {
    sel.innerHTML = sizes.map((c) => `<option value="${c}">${unit === "C" ? `${c}C` : `${c} ${unit}`}</option>`).join("");
    sel.dataset.sizes = key;
    sel.value = defaults[$("#cableKind").value] ?? sizes[0];
  }
  $("#cableKind").onchange = () => { $("#cableCores").value = defaults[$("#cableKind").value]; };
  if (!fibre && $(".tab.active#tab-splicing")) $("[data-tab='overview']").click();
  renderSectorSetting();
}

let SECTOR_LIST = null;
async function renderSectorSetting() {
  const sel = $("#sectorSel");
  if (!sel || !S.st) return;
  try { SECTOR_LIST = SECTOR_LIST || await api("/api/sectors"); } catch (_) { return; }
  const now = S.st.sector?.key || "fibre", co = S.st.company?.sector;
  sel.innerHTML = SECTOR_LIST.map((x) => `<option value="${esc(x.key)}" ${x.key === now ? "selected" : ""}>${esc(x.label)}${x.key === co ? " (company)" : ""}</option>`).join("");
}

$("#sectorApply")?.addEventListener("click", async () => {
  const key = $("#sectorSel").value;
  if (key === (S.st.sector?.key || "fibre")) return toast("The project already uses this sector");
  const keep = key === "fibre" || !confirm("Switch this project's sector?\n\nOK: also load the sector's material catalogue " +
    "(replaces the current materials and rules).\nCancel: keep the current materials.");
  try {
    await flush();
    const st = await serverOp(`/api/projects/${S.pid}/apply-sector`, jsonBody({ sector: key, keep_materials: keep }));
    toast(`Project sector: ${st.result.label}`);
  } catch (e) { toast(e.message, 7000); }
});
