const API = "";
let state = {
  token: localStorage.getItem("pf_token") || null,
  user: null, agents: [], currentScreen: null, history: [],
  historyFilter: "all", notifUnread: 0, sendFee: 0, wdFee: 0,
};
const $ = (id) => document.getElementById(id);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function money(n) {
  return "KES " + Number(n || 0).toLocaleString("en-KE",
    { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function prettyDate(iso) {
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  const now = new Date();
  const opts = d.toDateString() === now.toDateString()
    ? { hour: "2-digit", minute: "2-digit" }
    : { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" };
  return d.toLocaleString("en-KE", opts);
}
function initials(name) {
  return (name || "?").trim().split(/\s+/).slice(0, 2)
    .map((w) => w[0]).join("").toUpperCase();
}
function digitsOnly(s) { return (s || "").replace(/\D/g, ""); }

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = msg;
  $("toastWrap").appendChild(el);
  setTimeout(() => {
    el.style.transition = "opacity .25s, transform .25s";
    el.style.opacity = "0";
    el.style.transform = "translateY(-10px)";
    setTimeout(() => el.remove(), 260);
  }, 2600);
}

async function api(path, { method = "GET", body = null } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  const res = await fetch(API + path, {
    method, headers, body: body ? JSON.stringify(body) : undefined,
  });
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (res.status === 401 && state.token) {
    localStorage.removeItem("pf_token");
    state.token = null; state.user = null;
    go("s-auth"); throw new Error(data.error || "Session expired.");
  }
  if (!res.ok) throw new Error(data.error || "Something went wrong.");
  return data;
}

const TABBED = new Set(["s-home", "s-history", "s-notifications", "s-profile"]);
const screenStack = [];
function go(id, { push = true } = {}) {
  const target = $(id);
  if (!target) return;
  const current = state.currentScreen;
  if (push && current && current !== id) screenStack.push(current);
  if (!push) screenStack.length = 0;
  $$(".screen").forEach((s) => s.classList.remove("active"));
  target.classList.add("active");
  target.scrollTop = 0;
  state.currentScreen = id;
  const showTabs = TABBED.has(id);
  $("tabbar").classList.toggle("hidden", !showTabs);
  if (showTabs) {
    $$("#tabbar button").forEach((b) =>
      b.classList.toggle("on", b.dataset.tab === id));
  }
  onScreenEnter(id);
}
function back() {
  const prev = screenStack.pop();
  if (prev) go(prev, { push: false });
  else go("s-home", { push: false });
}

let pinResolve = null;
let pinBuffer = "";
function askPin(title, sub) {
  return new Promise((resolve) => {
    pinResolve = resolve;
    pinBuffer = "";
    $("pinTitle").textContent = title || "Enter your PIN";
    $("pinSub").textContent = sub || "Confirm the transaction";
    updateDots();
    $("pinSheet").classList.add("open");
  });
}
function updateDots() {
  const dots = $$("#pinDots i");
  dots.forEach((d, i) => d.classList.toggle("on", i < pinBuffer.length));
}
function closePin(value) {
  $("pinSheet").classList.remove("open");
  $("pinDots").classList.remove("err");
  const r = pinResolve;
  pinResolve = null; pinBuffer = "";
  updateDots();
  if (r) r(value);
}
$("keypad")?.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-k]");
  if (!btn || !pinResolve) return;
  const k = btn.dataset.k;
  if (k === "cancel") return closePin(null);
  if (k === "del") { pinBuffer = pinBuffer.slice(0, -1); return updateDots(); }
  if (/^\d$/.test(k) && pinBuffer.length < 4) {
    pinBuffer += k;
    updateDots();
    if (pinBuffer.length === 4) {
      const value = pinBuffer;
      setTimeout(() => closePin(value), 140);
    }
  }
});

