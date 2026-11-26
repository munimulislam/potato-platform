// Chat page: talks to the JSON API (/api/chat). All text goes in with textContent,
// never innerHTML, so nothing the model or a user writes can run as HTML or script.
(() => {
  const root = document.getElementById("chat");
  if (!root) return;

  const $ = (id) => document.getElementById(id);
  const els = {
    list: $("conversations"), messages: $("messages"), form: $("composer"),
    input: $("message"), send: $("send"), thinking: $("thinking"), newBtn: $("new-conversation"), empty: $("empty"),
  };
  let conversationId = null;

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = String(text);
    return n;
  };

  async function api(path, options = {}) {
    const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
    if (res.status === 401) { window.location.href = "/login"; throw new Error("Not signed in"); }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${res.status})`);
    }
    return res.status === 204 ? null : res.json();
  }

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
    const box = el("div", `msg msg-${m.role}`);
    box.appendChild(el("div", "msg-text", m.content));
    if (m.role === "assistant") {
      const t = renderTable(m.table);
      if (t) box.appendChild(t);
      if (m.trace && m.trace.length) {
        const d = el("details");
        d.appendChild(el("summary", "muted text-sm", "How this was answered"));
        d.appendChild(el("pre", null, JSON.stringify(m.trace, null, 2)));
        box.appendChild(d);
      }
    }
    els.messages.appendChild(box);
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  async function loadConversations() {
    const items = await api("/api/chat/conversations");
    els.list.replaceChildren(...items.map((c) => {
      const b = el("button", "side-item" + (c.id === conversationId ? " active" : ""), c.title);
      b.type = "button";
      b.title = c.title;
      b.addEventListener("click", () => openConversation(c.id));
      return b;
    }));
  }

  async function openConversation(id) {
    const conv = await api(`/api/chat/conversations/${id}`);
    conversationId = conv.id;
    els.messages.replaceChildren(els.empty);
    els.empty.hidden = conv.messages.length > 0;
    conv.messages.forEach(renderMessage);
    loadConversations();
  }

  function newConversation() {
    conversationId = null;
    els.messages.replaceChildren(els.empty);
    els.empty.hidden = false;
    els.input.focus();
    loadConversations();
  }

  els.form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = els.input.value.trim();
    if (!text) return;
    renderMessage({ role: "user", content: text });
    els.input.value = "";
    els.send.disabled = true;
    els.thinking.hidden = false;
    try {
      const res = await api("/api/chat", {
        method: "POST",
        body: JSON.stringify({ conversation_id: conversationId, message: text }),
      });
      conversationId = res.conversation_id;
      renderMessage(res.message);
      loadConversations();
    } catch (err) {
      renderMessage({ role: "assistant", content: `Something went wrong: ${err.message}` });
    } finally {
      els.send.disabled = false;
      els.thinking.hidden = true;
      els.input.focus();
    }
  });

  // Enter sends, Shift+Enter adds a new line
  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); els.form.requestSubmit(); }
  });
  els.newBtn.addEventListener("click", newConversation);

  loadConversations().catch(() => {});
})();