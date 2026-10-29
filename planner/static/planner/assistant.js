"use strict";
// AI assistant: a chat panel that asks the Groq model about the open project. The server adds a summary of the
// project and the trained Photo AI model's findings; the conversation lives in this page only. For planners who
// may edit, an answer can carry proposed changes: they are listed under it and made only when Apply is pressed.
(() => {
  const panel = $("#aiPanel"), log = $("#aiLog"), input = $("#aiInput"), send = $("#aiSend");
  const chats = {};  // project id -> [{role, content}]
  let status = null, busy = false, file = null;
  const ACCEPT = ".jpg,.jpeg,.png,.webp,.xlsx,.xlsm,.csv,.txt,.kml,.json,.geojson,.md";

  const SUGGEST = [
    "Summarise this project and what is left before approval",
    "Explain the QA errors and how to fix them",
    "Is the FAT and splitter sizing right for the homepasses?",
    "What did the photo AI find on the survey photos?",
    "Which BOQ lines cost the most, and can they be reduced?",
  ];
  const SUGGEST_BUILDING = [  // construction projects
    "Summarise this building and what is left before approval",
    "Explain the QA errors and how to fix them",
    "Check the floor-to-floor heights, stairs and headroom",
    "Which BOQ lines cost the most, and can they be reduced?",
    "What should a structural engineer check in this design?",
    "Add flower beds and trees round the compound",
  ];

  // answers are shown as escaped text with a small markdown subset: **bold**, *italic*, `code`, headings,
  // bullet lines and |tables| (tables can be collapsed, and long ones show their first rows until expanded)
  const TABLE_PREVIEW = 6;
  const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<i>$2</i>")
    .replace(/`([^`]+)`/g, "<code>$1</code>").replace(/&lt;br\s*\/?&gt;/gi, "<br>");
  const cellsOf = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => inline(c.trim()));
  const isRule = (line) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);

  function table(lines) {
    const head = cellsOf(lines[0]);
    const body = lines.slice(isRule(lines[1] || "") ? 2 : 1).filter((l) => !isRule(l)).map(cellsOf);
    const more = body.length > TABLE_PREVIEW;
    const rows = body.map((r, i) => `<tr${i >= TABLE_PREVIEW ? ' class="more"' : ""}>${head.map((_, j) => `<td>${r[j] ?? ""}</td>`).join("")}</tr>`).join("");
    return `<div class="aitable${more ? " long" : ""}">
      <div class="aitbar"><span>Table · ${body.length} row${body.length === 1 ? "" : "s"}</span>
        ${more ? `<button type="button" data-tmore>Show all ${body.length} rows</button>` : ""}
        <button type="button" data-tfold aria-expanded="true">Collapse</button></div>
      <div class="aitwrap"><table><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>
    </div>`;
  }

  function format(text) {
    const lines = esc(text).split(/\n/);
    let html = "", inList = false;
    const endList = () => { if (inList) { html += "</ul>"; inList = false; } };
    for (let k = 0; k < lines.length; k++) {
      const raw = lines[k];
      if (/^\s*\|.*\|\s*$/.test(raw)) {  // a run of |...| lines is a table
        const block = [];
        while (k < lines.length && /^\s*\|.*\|\s*$/.test(lines[k])) block.push(lines[k++]);
        k--;
        endList();
        html += block.length > 1 ? table(block) : `<p>${inline(raw)}</p>`;
        continue;
      }
      const m = raw.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
      if (m) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${inline(m[1])}</li>`; continue; }
      endList();
      const h = raw.match(/^\s*#{1,6}\s+(.*)$/);
      if (h) html += `<h4>${inline(h[1])}</h4>`;
      else if (raw.trim()) html += `<p>${inline(raw)}</p>`;
    }
    endList();
    return html;
  }

  function changesCard(m, i) {  // what the assistant proposes to change, with Apply / Dismiss
    if (!m.actions?.length) return "";
    const state = m.applied ? `<div class="aidone">&#10003; Applied${m.result?.length ? `: ${esc(m.result.join("; "))}` : ""}. Press Undo (Ctrl+Z) to take it back.</div>`
      : m.dismissed ? `<div class="aidone muted">Dismissed</div>`
      : `<div class="aiacts"><button type="button" class="ok" data-apply="${i}">Apply ${m.actions.length > 1 ? `these ${m.actions.length} changes` : "this change"}</button>
         <button type="button" data-dismiss="${i}">Dismiss</button></div>`;
    return `<div class="aichanges"><b>Proposed change${m.actions.length > 1 ? "s" : ""} to the project</b>
      <ul>${m.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>${state}</div>`;
  }

  async function applyChanges(i) {
    const m = (chats[S.pid] || [])[i];
    if (!m || m.applied || busy) return;
    busy = true; render();
    try {
      const st = await serverOp(`/api/projects/${S.pid}/ai-apply`, jsonBody({ actions: m.actions }));
      m.applied = true; m.result = st.result;
      toast("Changes applied");
      if (typeof renderBuilding === "function" && isConstruction() && BLD.renderer) renderBuilding(false);
    } catch (e) { toast(e.message, 8000); }
    finally { busy = false; render(); }
  }

  // table controls and proposed changes inside answers
  log.addEventListener("click", (e) => {
    const ap = e.target.closest("[data-apply]"), dis = e.target.closest("[data-dismiss]");
    if (ap) return applyChanges(+ap.dataset.apply);
    if (dis) { const m = (chats[S.pid] || [])[+dis.dataset.dismiss]; if (m) { m.dismissed = true; render(); } return; }
    const fold = e.target.closest("[data-tfold]"), more = e.target.closest("[data-tmore]");
    if (fold) {
      const t = fold.closest(".aitable"), shut = t.classList.toggle("folded");
      fold.textContent = shut ? "Expand" : "Collapse";
      fold.setAttribute("aria-expanded", String(!shut));
    } else if (more) {
      const t = more.closest(".aitable"), all = t.classList.toggle("all");
      more.textContent = all ? "Show fewer rows" : `Show all ${t.querySelectorAll("tbody tr").length} rows`;
    }
  });

  function render() {
    const msgs = chats[S.pid] || [];
    if (!status || !status.enabled) {
      log.innerHTML = `<div class="aiempty"><b>The AI assistant is not set up on this server.</b>
        <p>An administrator adds a Groq API key named <code>AI_CHAT_KEY</code> to the server's settings:</p>
        <ul><li><b>Vercel:</b> Project &rarr; Settings &rarr; Environment Variables, then redeploy.</li>
        <li><b>Docker / own server:</b> the <code>.env</code> file, then restart the app.</li></ul>
        <p>Add <code>PHOTO_AI_PROVIDER=groq</code> and <code>PHOTO_AI_KEY</code> too for photo checks.</p></div>`;
      return;
    }
    if (!msgs.length) {
      log.innerHTML = `<div class="aiempty"><b>Ask about this project</b>
        <p>Answers use this project's ${S.st?.sector?.construction ? "building" : "survey, design"}, BOQ and QA figures${status.photo_ai ? " and the trained photo model's findings" : ""}.</p>
        <div class="aisugg">${(S.st?.sector?.construction ? SUGGEST_BUILDING : SUGGEST).map((q) => `<button type="button" data-q="${esc(q)}">${esc(q)}</button>`).join("")}</div></div>`;
      log.querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => ask(b.dataset.q)));
      return;
    }
    log.innerHTML = msgs.map((m, i) => `<div class="aimsg ${m.role}${m.error ? " err" : ""}">${m.file ? `<span class="aifile">&#128206; ${esc(m.file)}</span>` : ""}${m.role === "user" ? esc(m.content) : format(m.content) + changesCard(m, i)}</div>`).join("")
      + (busy ? `<div class="aimsg assistant typing"><span></span><span></span><span></span></div>` : "");
    log.scrollTop = log.scrollHeight;
  }

  function showFile() {
    const chip = $("#aiChip");
    chip.hidden = !file;
    if (file) chip.querySelector("span").textContent = `${file.name} · ${Math.max(1, Math.round(file.size / 1024))} KB`;
  }

  async function ask(q) {
    q = (q || "").trim();
    if (busy || !S.pid || (!q && !file)) return;
    q = q || "What does the attached file show, and how does it relate to this project?";
    const msgs = chats[S.pid] = chats[S.pid] || [];
    const mine = { role: "user", content: q, file: file ? file.name : "" };
    msgs.push(mine);
    const history = msgs.filter((m) => !m.error)
      .map((m) => ({ role: m.role, content: (m.extra ? `${m.content}\n\n${m.extra}` : m.content)
        + (m.actions?.length ? `\n\n[Proposed changes: ${m.changes.join("; ")} - ${m.applied ? "applied by the planner" : m.dismissed ? "dismissed" : "not applied yet"}]` : "") }));
    let opts;
    if (file) {  // the file goes with this question; its findings are kept for follow-up questions
      const fd = new FormData();
      fd.append("messages", JSON.stringify(history));
      fd.append("file", file);
      opts = { method: "POST", body: fd };
    } else opts = jsonBody({ messages: history });
    input.value = ""; file = null; $("#aiFile").value = ""; showFile();
    busy = true; send.disabled = true; render();
    try {
      const r = await api(`/api/projects/${S.pid}/ai-chat`, opts);
      if (r.attachment) mine.extra = r.attachment;
      msgs.push({ role: "assistant", content: r.answer, actions: r.actions || [], changes: r.changes || [] });
    } catch (e) {
      msgs.push({ role: "assistant", content: e.message, error: true });
    } finally {
      busy = false; send.disabled = false; render(); input.focus();
    }
  }

  async function open() {
    panel.style.top = `${Math.round(document.querySelector("header").getBoundingClientRect().bottom) + 8}px`;  // header may wrap
    panel.hidden = false;
    $("#btnAI").setAttribute("aria-expanded", "true");
    if (!status) { try { status = await api("/api/ai-chat"); } catch (_) { status = { enabled: false }; } }
    $("#aiModel").textContent = status.enabled ? "" : "not set up";
    input.disabled = send.disabled = $("#aiAttach").disabled = !status.enabled;
    render();
    if (status.enabled) input.focus();
  }
  function close() { panel.hidden = true; $("#btnAI").setAttribute("aria-expanded", "false"); }

  $("#btnAI").addEventListener("click", () => (panel.hidden ? open() : close()));
  $("#aiClose").addEventListener("click", close);
  $("#aiWide").addEventListener("click", (e) => {
    const wide = panel.classList.toggle("wide");
    e.target.textContent = wide ? "Narrower" : "Wider";
    e.target.setAttribute("aria-pressed", String(wide));
  });
  $("#aiClear").addEventListener("click", () => { delete chats[S.pid]; render(); });
  $("#aiFile").accept = ACCEPT;
  $("#aiAttach").addEventListener("click", () => $("#aiFile").click());
  $("#aiFile").addEventListener("change", (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const image = /\.(jpe?g|png|webp)$/i.test(f.name);
    if (f.size > (image ? 10 : 2) * 1024 * 1024) { toast(image ? "Photos must be smaller than 10 MB" : "Files must be smaller than 2 MB"); e.target.value = ""; return; }
    if (image && !status.photo_ai) { toast("Photo AI is not set up on this server, so photos cannot be checked"); e.target.value = ""; return; }
    file = f; showFile(); input.focus();
  });
  $("#aiChip button").addEventListener("click", () => { file = null; $("#aiFile").value = ""; showFile(); });
  $("#aiForm").addEventListener("submit", (e) => { e.preventDefault(); ask(input.value); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input.value); } });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !panel.hidden) close(); });
  $("#projectSelect").addEventListener("change", () => { if (!panel.hidden) setTimeout(render, 0); });
})();

// account menu in the header: close it when clicking elsewhere or pressing Escape
(() => {
  const menu = document.querySelector("header .huser");
  if (!menu) return;
  document.addEventListener("click", (e) => { if (menu.open && !menu.contains(e.target)) menu.open = false; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") menu.open = false; });
})();