function showReceipt({ title, amount, lines = [], note = "" }) {
  const overlay = $("overlay");
  overlay.innerHTML = `
    <div class="receipt">
      <div class="tick">✓</div>
      <h3>${esc(title)}</h3>
      <p class="amt">${money(amount)}</p>
      <p>${esc(note)}</p>
      <div class="detail-rows" style="margin-top:18px;text-align:left">
        ${lines.map((l) => `<div class="row"><span>${esc(l[0])}</span><b>${esc(l[1])}</b></div>`).join("")}
      </div>
      <button class="btn primary" id="receiptClose">Done</button>
    </div>`;
  overlay.classList.add("open");
  $("receiptClose").onclick = () => overlay.classList.remove("open");
  overlay.onclick = (e) => { if (e.target === overlay) overlay.classList.remove("open"); };
}

async function afterLogin(payload) {
  state.token = payload.token;
  state.user = payload.user;
  localStorage.setItem("pf_token", payload.token);
  await loadAgents();
  renderUser();
  await Promise.all([loadTransactions(), loadNotifications()]);
  go("s-home", { push: false });
}
async function bootSession() {
  if (!state.token) return false;
  try {
    const { user } = await api("/api/me");
    state.user = user;
    await loadAgents();
    renderUser();
    await Promise.all([loadTransactions(), loadNotifications()]);
    return true;
  } catch (_) {
    state.token = null;
    localStorage.removeItem("pf_token");
    return false;
  }
}
function renderUser() {
  if (!state.user) return;
  const u = state.user;
  $("homeAvatar").textContent = initials(u.name);
  $("homeName").textContent = u.name.split(" ")[0];
  $("greeting").textContent = greetingText();
  $("homeBalance").textContent = money(u.balance);
  $("homePhone").textContent = "+254 " + u.phone.slice(1);
  $("profAvatar").textContent = initials(u.name);
  $("profName").textContent = u.name;
  $("profPhone").textContent = "+254 " + u.phone.slice(1);
  $("profBalance").textContent = money(u.balance);
  $("profSince").textContent = new Date(u.created_at).toLocaleDateString("en-KE",
    { month: "short", year: "numeric" });
  $("receivePhone").textContent = "+254 " + u.phone.slice(1);
  renderQR(u.phone);
}
function greetingText() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}
function renderQR(seed) {
  const box = $("qrBox");
  if (!box) return;
  box.innerHTML = "";
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  const rnd = () => { h = (h * 1103515245 + 12345) >>> 0; return h / 4294967295; };
  const N = 21;
  const grid = [];
  for (let y = 0; y < N; y++) {
    grid.push([]);
    for (let x = 0; x < N; x++) grid[y].push(rnd() > 0.52 ? 1 : 0);
  }
  const finder = (ox, oy) => {
    for (let y = 0; y < 7; y++) for (let x = 0; x < 7; x++) {
      const edge = x === 0 || y === 0 || x === 6 || y === 6;
      const core = x >= 2 && x <= 4 && y >= 2 && y <= 4;
      grid[oy + y][ox + x] = edge || core ? 1 : 0;
    }
  };
  finder(0, 0); finder(N - 7, 0); finder(0, N - 7);
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const i = document.createElement("i");
    if (!grid[y][x]) i.style.background = "transparent";
    box.appendChild(i);
  }
}

async function loadAgents() {
  const { agents } = await api("/api/agents");
  state.agents = agents;
  renderAgents("depAgents", "dep");
  renderAgents("wdAgents", "wd");
}
let selectedDepAgent = null;
let selectedWdAgent = null;
function renderAgents(containerId, mode) {
  const box = $(containerId);
  if (!box) return;
  box.innerHTML = state.agents.map((a) => {
    const icon = a.kind === "bank" ? "🏦" : a.kind === "atm" ? "🏧" : "🏪";
    return `<button class="agent" data-id="${a.id}">
      <span class="agent-icon">${icon}</span>
      <span class="agent-mid"><b>${esc(a.name)}</b><span>${esc(a.location)}</span></span>
    </button>`;
  }).join("");
  box.querySelectorAll(".agent").forEach((el) => {
    el.onclick = () => {
      box.querySelectorAll(".agent").forEach((x) => x.classList.remove("on"));
      el.classList.add("on");
      const id = Number(el.dataset.id);
      if (mode === "dep") selectedDepAgent = id;
      else selectedWdAgent = id;
    };
  });
}

