"use strict";
// Share dialog: who has access to the open project (owner, assignee, editors, viewers, company), add people by
// name / username / email with "can edit" or "can view", change or remove access, and copy the project link.
(() => {
  const dlg = $("#shareDlg"), who = $("#shareWho"), hits = $("#shareHits");
  const ACCESS = { owner: "Owner", assigned: "Assigned planner", edit: "Can edit", view: "Can view" };
  let timer = null;

  const initial = (p) => (p.name || p.username || "?").trim().charAt(0).toUpperCase();

  function render() {
    const st = S.st;
    if (!st) return;
    const manage = !!st.can_manage;
    $("#shareTitle").textContent = `Share "${S.D.info.name || "project"}"`;
    $("#shareForm").hidden = !manage;
    $("#shareNoManage").hidden = manage;
    $("#sharePeople").innerHTML = (st.people || []).map((p) => {
      const fixed = p.access === "owner" || p.access === "assigned" || !manage;
      const control = fixed ? `<span class="tag">${ACCESS[p.access]}</span>` :
        `<select data-user="${esc(p.username)}" aria-label="Access for ${esc(p.username)}">
           <option value="edit" ${p.access === "edit" ? "selected" : ""}>Can edit</option>
           <option value="view" ${p.access === "view" ? "selected" : ""}>Can view</option></select>
         <button type="button" class="rm" data-remove="${esc(p.username)}" title="Remove access" aria-label="Remove ${esc(p.username)}">&times;</button>`;
      return `<li><span class="av">${esc(initial(p))}</span>
        <span class="who"><b>${esc(p.name || p.username)}${p.username === document.body.dataset.user ? " (you)" : ""}</b>
          <small>${esc(p.username)}${p.email ? " · " + esc(p.email) : ""}</small></span>${control}</li>`;
    }).join("");
    const co = st.company;
    $("#shareCompany").hidden = !co;
    if (co) $("#shareCompany").textContent = `Everyone at ${co.name} also has access: viewers can view and comment, ` +
      "planners and above can edit, approvers can approve.";
    $("#shareLink").value = `${location.origin}/?project=${encodeURIComponent(S.pid)}`;
  }

  async function setAccess(username, access) {
    try {
      S.st = await api(`/api/projects/${S.pid}/share`, jsonBody({ username, access }));
      render();
      toast(access === "remove" ? `Removed ${username}` : `${username}: ${ACCESS[access].toLowerCase()}`);
    } catch (e) { toast(e.message, 6000); }
  }

  async function search() {
    const q = who.value.trim();
    if (q.length < 2) { hits.hidden = true; return; }
    let list = [];
    try { list = await api(`/api/people?q=${encodeURIComponent(q)}`); } catch (_) { /* typed name still works */ }
    const have = new Set((S.st.people || []).map((p) => p.username));
    list = list.filter((u) => !have.has(u.username));
    hits.innerHTML = list.map((u) => `<button type="button" data-pick="${esc(u.username)}"><b>${esc(u.name || u.username)}</b>
      <small>${esc(u.username)}${u.email ? " · " + esc(u.email) : ""}</small></button>`).join("");
    hits.hidden = !list.length;
  }

  $("#btnShare").addEventListener("click", () => {
    if (!S.st) return;
    render();
    who.value = ""; hits.hidden = true;
    dlg.showModal();
    if (S.st.can_manage) who.focus();
  });
  dlg.querySelector("[data-close]").addEventListener("click", () => dlg.close());
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });  // click on the backdrop
  who.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(search, 250); });
  hits.addEventListener("click", (e) => {
    const b = e.target.closest("[data-pick]");
    if (b) { who.value = b.dataset.pick; hits.hidden = true; who.focus(); }
  });
  $("#shareForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = who.value.trim();
    if (!name) return;
    await setAccess(name, $("#shareAccess").value);
    if (!dlg.open) return;
    who.value = ""; hits.hidden = true;
  });
  $("#sharePeople").addEventListener("change", (e) => {
    const sel = e.target.closest("select[data-user]");
    if (sel) setAccess(sel.dataset.user, sel.value);
  });
  $("#sharePeople").addEventListener("click", (e) => {
    const b = e.target.closest("[data-remove]");
    if (b && confirm(`Remove ${b.dataset.remove}'s access to this project?`)) setAccess(b.dataset.remove, "remove");
  });
  $("#shareCopy").addEventListener("click", async () => {
    const link = $("#shareLink");
    try { await navigator.clipboard.writeText(link.value); } catch (_) { link.select(); document.execCommand("copy"); }
    toast("Link copied");
  });
})();
