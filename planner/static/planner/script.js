"use strict";
// Script tab: build or change the open project from lines of commands (ftth/script.py runs them on the server,
// all or nothing). The text is kept per project in this browser while it is being written.
const SCRIPT_EXAMPLES = {
  network: `# a small fibre build: points are lat,lon (or E,N in the project's grid)
name "Script demo network"
crs utm
scale 1000
pop POP01 -1.2199,36.8949
pole P001 -1.2201,36.8955 type=concrete height=9 status=proposed
pole P002 -1.2203,36.8962 status=proposed
home H001 -1.2205,36.8963 units=4 kind=mdu
fat FAT01 on=P002 ports=8
cable C001 main 48 POP01 > P001 > P002 install=aerial
assign max=250
check`,
  building: `# a building from the brief
name "Script demo apartments"
site soil=clay bearing_capacity=150 water_table=4
room Bedroom 24 12
room Lounge 8 20
building width=24 depth=12 floors=4 use=apartments roof=flat columns=true
place -1.2921,36.8219 rotation=0
check`,
  dam: `# a dam's survey and parameters
dam name="Script demo dam" catchment_km2=18 stream_km=7 stream_slope=1.8 rain_24h=110 rain_annual=750 demand=1500 fsl=1515
axis 0 1522 1.5
axis 70 1506 2.5
axis 140 1500 3.5
axis 210 1506 2.5
axis 280 1521 1.5
reservoir 1500 0
reservoir 1505 30000
reservoir 1510 110000
reservoir 1515 250000
reservoir 1520 420000
check`,
};
const SCRIPT_HELP = `One command a line · # comment · "quotes" for spaces
Options key=value · points lat,lon or E,N

Any project
  name | area | client | prepared <text>
  crs utm | arc1960 | local
  scale 1000
  boundary lat,lon; lat,lon; lat,lon
  set info|site|dam|rules.<field> = <value>
  delete <ID> [ID ...]
  check

Network
  pole <ID> <pt> [type= height= status=]
  home <ID> <pt> [units= kind=]
  pop | closure | jb | pon | fat | slack <ID> <pt>
      or on=<pole> [ports=]
  cable <ID> main|spur|drop <cores> A > B > C
      [install= status=]
  autodesign [preset=]
  assign [max=250]
  allocate

Building
  site <field>=<value> ...
  room <name> <number> <area each>
  building width= depth= floors= use= roof= ... [add]
  place <pt> [rotation=]

Dam
  dam <field>=<value> ...
  axis <chainage> <ground> <depth to firm>
  reservoir <level> <area>
  damaxis <left pt> <right pt>`;

function scriptKind() {
  const t = S.st?.sector;
  return t?.dam ? "dam" : t?.construction ? "building" : "network";
}
function renderScript() {
  const box = $("#scriptText");
  if (!box || !S.pid) return;
  if (box.dataset.pid !== S.pid) {
    let saved = "";
    try { saved = localStorage.getItem(`script:${S.pid}`) || ""; } catch (_) { /* storage blocked */ }
    box.value = saved;
    box.dataset.pid = S.pid;
  }
  $("#scriptHelp").textContent = scriptHelp();
}
function scriptHelp() {  // this project's commands; other network sectors: what the equipment words and size mean
  const t = S.st?.sector, kind = scriptKind();
  const keep = { network: "Network", building: "Building", dam: "Dam" }[kind];
  const help = SCRIPT_HELP.split("\n\n").filter((b) => !/^(Network|Building|Dam)\n/.test(b) || b.startsWith(keep + "\n")).join("\n\n");
  if (!t || t.fibre_tools || kind !== "network") return help;
  const SCRIPT_HELP_ = help;
  const words = { pop: "POP", closure: "ENCLOSURE", jb: "JB", pon: "PON", fat: "FAT", slack: "SLACK" };
  const legend = Object.entries(words).map(([w, k]) => `      ${w.padEnd(8)}= ${t.kinds[k] || k}`).join("\n");
  return SCRIPT_HELP_.replace("<cores>", `<${t.size.split(" (")[0].toLowerCase()}>`)
    .replace("  pop | closure | jb | pon | fat | slack <ID> <pt>", `  <equipment word> <ID> <pt>, the words in this project:\n${legend}`)
    .replace("pole <ID>", `pole <ID> (a ${t.support.toLowerCase()})`).replace("home <ID>", `home <ID> (a ${t.premise.split("/")[0].trim().toLowerCase()})`);
}
$("#scriptText")?.addEventListener("input", (e) => {
  try { localStorage.setItem(`script:${S.pid}`, e.target.value); } catch (_) { /* storage blocked */ }
});
$("#scriptExample")?.addEventListener("click", () => {
  const box = $("#scriptText");
  if (box.value.trim() && !confirm("Replace the script with the example?")) return;
  box.value = SCRIPT_EXAMPLES[scriptKind()];
  box.dispatchEvent(new Event("input"));
});
$("#scriptRun")?.addEventListener("click", async () => {
  const text = $("#scriptText").value, out = $("#scriptLog");
  if (!text.trim()) return toast("Write the script first (or load the example)");
  out.classList.remove("err");
  out.textContent = "Running...";
  try {
    const st = await serverOp(`/api/projects/${S.pid}/script`, jsonBody({ script: text }));
    out.textContent = st.log.join("\n");
    toast("Script run: the project is updated");
  } catch (e) {
    out.classList.add("err");
    out.textContent = `${e.message}\nNothing was changed.`;
    const m = /^Line (\d+)/.exec(e.message);  // select the bad line
    if (m) {
      const box = $("#scriptText"), lines = box.value.split("\n"), n = +m[1] - 1;
      const start = lines.slice(0, n).join("\n").length + (n ? 1 : 0);
      box.focus(); box.setSelectionRange(start, start + (lines[n] || "").length);
    }
  }
});
