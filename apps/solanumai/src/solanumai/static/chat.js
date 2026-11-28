(() => {
  const root = document.getElementById("chat");
  if (!root) return;

  const $ = (id) => document.getElementById(id);
  const els = {
    sidebar: $("chat-sidebar"), backdrop: $("sidebar-backdrop"), toggle: $("sidebar-toggle"),
    list: $("conversations"), newBtn: $("new-conversation"),
    scroll: $("messages"), thread: $("thread"), empty: $("empty"),
    form: $("composer"), input: $("message"), send: $("send"),
    dialog: $("delete-dialog"), dialogName: $("delete-dialog-name"), toast: $("toast"),
  };
  const TOAST_MS = 3000;; // the bin turns into "Delete?" for this long
  const MAX_INPUT_HEIGHT = 200; // px, about 8 lines

  let conversationId = null;
  let busy = false;
  // Changes whenever another conversation is opened, so a late answer isn't
  // drawn into the wrong conversation
  let view = 0;

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  };

  function trashIcon() {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    for (const [k, v] of Object.entries({
      viewBox: "0 0 24 24", width: "14", height: "14", fill: "none",
      stroke: "currentColor", "stroke-width": "2", "aria-hidden": "true",
    })) svg.setAttribute(k, v);
    for (const d of ["M3 6h18", "M8 6V4h8v2", "M19 6l-1 14H6L5 6"]) {
      const p = document.createElementNS(ns, "path");
      p.setAttribute("d", d);
      svg.appendChild(p);
    }
    return svg;
  }

  async function api(path, options = {}) {
    const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
    if (res.status === 401) { window.location.href = "/login"; throw new Error("Not signed in"); }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${res.status})`);
    }
    return res.status === 204 ? null : res.json();
  }

  // ---------- messages ----------

  const scrollToBottom = () => { els.scroll.scrollTop = els.scroll.scrollHeight; };

  function renderTable(rows) {
    if (!rows || !rows.length) return null;
    const cols = Object.keys(rows[0]);
    const wrap = el("div", "table-wrap");
    const table = el("table", "table");
    const head = el("tr");
    cols.forEach((c) => head.appendChild(el("th", null, c)));
    const thead = el("thead"); thead.appendChild(head);
    const tbody = el("tbody");
    rows.forEach((r) => {
      const tr = el("tr");
      cols.forEach((c) => tr.appendChild(el("td", null, r[c] ?? "")));
      tbody.appendChild(tr);
    });
    table.append(thead, tbody);
    wrap.appendChild(table);
    return wrap;
  }

  function renderMessage(m) {
    els.empty.hidden = true;
    const row = el("div", `chat-msg chat-msg-${m.role}`);

    if (m.role === "user") {
      row.appendChild(el("div", "chat-bubble", m.content));
    } else {
      (m.displays || []).forEach((d) => row.appendChild(el("pre", "chat-display", d)));
      row.appendChild(el("div", "chat-answer", m.content));
      const t = renderTable(m.table);
      if (t) row.appendChild(t);
      if (m.trace && m.trace.length) {
        const d = el("details");
        d.appendChild(el("summary", "muted text-sm", "How this was answered"));
        d.appendChild(el("pre", null, JSON.stringify(m.trace, null, 2)));
        row.appendChild(d);
      }
    }
    els.thread.appendChild(row);
    scrollToBottom();
  }

  // A temporary answer bubble with dots and a seconds counter. Returns a function that
  // removes it; safe to call more than once.
  function showThinking() {
    const row = el("div", "chat-msg chat-msg-assistant chat-pending");
    const dots = el("span", "chat-dots");
    dots.append(el("span"), el("span"), el("span"));
    const label = el("span", "muted text-sm", "Thinking… 0 s");
    row.append(dots, label);
    els.thread.appendChild(row);
    scrollToBottom();

    const started = Date.now();
    const timer = setInterval(() => {
      label.textContent = `Thinking… ${Math.round((Date.now() - started) / 1000)} s`;
    }, 1000);
    return () => { clearInterval(timer); row.remove(); };
  }

  function clearThread() {
    els.thread.replaceChildren(els.empty);
    els.empty.hidden = false;
  }

  // ---------- sidebar ----------

  function groupLabel(isoDate) {
    const day = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const days = Math.round((day(new Date()) - day(new Date(isoDate))) / 86_400_000);
    if (days <= 0) return "Today";
    if (days === 1) return "Yesterday";
    if (days < 7) return "Previous 7 days";
    return "Older";
  }

    // Asks "Delete chat?" in a modal dialog. Resolves true only when Delete was clicked;
  // Cancel, Esc and a click outside the dialog all count as no.
  function confirmDelete(title) {
    els.dialogName.textContent = title;
    els.dialog.returnValue = "";
    els.dialog.showModal();
    return new Promise((resolve) => {
      els.dialog.addEventListener("close", () => resolve(els.dialog.returnValue === "delete"), { once: true });
    });
  }

  // A short notice in the corner, e.g. "Chat deleted"
  let toastTimer = null;
  function showToast(message, kind = "success") {
    els.toast.textContent = message;
    els.toast.className = `toast toast-${kind}`;
    els.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { els.toast.hidden = true; }, TOAST_MS);
  }

  function conversationItem(c) {
    const item = el("div", "chat-item" + (c.id === conversationId ? " active" : ""));

    const open = el("button", "chat-item-title", c.title);
    open.type = "button";
    open.title = c.title;
    open.addEventListener("click", () => { location.hash = `c=${c.id}`; });

    const del = el("button", "chat-item-delete");
    del.type = "button";
    del.title = "Delete";
    del.setAttribute("aria-label", `Delete "${c.title}"`);
    del.appendChild(trashIcon());

    // First click asks, second click (within DELETE_CONFIRM_MS) deletes
    del.addEventListener("click", async () => {
      if (!(await confirmDelete(c.title))) return;
      try {
        await api(`/api/chat/conversations/${c.id}`, { method: "DELETE" });
        if (c.id === conversationId) {
          if (location.hash) location.hash = ""; // goes to a new chat (see route)
          else startNew();
        }
        await loadConversations();
        showToast("Chat deleted");
      } catch (err) {
        showToast(`Could not delete the chat: ${err.message}`, "error");
      }
    });

    item.append(open, del);
    return item;
  }

  async function loadConversations() {
    const items = await api("/api/chat/conversations"); // newest first
    const nodes = [];
    let lastGroup = null;
    for (const c of items) {
      const group = groupLabel(c.updated_at);
      if (group !== lastGroup) { nodes.push(el("div", "chat-group", group)); lastGroup = group; }
      nodes.push(conversationItem(c));
    }
    if (!items.length) nodes.push(el("p", "muted text-sm chat-history-empty", "No chats yet."));
    els.list.replaceChildren(...nodes);
  }

  function setSidebar(open) {
    els.sidebar.classList.toggle("open", open);
    els.backdrop.hidden = !open;
  }

  // ---------- conversations and the address bar (#c=<id>) ----------

  function startNew() {
    view += 1;
    conversationId = null;
    clearThread();
    els.input.focus();
    loadConversations().catch(() => {});
  }

  async function openConversation(id) {
    view += 1;
    const conv = await api(`/api/chat/conversations/${id}`);
    conversationId = conv.id;
    clearThread();
    conv.messages.forEach(renderMessage);
    setSidebar(false);
    loadConversations().catch(() => {});
  }

  async function route() {
    const match = location.hash.match(/^#c=([0-9a-f-]{36})$/i);
    if (!match) { startNew(); return; }
    try {
      await openConversation(match[1]);
    } catch {
      history.replaceState(null, "", location.pathname); // deleted or not ours: start fresh
      startNew();
    }
  }

  // ---------- sending ----------

  function autoGrow() {
    els.input.style.height = "auto";
    els.input.style.height = `${Math.min(els.input.scrollHeight, MAX_INPUT_HEIGHT)}px`;
  }

  async function send(rawText) {
    const text = rawText.trim();
    if (!text || busy) return;
    busy = true;
    els.send.disabled = true;
    const sentFrom = view;

    renderMessage({ role: "user", content: text });
    els.input.value = "";
    autoGrow();
    const stopThinking = showThinking();

    try {
      const res = await api("/api/chat", {
        method: "POST",
        body: JSON.stringify({ conversation_id: conversationId, message: text }),
      });
      if (sentFrom === view) {
        stopThinking();
        conversationId = res.conversation_id;
        // replaceState doesn't fire hashchange, so the conversation isn't reloaded
        history.replaceState(null, "", `#c=${res.conversation_id}`);
        renderMessage(res.message);
      }
      loadConversations().catch(() => {});
    } catch (err) {
      if (sentFrom === view) {
        stopThinking();
        renderMessage({ role: "assistant", content: `Something went wrong: ${err.message}` });
      }
    } finally {
      stopThinking();
      busy = false;
      els.send.disabled = false;
      els.input.focus();
    }
  }


  els.form.addEventListener("submit", (e) => { e.preventDefault(); send(els.input.value); });
  els.input.addEventListener("input", autoGrow);
  // Enter sends, Shift+Enter adds a new line (not while an input method is composing text)
  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); els.form.requestSubmit(); }
  });
  root.querySelectorAll("[data-example]").forEach((b) => b.addEventListener("click", () => send(b.textContent)));
  els.newBtn.addEventListener("click", () => {
    if (location.hash) location.hash = ""; else startNew();
    setSidebar(false);
  });
  els.toggle.addEventListener("click", () => setSidebar(true));
  els.backdrop.addEventListener("click", () => setSidebar(false));
  els.dialog.addEventListener("click", (e) => { if (e.target === els.dialog) els.dialog.close("cancel"); });
  window.addEventListener("hashchange", route);

  route();
})();