function txVisual(t) {
  const isIn = t.type === "send_in" || t.type === "deposit";
  const sign = isIn ? "+" : "−";
  let title;
  if (t.type === "send_out") title = "Sent to " + (t.counterparty_name || "recipient");
  else if (t.type === "send_in") title = "Received from " + (t.counterparty_name || "sender");
  else if (t.type === "deposit") title = "Deposit · " + (t.counterparty_name || "Agent");
  else title = "Withdrawal · " + (t.counterparty_name || "Agent");
  return { isIn, sign, title };
}
function renderTxList(container, list) {
  if (!container) return;
  if (!list.length) {
    container.innerHTML = `<div class="empty">No transactions yet.<br/>Deposit cash with an agent to get started.</div>`;
    return;
  }
  container.innerHTML = list.map((t) => {
    const v = txVisual(t);
    return `<button class="tx" data-ref="${esc(t.ref)}">
      <span class="tx-icon ${v.isIn ? "in" : "out"}">${v.isIn ? "↓" : "↑"}</span>
      <span class="tx-mid">
        <b>${esc(v.title)}</b>
        <span>${prettyDate(t.created_at)}${t.note ? " · " + esc(t.note) : ""}</span>
      </span>
      <span class="tx-amt">
        <b class="${v.isIn ? "in" : "out"}">${v.sign}${money(t.amount).replace("KES ", "")}</b>
        <span>${t.ref.slice(0, 6)}</span>
      </span>
    </button>`;
  }).join("");
  container.querySelectorAll(".tx").forEach((el) => {
    el.onclick = () => openDetail(el.dataset.ref);
  });
}
async function loadTransactions(filter = "all") {
  const { transactions } = await api("/api/transactions?filter=" + filter);
  state.history = transactions;
  renderTxList($("homeTxList"), transactions.slice(0, 4));
  if (filter === state.historyFilter) renderTxList($("historyList"), transactions);
  $("profTxCount").textContent = transactions.length;
  const incoming = transactions.filter((t) => t.type === "send_in" || t.type === "deposit");
  renderTxList($("receiveList"), incoming.slice(0, 5));
  return transactions;
}
async function openDetail(ref) {
  try {
    const { transaction: t } = await api("/api/transactions/" + encodeURIComponent(ref));
    const v = txVisual(t);
    $("detailBody").innerHTML = `
      <div class="detail-hero">
        <span class="status">${esc(t.status.charAt(0).toUpperCase() + t.status.slice(1))}</span>
        <div class="amt">${v.sign} ${money(t.amount)}</div>
        <p class="muted" style="font-size:13px">${esc(v.title)}</p>
      </div>
      <div class="detail-rows">
        <div class="row"><span>Reference</span><b>${esc(t.ref)}</b></div>
        <div class="row"><span>Date</span><b>${prettyDate(t.created_at)}</b></div>
        <div class="row"><span>Type</span><b>${esc(t.type.replace("_", " "))}</b></div>
        ${t.counterparty_name ? `<div class="row"><span>Counterparty</span><b>${esc(t.counterparty_name)}</b></div>` : ""}
        ${t.counterparty_phone ? `<div class="row"><span>Phone</span><b>+254 ${esc(t.counterparty_phone.slice(1))}</b></div>` : ""}
        ${t.note ? `<div class="row"><span>Note</span><b>${esc(t.note)}</b></div>` : ""}
        <div class="row"><span>Fee</span><b>${money(t.fee)}</b></div>
        <div class="row"><span>Balance after</span><b>${money(t.balance_after)}</b></div>
      </div>
      <button class="btn ghost small" style="width:100%;margin-top:22px" id="reportBtn">Report an issue</button>`;
    $("reportBtn").onclick = () => { $("supRef").value = t.ref; go("s-support"); };
    go("s-detail");
  } catch (err) { toast(err.message, "err"); }
}

async function loadNotifications() {
  const { notifications, unread } = await api("/api/notifications");
  state.notifUnread = unread;
  $("bellBadge").classList.toggle("hidden", unread === 0);
  const box = $("notifList");
  if (!notifications.length) {
    box.innerHTML = `<div class="empty">No alerts yet.</div>`;
    return;
  }
  box.innerHTML = notifications.map((n) => `
    <div class="notif ${n.read ? "read" : ""}">
      <span class="notif-dot"></span>
      <div class="notif-mid">
        <b>${esc(n.title)}</b>
        <p>${esc(n.body || "")}</p>
        <time>${prettyDate(n.created_at)}</time>
      </div>
    </div>`).join("");
}

