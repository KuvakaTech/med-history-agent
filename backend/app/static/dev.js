// Shared helpers for the dev harnesses under /dev.
// Dev-only, deliberately minimal: no framework, no build step, no error recovery beyond
// showing you what the server said. Not a reference implementation for frontend/.

const API = "/api/v1";

export const store = {
  get token() { return localStorage.getItem("dev_token") || ""; },
  set token(v) { v ? localStorage.setItem("dev_token", v) : localStorage.removeItem("dev_token"); },
  get patientId() { return localStorage.getItem("dev_patient_id") || ""; },
  set patientId(v) { v ? localStorage.setItem("dev_patient_id", v) : localStorage.removeItem("dev_patient_id"); },
  get patientName() { return localStorage.getItem("dev_patient_name") || ""; },
  set patientName(v) { v ? localStorage.setItem("dev_patient_name", v) : localStorage.removeItem("dev_patient_name"); },
  get sessionId() { return localStorage.getItem("dev_session_id") || ""; },
  set sessionId(v) { v ? localStorage.setItem("dev_session_id", v) : localStorage.removeItem("dev_session_id"); },
};

export const $ = (id) => document.getElementById(id);

export function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

/** fetch + auth header + JSON, throwing the server's own detail so failures are legible. */
export async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (store.token) headers["Authorization"] = `Bearer ${store.token}`;
  const resp = await fetch(`${API}${path}`, { ...options, headers });
  const text = await resp.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!resp.ok) {
    const detail = body && body.detail ? body.detail : text || resp.statusText;
    const err = new Error(`${resp.status} — ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
    err.status = resp.status;
    err.body = body;
    throw err;
  }
  return body;
}

export async function login(email, password) {
  const data = await api("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  store.token = data.access_token;
  return data;
}

export async function register(email, password, name) {
  const data = await api("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, name }),
  });
  store.token = data.access_token;
  return data;
}

/** Shared nav + auth bar. Every page calls this so the token is set in one place. */
export function mountChrome(active) {
  const pages = [
    ["index.html", "1 · Login"],
    ["patients.html", "2 · Patients & profile"],
    ["cabin_test.html", "3 · Live consult"],
    ["sessions.html", "4 · Sessions"],
    ["record.html", "5 · Record & override"],
  ];
  const nav = document.createElement("div");
  nav.id = "nav";
  nav.innerHTML =
    pages.map(([href, label]) =>
      href === active
        ? `<span class="navitem current">${label}</span>`
        : `<a class="navitem" href="${href}">${label}</a>`).join("") +
    `<span class="spacer"></span><span id="who"></span>`;
  document.body.prepend(nav);
  renderWho();
}

export function renderWho() {
  const who = $("who");
  if (!who) return;
  const bits = [];
  bits.push(store.token ? `<span class="ok">authenticated</span>` : `<span class="bad">no token</span>`);
  if (store.patientName) bits.push(`patient: <b>${esc(store.patientName)}</b>`);
  if (store.sessionId) bits.push(`session: <b>${esc(store.sessionId.slice(0, 8))}…</b>`);
  who.innerHTML = bits.join(" &nbsp;|&nbsp; ");
}

export function requireToken(statusEl) {
  if (store.token) return true;
  if (statusEl) statusEl.innerHTML = `<span class="bad">Not logged in — go to step 1.</span>`;
  return false;
}
