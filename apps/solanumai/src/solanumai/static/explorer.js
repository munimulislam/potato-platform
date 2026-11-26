// Data explorer: talks to the JSON API (/api/tables). Every value goes in with textContent,
// never innerHTML, so nothing stored in the data can run as HTML or script.
(() => {
  const root = document.getElementById("explorer");
  if (!root) return;

  const $ = (id) => document.getElementById(id);
  const els = {
    list: $("table-list"), title: $("table-title"), body: $("table-body"),
    filterCol: $("filter-col"), filterVal: $("filter-val"), filterForm: $("filter-form"),
    prev: $("prev"), next: $("next"), pageInfo: $("page-info"), download: $("download"), panel: $("table-panel"),
  };
  const state = { schema: null, table: null, page: 1, filterCol: "", filterVal: "" };

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  };

  async function api(path) {
    const res = await fetch(path);
    if (res.status === 401) { window.location.href = "/login"; throw new Error("Not signed in"); }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${res.status})`);
    }
    return res.json();
  }

  const base = () => `/api/tables/${encodeURIComponent(state.schema)}/${encodeURIComponent(state.table)}`;
  const filterParams = () => {
    const p = new URLSearchParams();
    if (state.filterCol && state.filterVal) { p.set("filter_col", state.filterCol); p.set("filter_val", state.filterVal); }
    return p;
  };

  async function loadTables() {
    const tables = await api("/api/tables");
    const items = [];
    let lastSchema = null;
    for (const t of tables) {
      if (t.schema_name !== lastSchema) { items.push(el("div", "side-heading", t.schema_name)); lastSchema = t.schema_name; }
      const b = el("button", "side-item");
      b.type = "button";
      b.title = `${t.schema_name}.${t.table_name}`;
      b.append(el("span", null, t.table_name), el("span", "muted text-sm", `  ≈${t.approx_rows.toLocaleString()}`));
      b.addEventListener("click", () => selectTable(t.schema_name, t.table_name, b));
      items.push(b);
    }
    els.list.replaceChildren(...items);
  }

  async function selectTable(schema, table, button) {
    Object.assign(state, { schema, table, page: 1, filterCol: "", filterVal: "" });
    els.list.querySelectorAll(".side-item").forEach((b) => b.classList.toggle("active", b === button));
    els.filterVal.value = "";
    els.panel.hidden = false;
    await loadPage(true);
  }

  async function loadPage(resetColumns = false) {
    const params = filterParams();
    params.set("page", state.page);
    let data;
    try { data = await api(`${base()}?${params}`); }
    catch (err) { els.body.replaceChildren(el("div", "alert alert-destructive", err.message)); return; }

    els.title.textContent = `${data.schema_name}.${data.table_name}`;
    if (resetColumns) {
      els.filterCol.replaceChildren(...data.columns.map((c) => { const o = el("option", null, c); o.value = c; return o; }));
    }

    const wrap = el("div", "table-wrap");
    const table = el("table", "table");
    const head = el("tr");
    data.columns.forEach((c) => head.appendChild(el("th", null, c)));
    const thead = el("thead"); thead.appendChild(head);
    const tbody = el("tbody");
    if (!data.rows.length) {
      const td = el("td", "muted", "No rows match.");
      td.colSpan = data.columns.length;
      const tr = el("tr"); tr.appendChild(td); tbody.appendChild(tr);
    }
    data.rows.forEach((r) => {
      const tr = el("tr");
      r.forEach((v) => tr.appendChild(el("td", null, v ?? "")));
      tbody.appendChild(tr);
    });
    table.append(thead, tbody);
    wrap.appendChild(table);
    els.body.replaceChildren(wrap);

    els.pageInfo.textContent = `Page ${data.page}`;
    els.prev.disabled = data.page <= 1;
    els.next.disabled = !data.has_next;
    els.download.href = `${base()}/export?${filterParams()}`;
  }

  els.filterForm.addEventListener("submit", (e) => {
    e.preventDefault();
    state.filterCol = els.filterCol.value;
    state.filterVal = els.filterVal.value.trim();
    state.page = 1;
    loadPage();
  });
  els.prev.addEventListener("click", () => { state.page -= 1; loadPage(); });
  els.next.addEventListener("click", () => { state.page += 1; loadPage(); });

  loadTables().catch((err) => els.list.replaceChildren(el("div", "alert alert-destructive", err.message)));
})();