async function fetchFees(amount) {
  const r = await fetch(`/api/fees?amount=${encodeURIComponent(amount || 0)}`);
  return r.json();
}
function updateSendSummary() {
  const amt = parseFloat($("sendAmount").value || 0) || 0;
  $("sumAmount").textContent = money(amt);
  $("sumFee").textContent = money(state.sendFee);
  $("sumTotal").textContent = money(amt + state.sendFee);
}
$("sendAmount")?.addEventListener("input", async (e) => {
  const amt = parseFloat(e.target.value || 0) || 0;
  const f = await fetchFees(amt);
  state.sendFee = f.send_fee;
  $("sendFeeHint").textContent = "Transaction fee: " + money(state.sendFee);
  updateSendSummary();
});

let resolvedRecipient = null;
let lookupTimer = null;
$("sendPhone")?.addEventListener("input", () => {
  clearTimeout(lookupTimer);
  const raw = digitsOnly($("sendPhone").value);
  resolvedRecipient = null;
  const box = $("sendResolved");
  box.classList.add("hidden");
  if (raw.length < 9) return;
  lookupTimer = setTimeout(async () => {
    try {
      const { name, phone } = await api("/api/lookup?phone=" + encodeURIComponent(raw));
      resolvedRecipient = { name, phone };
      box.className = "resolved";
      box.textContent = "✓ " + name;
      box.classList.remove("hidden");
    } catch (err) {
      box.className = "resolved error";
      box.textContent = err.message;
      box.classList.remove("hidden");
    }
  }, 350);
});

$("btnSendContinue")?.addEventListener("click", async () => {
  const amount = parseFloat($("sendAmount").value || 0);
  const phone = digitsOnly($("sendPhone").value);
  const note = $("sendNote").value.trim();
  if (!amount || amount < 1) return toast("Enter an amount of at least KES 1.", "err");
  if (!resolvedRecipient) return toast("Enter a valid recipient number.", "err");
  const pin = await askPin("Confirm send", `Send ${money(amount)} to ${resolvedRecipient.name}`);
  if (!pin) return;
  try {
    const res = await api("/api/send", { method: "POST",
      body: { amount, phone, note, pin } });
    state.user = res.user;
    renderUser();
    $("sendAmount").value = ""; $("sendPhone").value = ""; $("sendNote").value = "";
    $("sendResolved").classList.add("hidden");
    state.sendFee = 0;
    showReceipt({
      title: "Money sent", amount: res.transaction.amount,
      note: `To ${res.transaction.counterparty_name}`,
      lines: [
        ["Reference", res.transaction.ref],
        ["Phone", "+254 " + res.transaction.counterparty_phone.slice(1)],
        ["Fee", money(res.transaction.fee)],
        ["New balance", money(res.user.balance)],
      ],
    });
    await Promise.all([loadTransactions(state.historyFilter), loadNotifications()]);
  } catch (err) { toast(err.message, "err"); }
});

$("btnDeposit")?.addEventListener("click", async () => {
  const amount = parseFloat($("depAmount").value || 0);
  if (!amount || amount < 1) return toast("Enter a deposit amount.", "err");
  if (!selectedDepAgent) return toast("Select an agent first.", "err");
  try {
    const res = await api("/api/deposit", { method: "POST",
      body: { amount, agent_id: selectedDepAgent } });
    state.user = res.user;
    renderUser();
    $("depAmount").value = "";
    selectedDepAgent = null;
    $$("#depAgents .agent").forEach((a) => a.classList.remove("on"));
    showReceipt({
      title: "Deposit successful", amount: res.transaction.amount,
      note: "Cash received",
      lines: [
        ["Reference", res.transaction.ref],
        ["Agent", res.transaction.counterparty_name],
        ["New balance", money(res.user.balance)],
      ],
    });
    await Promise.all([loadTransactions(state.historyFilter), loadNotifications()]);
  } catch (err) { toast(err.message, "err"); }
});

