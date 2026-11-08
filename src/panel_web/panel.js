// Chatty's remote panel. Talks only to the Pi it came from (see src/panel.py).
"use strict";

const $ = (id) => document.getElementById(id);
const POLL_MS = 5000, FACE_MS = 15000;
let loggedIn = false, faceUrl = null, faceBusy = false, lastFace = 0;

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}

function toast(text, bad) {
  const t = $("toast");
  t.textContent = text;
  t.classList.toggle("bad", !!bad);
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 3500);
}

async function post(path, body) {
  const r = await fetch(path, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Chatty-Panel": "1" },
    body: JSON.stringify(body),
  });
  let data = {};
  try { data = await r.json(); } catch (e) { /* empty */ }
  if (r.status === 401) showLogin();
  return { ok: r.ok && data.ok !== false, data };
}

async function act(body, btn) {
  if (btn) btn.disabled = true;
  try {
    const { ok, data } = await post("/api/do", body);
    if (data.message) toast(data.message, !ok);
    setTimeout(refresh, 700);
    if (body.action === "face" || body.action === "note" || body.action === "light") setTimeout(loadFace, 1200);
  } catch (e) {
    toast("Can't reach Chatty right now", true);
  } finally {
    if (btn) setTimeout(() => (btn.disabled = false), 600);
  }
}

// ----- login -----
function showLogin(hint) {
  loggedIn = false;
  $("panel").hidden = true;
  $("login").hidden = false;
  $("mode").textContent = "Locked";
  if (hint) $("login-hint").textContent = hint;
  $("passcode").focus();
}

$("login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  $("login-msg").textContent = "";
  try {
    const { ok, data } = await post("/api/login", { passcode: $("passcode").value });
    if (!ok) { $("login-msg").textContent = data.message || "That didn't work"; return; }
    $("passcode").value = "";
    $("login").hidden = true;
    refresh();
    loadFace();
  } catch (e) {
    $("login-msg").textContent = "Can't reach Chatty right now";
  }
});

$("logout").addEventListener("click", async () => {
  await post("/api/logout", {});
  showLogin("Logged out. Come back any time.");
});

// ----- the picture of her screen -----
async function loadFace() {
  if (!loggedIn || faceBusy || document.hidden) return;
  faceBusy = true;
  try {
    const r = await fetch("/api/face.png?t=" + Date.now(), { credentials: "same-origin" });
    if (r.status === 401) return showLogin();
    if (!r.ok) { $("face-empty").textContent = "No picture (is her face running?)"; return; }
    const blob = await r.blob();
    if (faceUrl) URL.revokeObjectURL(faceUrl);
    faceUrl = URL.createObjectURL(blob);
    $("face").src = faceUrl;
    $("face-empty").hidden = true;
    lastFace = Date.now();
  } catch (e) { /* try again later */ }
  finally { faceBusy = false; }
}
$("face-wrap").addEventListener("click", loadFace);
$("refresh-face").addEventListener("click", loadFace);

// ----- status -----
const ago = (ts, now) => {
  const s = Math.max(0, Math.round(now - ts));
  if (s < 60) return "just now";
  if (s < 3600) return Math.round(s / 60) + " min ago";
  if (s < 86400) return Math.round(s / 3600) + " h ago";
  return Math.round(s / 86400) + " d ago";
};
const clock = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

function fill(list, items) {
  list.replaceChildren(...items);
}

function row(name, value, dotClass) {
  const li = el("li");
  const n = el("span", "name");
  if (dotClass !== undefined) n.append(el("span", "dot " + dotClass));
  n.append(el("span", null, name));
  li.append(n, el("span", "muted small", value));
  return li;
}

function tile(label, value, level) {
  const t = el("div", "tile" + (level ? " " + level : ""));
  t.append(el("b", null, value), el("span", null, label));
  return t;
}

const ACTIVITY = { "doodle:spiro": "She's drawing a spirograph.", "doodle:stars": "She's drawing a constellation.",
  "doodle:rain": "Code rain is falling on her screen.", "doodle:portrait": "She's painting a self-portrait.",
  trickster: "She's hosting Who's the Trickster? (the nodes are doing chores; one of them is pranking).",
  game: "A tic-tac-toe game is on her screen.", ponder: "She's wondering about another node." };

