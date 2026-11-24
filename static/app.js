// Vanilla JS, no build step. All user text goes through textContent (never innerHTML).
const $ = (id) => document.getElementById(id);
const state = { customers: [], customerId: null, sessions: {}, seen: 0, filter: "", selected: null };

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) el.append(kid instanceof Node ? kid : document.createTextNode(kid ?? ""));
  return el;
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `Request failed (${r.status})`);
  return body;
}
const post = (path, data) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

const PROMPTS = {
  "C-1001": ["My ceramic pour-over set arrived cracked", "The walnut desk arrived damaged"],
  "C-1002": ["My earbuds are late, still waiting", "Where is my earbuds order?", "Something I ordered arrived broken"],
  "C-1003": ["My duvet cover arrived damaged"],
  "C-1004": ["My desk lamp arrived broken", "The skillet is broken", "I will call my lawyer about this"],
};
const fmt = (n) => `$${Number(n).toFixed(2)}`;
const ago = (iso) => {
  const d = (Date.now() - new Date(iso)) / 86400000;
  return d < 1 ? "today" : `${Math.round(d)}d ago`;
};

// ------------------------------------------------------------------ tabs
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
function showView(name) {
  for (const v of ["customer", "desk"]) {
    $("view-" + v).hidden = v !== name;
    $("tab-" + v).setAttribute("aria-selected", String(v === name));
  }
  if (name === "desk") loadTickets();
}