$("wdAmount")?.addEventListener("input", async (e) => {
  const amt = parseFloat(e.target.value || 0) || 0;
  const f = await fetchFees(amt);
  state.wdFee = f.withdraw_fee;
  $("wdFeeHint").textContent =
    `Withdrawal fee: ${money(state.wdFee)} · Balance: ${money(state.user?.balance || 0)}`;
});
$("btnWithdraw")?.addEventListener("click", async () => {
  const amount = parseFloat($("wdAmount").value || 0);
  if (!amount || amount < 1) return toast("Enter a withdrawal amount.", "err");
  if (!selectedWdAgent) return toast("Select an agent first.", "err");
  const pin = await askPin("Confirm withdrawal", `Withdraw ${money(amount)}`);
  if (!pin) return;
  try {
    const res = await api("/api/withdraw", { method: "POST",
      body: { amount, agent_id: selectedWdAgent, pin } });
    state.user = res.user;
    renderUser();
    $("wdAmount").value = "";
    selectedWdAgent = null;
    $$("#wdAgents .agent").forEach((a) => a.classList.remove("on"));
    showReceipt({
      title: "Withdrawal successful", amount: res.transaction.amount,
      note: "Cash dispensed",
      lines: [
        ["Reference", res.transaction.ref],
        ["Agent", res.transaction.counterparty_name],
        ["Fee", money(res.transaction.fee)],
        ["New balance", money(res.user.balance)],
      ],
    });
    await Promise.all([loadTransactions(state.historyFilter), loadNotifications()]);
  } catch (err) { toast(err.message, "err"); }
});

$("btnCopyPhone")?.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText("+254" + state.user.phone.slice(1));
    toast("Number copied", "ok");
  } catch (_) { toast("Copy failed — long press to select.", "err"); }
});
$("btnSimulate")?.addEventListener("click", async () => {
  try {
    const res = await api("/api/simulate-incoming", { method: "POST" });
    state.user = res.user;
    renderUser();
    showReceipt({
      title: "Money received", amount: res.transaction.amount,
      note: `From ${res.transaction.counterparty_name}`,
      lines: [["Reference", res.transaction.ref],
              ["New balance", money(res.user.balance)]],
    });
    await Promise.all([loadTransactions(state.historyFilter), loadNotifications()]);
  } catch (err) { toast(err.message, "err"); }
});

$("historyFilters")?.addEventListener("click", async (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  $$("#historyFilters .chip").forEach((c) => c.classList.remove("on"));
  chip.classList.add("on");
  state.historyFilter = chip.dataset.filter;
  try {
    const { transactions } = await api("/api/transactions?filter=" + state.historyFilter);
    renderTxList($("historyList"), transactions);
  } catch (err) { toast(err.message, "err"); }
});

$("btnMarkRead")?.addEventListener("click", async () => {
  await api("/api/notifications/read", { method: "POST" });
  $("bellBadge").classList.add("hidden");
  await loadNotifications();
});

async function loadTickets() {
  const { tickets } = await api("/api/support");
  const box = $("ticketList");
  if (!tickets.length) {
    box.innerHTML = `<div class="empty" style="padding:20px 0">No reports yet.</div>`;
    return;
  }
  box.innerHTML = tickets.map((t) => `
    <div class="notif">
      <span class="notif-dot"></span>
      <div class="notif-mid">
        <b>${esc(t.subject)}</b>
        <p>${esc(t.message)}</p>
        <time>${prettyDate(t.created_at)} · ${esc(t.status)}${t.ref ? " · " + esc(t.ref) : ""}</time>
      </div>
    </div>`).join("");
}
$("btnSubmitTicket")?.addEventListener("click", async () => {
  const subject = $("supSubject").value.trim();
  const message = $("supMessage").value.trim();
  const ref = $("supRef").value.trim();
  if (subject.length < 3) return toast("Add a short subject.", "err");
  if (message.length < 10) return toast("Describe the issue in more detail.", "err");
  try {
    await api("/api/support", { method: "POST", body: { subject, message, ref } });
    $("supSubject").value = ""; $("supMessage").value = ""; $("supRef").value = "";
    toast("Report submitted", "ok");
    await loadTickets();
  } catch (err) { toast(err.message, "err"); }
});

