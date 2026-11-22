/* Authority dashboard: pending, approved, and rejected gate passes. */

const SLOT_LABEL = {
  morning: "Morning 06:00–09:30",
  evening: "Evening 16:30–19:30",
};

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function when(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

function show(id, on) {
  document.getElementById(id).classList.toggle("d-none", !on);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(data.error || "Request failed");
    error.status = res.status;
    throw error;
  }
  return data;
}

function passCard(gp, pending) {
  const slot = SLOT_LABEL[gp.entry_slot] || gp.entry_slot || "";
  const decision = gp.status === "PENDING"
    ? ""
    : `<div class="mt-2 small">${esc(gp.status === "APPROVED" ? "Approved" : "Rejected")} by ${esc(gp.decided_by_name || "—")}${gp.decided_at ? " · " + esc(when(gp.decided_at)) : ""}</div>${gp.decision_note ? `<div class="small">${esc(gp.decision_note)}</div>` : ""}`;
  const actions = pending
    ? `<textarea class="form-control form-control-sm mt-3 mb-2" rows="2" data-note-for="${esc(gp.id)}" placeholder="Note for the audit trail (optional)"></textarea>
       <div class="d-flex gap-2">
         <button class="btn btn-primary btn-sm flex-grow-1" type="button" data-action="approve" data-id="${esc(gp.id)}">APPROVE</button>
         <button class="btn btn-outline-danger btn-sm flex-grow-1" type="button" data-action="reject" data-id="${esc(gp.id)}">REJECT</button>
       </div>`
    : "";
  return `<article class="card pass-card p-3 border-0">
    <div class="d-flex justify-content-between align-items-start gap-2 mb-2">
      <div>
        <div class="meta">Gate pass</div>
        <div class="fw-semibold font-monospace">${esc(gp.id)}</div>
      </div>
      <span class="gp-status gp-${esc(String(gp.status || "").toLowerCase())}">${esc(gp.status)}</span>
    </div>
    <div class="meta">Booked by</div>
    <div>${esc(gp.booked_by)} · ${esc(gp.person_category)}</div>
    <div class="meta mt-2">Department / Hostel</div>
    <div>${esc(gp.department_or_hostel)}</div>
    <div class="meta mt-2">Purpose of booking</div>
    <div>${esc(gp.purpose_label || gp.purpose)}${gp.purpose_note ? " — " + esc(gp.purpose_note) : ""}</div>
    <div class="meta mt-2">Booking</div>
    <div class="font-monospace">${esc(gp.booking_id)}</div>
    <div class="small text-muted">${esc(gp.pickup)} → ${esc(gp.drop)}</div>
    <div class="meta mt-2">Truck details</div>
    <div>${esc(gp.truck_details)}</div>
    <div class="small">Truck number: ${esc(gp.truck_number)}</div>
    ${gp.entry_gate ? `<div class="small mt-1">${esc(gp.entry_gate)}${slot ? " · " + esc(slot) : ""}</div>` : ""}
    <div class="small text-muted mt-2">Requested ${esc(when(gp.created_at))}</div>
    ${decision}
    ${actions}
  </article>`;
}

function renderList(elementId, items, pending) {
  const box = document.getElementById(elementId);
  if (!items.length) {
    box.innerHTML = `<div class="text-muted small">None</div>`;
    return;
  }
  box.innerHTML = items.map((gp) => passCard(gp, pending)).join("");
}

async function loadQueue() {
  const data = await api("/api/gatepass/mine");
  document.getElementById("countPending").textContent = data.pending.length;
  document.getElementById("countApproved").textContent = data.approved.length;
  document.getElementById("countRejected").textContent = data.rejected.length;
  renderList("listPending", data.pending, true);
  renderList("listApproved", data.approved, false);
  renderList("listRejected", data.rejected, false);
  const err = document.getElementById("dashError");
  err.classList.add("d-none");
}

function showDashboard(account) {
  show("loginView", false);
  show("wrongDesk", false);
  show("dashboard", true);
  document.getElementById("logoutBtn").classList.remove("d-none");
  document.getElementById("whoami").textContent = account.display_name;
  document.getElementById("unitLine").textContent = account.id === "AUTH-GATE"
    ? "Every hostel and department. You can approve or reject any request."
    : `${account.unit_name} · you only see this unit's requests`;
  loadQueue().catch((error) => {
    const err = document.getElementById("dashError");
    err.textContent = error.message;
    err.classList.remove("d-none");
  });
}

async function decide(action, id, button) {
  const noteEl = document.querySelector(`[data-note-for="${CSS.escape(id)}"]`);
  const note = noteEl ? noteEl.value : "";
  button.disabled = true;
  try {
    await api(`/api/gatepass/${encodeURIComponent(id)}/${action}`, {
      method: "POST",
      body: JSON.stringify({ note }),
    });
    await loadQueue();
  } catch (error) {
    const err = document.getElementById("dashError");
    err.textContent = error.message;
    err.classList.remove("d-none");
    button.disabled = false;
  }
}

document.getElementById("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const errorBox = document.getElementById("loginError");
  errorBox.classList.add("d-none");
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: document.getElementById("username").value,
        password: document.getElementById("password").value,
      }),
    });
    document.getElementById("password").value = "";
    if (data.account.role === "SECURITY") {
      show("loginView", false);
      show("dashboard", false);
      show("wrongDesk", true);
      document.getElementById("logoutBtn").classList.remove("d-none");
      return;
    }
    showDashboard(data.account);
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove("d-none");
  }
});

document.getElementById("logoutBtn").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST", body: "{}" });
  document.getElementById("whoami").textContent = "";
  document.getElementById("logoutBtn").classList.add("d-none");
  show("dashboard", false);
  show("wrongDesk", false);
  show("loginView", true);
});

document.getElementById("refreshBtn").addEventListener("click", () => {
  loadQueue().catch((error) => {
    const err = document.getElementById("dashError");
    err.textContent = error.message;
    err.classList.remove("d-none");
  });
});

document.getElementById("dashboard").addEventListener("click", (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  decide(button.getAttribute("data-action"), button.getAttribute("data-id"), button);
});

api("/api/auth/me").then((data) => {
  if (!data.account) return;
  if (data.account.role === "SECURITY") {
    show("loginView", false);
    show("wrongDesk", true);
    document.getElementById("logoutBtn").classList.remove("d-none");
    document.getElementById("whoami").textContent = data.account.display_name;
    return;
  }
  showDashboard(data.account);
}).catch(() => {});

setInterval(() => {
  if (!document.getElementById("dashboard").classList.contains("d-none")) {
    loadQueue().catch(() => {});
  }
}, 10000);
