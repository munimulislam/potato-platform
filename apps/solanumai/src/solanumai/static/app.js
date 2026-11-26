// Shared behaviour for every page.

// Light/dark toggle, remembered per browser (the initial theme is set in base.html before paint).
document.addEventListener("click", (e) => {
  if (!e.target.closest("[data-theme-toggle]")) return;
  const dark = document.documentElement.classList.toggle("dark");
  try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch (_) {}
});

// Forms that return a file (batch prediction): download on success, show the server's message on error,
// instead of leaving the page for a raw JSON error.
document.addEventListener("submit", async (e) => {
  const form = e.target.closest("form[data-download]");
  if (!form) return;
  e.preventDefault();
  const errorBox = form.querySelector("[data-error]");
  const button = form.querySelector("button[type=submit]");
  errorBox.hidden = true;
  button.disabled = true;
  try {
    const res = await fetch(form.action, { method: "POST", body: new FormData(form) });
    if (res.status === 401) { window.location.href = "/login"; return; }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${res.status})`);
    }
    const blob = await res.blob();
    const name = (res.headers.get("Content-Disposition") || "").match(/filename="(.+)"/)?.[1] || "download";
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    errorBox.textContent = err.message;   // textContent: never interpreted as HTML
    errorBox.hidden = false;
  } finally {
    button.disabled = false;
  }
});