$("btnChangePin")?.addEventListener("click", async () => {
  const oldPin = await askPin("Current PIN", "Enter your existing 4-digit PIN");
  if (!oldPin) return;
  const newPin = await askPin("New PIN", "Choose a new 4-digit PIN");
  if (!newPin) return;
  try {
    await api("/api/change-pin", { method: "POST",
      body: { old_pin: oldPin, new_pin: newPin } });
    toast("PIN updated", "ok");
  } catch (err) { toast(err.message, "err"); }
});
$("btnLimits")?.addEventListener("click", () => {
  showReceipt({
    title: "Transaction limits", amount: 150000, note: "Daily limits",
    lines: [
      ["Minimum per transaction", "KES 1.00"],
      ["Maximum per transaction", "KES 150,000.00"],
      ["Send fee starts at", "Free up to KES 100"],
      ["Withdrawal fee starts at", "KES 11 (up to KES 100)"],
    ],
  });
});
$("btnLogout")?.addEventListener("click", async () => {
  try { await api("/api/logout", { method: "POST" }); } catch (_) {}
  localStorage.removeItem("pf_token");
  state.token = null; state.user = null;
  screenStack.length = 0;
  go("s-auth", { push: false });
});

$("btnLogin")?.addEventListener("click", async () => {
  const phone = $("loginPhone").value.trim();
  const pin = $("loginPin").value.trim();
  if (!phone || !pin) return toast("Enter phone number and PIN.", "err");
  try {
    const payload = await api("/api/login", { method: "POST",
      body: { phone: "+254" + digitsOnly(phone), pin } });
    await afterLogin(payload);
  } catch (err) { toast(err.message, "err"); }
});
$("loginPin")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("btnLogin").click();
});
$("btnRegister")?.addEventListener("click", async () => {
  const name = $("regName").value.trim();
  const phone = $("regPhone").value.trim();
  const pin = $("regPin").value.trim();
  const pin2 = $("regPin2").value.trim();
  if (!name || !phone || !pin || !pin2) return toast("Fill in all fields.", "err");
  if (pin !== pin2) return toast("PINs do not match.", "err");
  try {
    const payload = await api("/api/register", { method: "POST",
      body: { name, phone: "+254" + digitsOnly(phone), pin, pin2 } });
    await afterLogin(payload);
    toast("Welcome to PesaFlow!", "ok");
  } catch (err) { toast(err.message, "err"); }
});

document.addEventListener("click", (e) => {
  const navBtn = e.target.closest("[data-go]");
  if (navBtn) { e.preventDefault(); go(navBtn.dataset.go); return; }
  const backBtn = e.target.closest("[data-back]");
  if (backBtn) { e.preventDefault(); back(); }
});

async function onScreenEnter(id) {
  try {
    if (id === "s-history") {
      const { transactions } = await api("/api/transactions?filter=" + state.historyFilter);
      renderTxList($("historyList"), transactions);
    } else if (id === "s-notifications") {
      await loadNotifications();
    } else if (id === "s-support") {
      await loadTickets();
    } else if (id === "s-home") {
      renderUser();
      await Promise.all([loadTransactions(state.historyFilter), loadNotifications()]);
    } else if (id === "s-withdraw" && state.user) {
      $("wdFeeHint").textContent =
        `Withdrawal fee: KES 0.00 · Balance: ${money(state.user.balance)}`;
    }
  } catch (err) { toast(err.message, "err"); }
}

function tickClock() {
  const d = new Date();
  $("clock").textContent = d.toLocaleTimeString("en-KE",
    { hour: "2-digit", minute: "2-digit", hour12: false });
}
async function boot() {
  tickClock();
  setInterval(tickClock, 20000);
  go("s-splash", { push: false });
  await new Promise((r) => setTimeout(r, 900));
  const resumed = await bootSession();
  if (resumed) go("s-home", { push: false });
  else go("s-auth", { push: false });
}
boot();
