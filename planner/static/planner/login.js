"use strict";
// Sign-in page: show / hide password, Caps Lock warning, and a busy state while signing in.
(() => {
  const pw = document.getElementById("id_password");
  const reveal = document.getElementById("reveal");
  const caps = document.getElementById("caps");
  const form = document.getElementById("loginForm");
  const btn = document.getElementById("submitBtn");
  if (reveal && pw) {
    reveal.addEventListener("click", () => {
      const show = pw.type === "password";
      pw.type = show ? "text" : "password";
      reveal.setAttribute("aria-pressed", String(show));
      reveal.setAttribute("aria-label", show ? "Hide password" : "Show password");
      pw.focus();
    });
  }
  if (pw && caps) {
    const check = (e) => { if (e.getModifierState) caps.classList.toggle("show", e.getModifierState("CapsLock")); };
    pw.addEventListener("keydown", check);
    pw.addEventListener("keyup", check);
    pw.addEventListener("blur", () => caps.classList.remove("show"));
  }
  if (form && btn) {
    form.addEventListener("submit", () => {
      btn.disabled = true;
      btn.querySelector(".label").textContent = "Signing in…";
    });
  }
})();
