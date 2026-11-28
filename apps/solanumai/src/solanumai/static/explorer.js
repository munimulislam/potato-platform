(() => {
  const root = document.getElementById("explorer");
  if (!root) return;

  const $ = (id) => document.getElementById(id);
  const els = {
    form: $("filters"), env: $("f-env"), yearFrom: $("f-year-from"), yearTo: $("f-year-to"),
    locations: $("location-options"), trait: $("f-trait"), reset: $("reset"),
    body: $("table-body"), summary: $("summary"), download: $("download"),
    prev: $("prev"), next: $("next"), pageInfo: $("page-info"),
  };
  const FROZEN_COLUMNS = 6; // the meta ID columns, always first
  const ENV_LABELS = { med: "Mediterranean", ne: "North Europe" };
  const state = { filters: new URLSearchParams(), page: 1, optionsLoaded: false };

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  };

  async function api(url) {
    const res = await fetch(url);
    if (res.status === 401) { window.location.href = "/login"; throw new Error("Not signed in"); }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      // 422 from FastAPI has a list of problems; other errors have one message
      const detail = Array.isArray(body.detail)
        ? body.detail.map((d) => d.msg.replace(/^Value error, /, "")).join("; ")
        : body.detail;
      throw new Error(detail || `Request failed (${res.status})`);
    }
    return res.json();
  }

  // Only the filters that have a value; the API treats a missing one as "no filter"
  function readFilters() {
    const params = new URLSearchParams();
    for (const [key, value] of new FormData(els.form)) {
      const v = String(value).trim();
      if (v) params.set(key, v);
    }
    return params;
  }

  function fillOptions(o) {
    const option = (value, label) => { const n = el("option", null, label); n.value = value; return n; };
    els.env.append(...o.env_types.map((v) => option(v, ENV_LABELS[v] || v)));
    els.trait.append(...o.traits.map((t) => option(t, t)));
    els.locations.replaceChildren(...o.locations.map((l) => option(l, l)));
    for (const input of [els.yearFrom, els.yearTo]) {
      if (o.year_min != null) input.min = o.year_min;
      if (o.year_max != null) input.max = o.year_max;
    }
    els.yearFrom.placeholder = o.year_min ?? "";
    els.yearTo.placeholder = o.year_max ?? "";
    state.optionsLoaded = true;
  }

  function freezeColumns(table, count) {
    const headCells = [...table.tHead.rows[0].cells].slice(0, count);
    const widths = headCells.map((c) => c.getBoundingClientRect().width); // measure first, then change
    const maxFrozen = table.parentElement.clientWidth * 0.6;

    let left = 0;
    let frozen = 0;
    for (const width of widths) {
      if (left + width > maxFrozen) break;
      for (const row of table.rows) {
        const cell = row.cells[frozen];
        if (!cell || cell.colSpan > 1) continue; // skip the "No plots match" row
        cell.classList.add("frozen");
        cell.style.left = `${left}px`;
      }
      left += width;
      frozen += 1;
    }
    if (frozen) {
      for (const row of table.rows) row.cells[frozen - 1]?.classList.add("frozen-last");
    }
  }

  function renderTable(data) {
    const wrap = el("div", "table-wrap table-wrap-tall");
    const table = el("table", "table table-frozen");
    const head = el("tr");
    data.columns.forEach((c) => head.appendChild(el("th", null, c)));
    const thead = el("thead"); thead.appendChild(head);
    const tbody = el("tbody");
    if (!data.rows.length) {
      const td = el("td", "muted", "No plots match these filters.");
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
    freezeColumns(table, FROZEN_COLUMNS);
  }

  async function load() {
    const params = new URLSearchParams(state.filters);
    params.set("page", state.page);

    let data;
    try { data = await api(`/api/explorer?${params}`); }
    catch (err) { els.body.replaceChildren(el("div", "alert alert-destructive", err.message)); return; }

    if (!state.optionsLoaded) fillOptions(data.options);
    renderTable(data);

    els.pageInfo.textContent = `Page ${data.page}`;
    els.prev.disabled = data.page <= 1;
    els.next.disabled = !data.has_next;
    els.summary.textContent = state.filters.toString() ? "Filtered plots" : "All plots";

    const csv = new URLSearchParams(state.filters);
    csv.set("format", "csv");
    els.download.href = `/api/explorer?${csv}`;
  }

  els.form.addEventListener("submit", (e) => {
    e.preventDefault();
    state.filters = readFilters();
    state.page = 1;
    load();
  });
  els.reset.addEventListener("click", () => {
    els.form.reset();
    state.filters = new URLSearchParams();
    state.page = 1;
    load();
  });
  els.prev.addEventListener("click", () => { state.page -= 1; load(); });
  els.next.addEventListener("click", () => { state.page += 1; load(); });

  load();
})();