// -------------------------------------------------------------- customer
async function init() {
  const [customers, graph, status] = await Promise.all([api("/api/customers"), api("/api/graph"), api("/api/status")]);
  state.customers = customers;
  $("engine").replaceChildren("understanding: ", h("b", {}, status.llm), status.model ? ` · ${status.model}` : "");
  const nodes = graph.nodes.filter((n) => !n.startsWith("__"));
  $("graph").replaceChildren(...nodes.map((n) => h("span", { class: "chip", "data-node": n }, n)));

  const sel = $("customer-select");
  sel.replaceChildren(...customers.map((c) => h("option", { value: c.id }, `${c.name} · ${c.tier}`)));
  sel.addEventListener("change", () => switchCustomer(sel.value));
  $("new-convo").addEventListener("click", () => { delete state.sessions[state.customerId]; renderTranscript([]); clearWorkings(); });
  $("composer").addEventListener("submit", onSend);
  $("input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("composer").requestSubmit(); } });
  switchCustomer(customers[0].id);
  refreshQueueCount();
  setInterval(pollMessages, 4000);
  setInterval(() => { refreshQueueCount(); if (!$("view-desk").hidden) loadTickets(false); }, 5000);
}

function switchCustomer(id) {
  state.customerId = id;
  const c = state.customers.find((x) => x.id === id);
  $("orders").replaceChildren(...c.orders.map((o) =>
    h("span", { class: "order" }, h("b", {}, o.id), " ", o.item, " ", fmt(o.amount), h("span", { class: "st" }, o.status.replace("_", " ")))));
  $("prompts").replaceChildren(...(PROMPTS[id] || []).map((p) =>
    h("button", { type: "button", onclick: () => { $("input").value = p; $("input").focus(); } }, p)));
  clearWorkings();
  const sid = state.sessions[id];
  if (sid) api(`/api/sessions/${sid}/messages`).then(renderTranscript); else renderTranscript([]);
}

const ROLE = { customer: "You", agent: "Agent", human: "Team member" };
function renderTranscript(messages) {
  state.seen = messages.length;
  const list = $("transcript");
  list.replaceChildren(...(messages.length ? messages.map((m) => line(m.role, m.text)) :
    [h("li", { class: "empty big" }, "Say what went wrong. The agent will look up your order, decide, and act.")]));
  list.scrollTop = list.scrollHeight;
}
const line = (role, text, extra = "") =>
  h("li", { class: `line ${role} ${extra}` }, h("span", { class: "role" }, ROLE[role]), h("span", { class: "text" }, text));

async function onSend(e) {
  e.preventDefault();
  const input = $("input"), message = input.value.trim();
  if (!message) return;
  input.value = "";
  $("send").disabled = true;
  const list = $("transcript");
  list.querySelector(".empty")?.remove();
  list.append(line("customer", message), line("agent", "Looking into it…", "pending"));
  list.scrollTop = list.scrollHeight;
  clearWorkings(true);
  try {
    const res = await post("/api/chat", { customer_id: state.customerId, session_id: state.sessions[state.customerId], message });
    state.sessions[state.customerId] = res.session_id;
    list.querySelector(".pending")?.remove();
    list.append(line("agent", res.reply));
    state.seen = (await api(`/api/sessions/${res.session_id}/messages`)).length;
    showTrace(res.trace);
    showTicket(res.ticket);
    refreshQueueCount();
  } catch (err) {
    list.querySelector(".pending")?.remove();
    list.append(line("agent", `Something went wrong: ${err.message}`));
  } finally {
    $("send").disabled = false;
    list.scrollTop = list.scrollHeight;
    input.focus();
  }
}

// A human may reply from the staff desk while the customer is on this page.
async function pollMessages() {
  const sid = state.sessions[state.customerId];
  if (!sid || $("view-customer").hidden) return;
  const msgs = await api(`/api/sessions/${sid}/messages`).catch(() => null);
  if (msgs && msgs.length > state.seen) { renderTranscript(msgs); }
}

function clearWorkings(running = false) {
  document.querySelectorAll(".chip").forEach((c) => c.classList.remove("on", "esc", "ok"));
  $("trace").replaceChildren(h("li", { class: "empty" }, running ? "Running…" : "Send a message to watch the agent work."));
  $("ticket-card").hidden = true;
}

function showTrace(trace) {
  const ran = new Set(trace.map((t) => t.node));
  document.querySelectorAll(".chip").forEach((c) => {
    const n = c.dataset.node;
    c.classList.toggle("on", ran.has(n));
    c.classList.toggle("esc", n === "escalate" && ran.has(n));
    c.classList.toggle("ok", n === "resolve_ticket" && ran.has(n));
  });
  $("trace").replaceChildren(...trace.map((t, i) => {
    const li = h("li", { class: "fresh" }, h("span", { class: "node" }, t.node), h("span", { class: "ms" }, `${t.ms} ms`), h("div", { class: "sum" }, t.summary));
    li.style.animationDelay = `${i * 70}ms`;
    return li;
  }));
}

function showTicket(t) {
  const card = $("ticket-card");
  if (!t) { card.hidden = true; return; }
  card.hidden = false;
  card.replaceChildren(
    h("div", { class: "ref" }, t.id, " ", h("span", { class: `pill ${t.status}` }, t.status)),
    h("dl", {},
      h("dt", {}, "CATEGORY"), h("dd", {}, t.category.replace("_", " ")),
      h("dt", {}, "ORDER"), h("dd", {}, t.order_id || "unknown"),
      h("dt", {}, "DECISION"), h("dd", {}, t.decision || "—"),
      h("dt", {}, "REASON"), h("dd", {}, t.reason || "—")));
}

// ------------------------------------------------------------ staff desk
document.querySelectorAll("#filters button").forEach((b) => b.addEventListener("click", () => {
  state.filter = b.dataset.status;
  document.querySelectorAll("#filters button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  loadTickets();
}));

async function refreshQueueCount() {
  const esc = await api("/api/tickets?status=escalated").catch(() => []);
  const badge = $("queue-count");
  badge.hidden = esc.length === 0;
  badge.textContent = esc.length;
}

async function loadTickets(keepDetail = true) {
  const rows = await api("/api/tickets" + (state.filter ? `?status=${state.filter}` : ""));
  $("ticket-list").replaceChildren(...(rows.length ? rows.map((t) =>
    h("li", { class: t.id === state.selected ? "sel" : "", tabindex: "0", onclick: () => openTicket(t.id), onkeydown: (e) => { if (e.key === "Enter") openTicket(t.id); } },
      h("div", { class: "row" }, h("span", { class: "ref" }, t.id), h("span", { class: `pill ${t.status}` }, t.status)),
      h("div", { class: "meta" }, `${t.customer_name} · ${t.category.replace("_", " ")} · ${ago(t.created_at)}`))) :
    [h("li", { class: "empty" }, "No tickets here yet.")]));
  if (state.selected && keepDetail && !document.activeElement?.closest?.(".resolve")) openTicket(state.selected, true);
}

async function openTicket(id, quiet = false) {
  state.selected = id;
  if (!quiet) document.querySelectorAll("#ticket-list li").forEach((li) => li.classList.toggle("sel", li.querySelector(".ref")?.textContent === id));
  const t = await api(`/api/tickets/${id}`);
  const box = $("ticket-detail");
  const o = t.order;
  box.replaceChildren(
    h("h2", {}, h("small", {}, `Case file · opened ${ago(t.created_at)}`), t.summary.length > 80 ? t.category.replace("_", " ") : t.summary),
    h("dl", { class: "facts" },
      fact("Ticket", h("span", {}, t.id, " ", h("span", { class: `pill ${t.status}` }, t.status))),
      fact("Customer", `${t.customer.name} (${t.customer.tier})`),
      fact("Order", o ? `${o.id} · ${o.item} · ${fmt(o.amount)} · ${o.status.replace("_", " ")}` : "No order identified"),
      fact("Category", `${t.category.replace("_", " ")} · severity ${t.severity}`)),
    t.reason ? h("p", { class: "why" }, h("b", {}, t.status === "escalated" ? "Why the agent stopped" : "Agent's reasoning"), t.reason) : "",
    h("h3", {}, "Conversation"),
    h("ol", { class: "transcript", style: "overflow:visible" },
      ...(t.messages.length ? t.messages.map((m) => line(m.role, m.text)) : [h("li", { class: "empty" }, "No conversation is linked to this ticket.")])),
    t.status === "escalated" ? resolveForm(t) :
      t.resolution ? h("p", { class: "closed-note" }, `Closed: ${t.resolution}`) : "");
}
const fact = (k, v) => h("div", { class: "fact" }, h("dt", {}, k), h("dd", {}, v));

function resolveForm(t) {
  const outcome = h("select", { id: "r-outcome" },
    ...[["refund", "Refund"], ["replace", "Send replacement"], ["credit", "Account credit"], ["decline", "Decline"]].map(([v, l]) => h("option", { value: v }, l)));
  const amount = h("input", { id: "r-amount", type: "number", min: "0", step: "0.01", value: t.order ? t.order.amount : 0 });
  const note = h("textarea", { id: "r-note", placeholder: "Message to the customer (they see this in their conversation)" });
  const err = h("span", { class: "err" });
  const btn = h("button", { type: "button" }, "Resolve ticket");
  const sync = () => { amount.disabled = ["replace", "decline"].includes(outcome.value); };
  outcome.addEventListener("change", sync); sync();
  btn.addEventListener("click", async () => {
    err.textContent = "";
    if (!note.value.trim()) { err.textContent = "Add a note for the customer."; return; }
    btn.disabled = true;
    try {
      await post(`/api/tickets/${t.id}/resolve`, { outcome: outcome.value, amount: Number(amount.value) || 0, note: note.value.trim() });
      await loadTickets(); await openTicket(t.id); refreshQueueCount();
    } catch (e) { err.textContent = e.message; btn.disabled = false; }
  });
  return h("div", { class: "resolve" }, h("h3", {}, "Take it from here"),
    h("div", { class: "fields" },
      h("div", {}, h("label", { for: "r-outcome" }, "Outcome"), outcome),
      h("div", {}, h("label", { for: "r-amount" }, "Amount ($)"), amount),
      h("div", {}),
      note),
    h("div", { class: "actions" }, btn, err));
}

init().catch((e) => document.body.prepend(h("p", { style: "padding:20px;color:#d4401a" }, `Failed to start: ${e.message}`)));