function render(s) {
  const now = s.now, v = s.voice || {}, face = s.face || {};
  const mode = $("mode");
  mode.textContent = s.mode_text + (v.hush ? " (answering quietly)" : "");
  mode.className = "mode" + (!s.voice_ok ? " bad" : s.mode === "resting" ? " rest" : "");
  $("night").hidden = !v.night;
  $("confirm").hidden = !(s.voice_ok && s.mode === "confirm");

  // her screen
  const act = face.activity || "";
  $("activity").textContent = ACTIVITY[act] || (act.startsWith("chess:") ? "She's playing chess" +
    (act.length > 6 ? " with " + act.slice(6) : "") + "." : "");
  fill($("notices"), (face.notices || []).map((t) => el("li", null, t)));
  const myst = face.mystery;
  $("mystery").hidden = !myst;
  if (myst) {
    $("mystery-thinks").textContent = myst.trickster
      ? "It was " + myst.trickster + "! " + (myst.accused === myst.trickster ? "Mystery solved." : "The trickster got away.")
      : myst.you ? "Your vote: " + myst.you + ". " + myst.thinks : "Chatty's notebook: " + myst.thinks;
    fill($("mystery-clues"), (myst.clues || []).map((c) => el("li", null, c.what + " (near: " + c.near.join(", ") + ")")));
  }

  // what was said
  const lines = (v.lines || []).map((l) => {
    const li = el("li", l.who === "you" ? "you" : "chatty", l.text);
    li.prepend(el("time", null, (l.who === "you" ? "You" : "Chatty") + " · " + clock(l.ts)));
    return li;
  });
  if (!lines.length) lines.push(el("li", "chatty muted",
    v.log_mode && v.log_mode !== "full" ? "Her log is private, so only what you ask here shows up."
      : "Nothing said yet."));
  const box = $("lines"), atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  fill(box, lines);
  if (atEnd) box.scrollTop = box.scrollHeight;     // newest at the bottom, like a chat

  // timers
  const timers = (v.timers || []).map((t) => row(t.kind === "alarm" ? "Alarm " + t.label : t.label + " timer",
    t.kind === "alarm" ? "" : Math.max(0, Math.round((t.end - now) / 60)) + " min left", "ok"));
  fill($("timers"), timers.length ? timers : [el("li", "muted small", "No timers or alarms.")]);

  // health
  const h = s.health || {};
  const tiles = [];
  if (h.temp != null) tiles.push(tile("CPU temperature", Math.round(h.temp) + "°C",
    h.temp >= 80 ? "bad" : h.temp >= 70 ? "warn" : ""));
  if (h.throttled != null) tiles.push(tile("Power", h.throttled & 0x1 ? "Low now" : h.throttled ? "Dipped" : "Good",
    h.throttled & 0x1 ? "bad" : h.throttled ? "warn" : ""));
  if (h.disk_free_gb != null) tiles.push(tile("Disk free", h.disk_free_gb + " GB",
    h.disk_used_pct >= 90 ? "bad" : h.disk_used_pct >= 80 ? "warn" : ""));
  if (h.mem_mb != null) tiles.push(tile("Memory free", Math.round(h.mem_mb) + " MB", h.mem_mb < 200 ? "warn" : ""));
  if (h.ollama != null) tiles.push(tile("Local brain", h.ollama ? "Awake" : "Down", h.ollama ? "" : "bad"));
  if (h.uptime != null) tiles.push(tile("Up for", h.uptime > 86400 ? Math.floor(h.uptime / 86400) + " days"
    : Math.floor(h.uptime / 3600) + " h"));
  fill($("health"), tiles);
  const w = s.wifi;
  $("wifi").textContent = w ? "WiFi: " + [w.ssid || "", w.signal != null ? "signal " + w.signal + "%" : "",
    w.online === false ? "no internet" : "internet OK"].filter(Boolean).join(", ") : "";

  // nodes
  const nodes = (v.nodes || []).map((n) => row(n.title,
    n.online ? "online, seen " + ago(n.last_seen, now)
      : n.last_seen ? "quiet since " + clock(n.last_seen) : "quiet", n.online ? "ok" : "bad"));
  fill($("nodes"), nodes.length ? nodes : [el("li", "muted small",
    v.mesh_connected === false ? "Can't reach the message board (Mosquitto)." : "No nodes have checked in yet.")]);
  const r = v.rain;
  $("rain").textContent = v.raining ? "It's raining at the rain node right now." :
    r ? `Rain outlook: ${r.chance}% ${r.kind} around ${clock(r.starts)} (${r.summary}).` :
      v.nodes ? "No rain expected in the next few hours." : "";

  // services
  fill($("services"), Object.entries(s.services || {}).map(([name, st]) =>
    row(name, st, st === "active" ? "ok" : st === "inactive" || st === "unknown" ? "" : "bad")));

  $("updated").textContent = "Updated " + clock(now) + " · " + (s.host || "");
}

async function refresh() {
  if (document.hidden) return;
  try {
    const r = await fetch("/api/status", { credentials: "same-origin" });
    const data = await r.json();
    if (r.status === 401) return showLogin(data.has_key === false ?
      "No passcode is set yet. On the Pi run: python3 src/panel.py --new-passcode" : undefined);
    if (!loggedIn) { loggedIn = true; $("login").hidden = true; $("panel").hidden = false; loadFace(); }
    render(data);
    if (Date.now() - lastFace > FACE_MS) loadFace();
  } catch (e) {
    $("mode").textContent = "Can't reach Chatty right now";
    $("mode").className = "mode bad";
  }
}

// ----- buttons -----
document.addEventListener("click", (ev) => {
  const b = ev.target.closest("button");
  if (!b) return;
  if (b.dataset.act) act({ action: b.dataset.act }, b);
  else if (b.dataset.face) act({ action: "face", what: b.dataset.face }, b);
  else if (b.dataset.ask) act({ action: $("quick-quiet").checked ? "hush" : "ask", text: b.dataset.ask }, b);
  else if (b.dataset.talk) {
    const text = $("say-text").value.trim();
    if (!text) return toast("Type something first", true);
    act({ action: b.dataset.talk, text }, b);
    $("say-text").value = "";
  } else if (b.dataset.restart) {
    const what = b.dataset.restart === "voice" ? "her voice (she'll be quiet for about half a minute)" : "her face";
    if (confirm("Restart " + what + "?")) act({ action: "restart", service: b.dataset.restart }, b);
  }
});

$("say-text").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); document.querySelector('[data-talk="ask"]').click(); }
});
$("light").addEventListener("input", () => ($("light-val").textContent = $("light").value + "%"));
$("light-set").addEventListener("click", (ev) => act({ action: "light", level: $("light").value / 100 }, ev.target));
$("light-auto").addEventListener("click", (ev) => act({ action: "light", level: "auto" }, ev.target));
$("note-send").addEventListener("click", (ev) => {
  const text = $("note-text").value.trim();
  if (!text) return toast("Type a note first", true);
  act({ action: "note", text }, ev.target);
  $("note-text").value = "";
});

document.addEventListener("visibilitychange", () => { if (!document.hidden) { refresh(); loadFace(); } });
setInterval(refresh, POLL_MS);
refresh();
