/* Security desk: a gate pass is valid for entry only when it is APPROVED. */

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
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

function row(label, value) {
  return `<div class="summary-row"><span class="summary-label">${esc(label)}</span><span class="summary-value">${esc(value || "—")}</span></div>`;
}

function renderResult(payload) {
  const gp = payload.gate_pass;
  const box = document.getElementById("result");
  box.classList.remove("d-none");
  const empty = document.getElementById("resultEmpty");
  if (empty) empty.classList.add("d-none");
  const bannerClass = payload.valid_for_entry ? "valid" : "invalid";
  box.innerHTML = `
    <div class="gp-banner ${bannerClass} mb-3">${esc(payload.verdict)}</div>
    <div class="card p-4 border-0">
      ${row("Gate pass ID", gp.id)}
      ${row("Truck number", gp.truck_number)}
      ${row("Booked by", `${gp.booked_by} · ${gp.person_category}`)}
      ${row("Department / Hostel", gp.department_or_hostel)}
      ${row("Purpose of booking", gp.purpose_note ? `${gp.purpose_label} — ${gp.purpose_note}` : gp.purpose_label)}
      ${row("Approval status", gp.approval_status)}
      ${row("Approving authority", gp.approving_authority)}
      ${gp.status === "REJECTED" ? row("Rejected by", gp.rejecting_authority) : ""}
      ${row("Booking ID", gp.booking_id)}
      ${row("Truck details", gp.truck_details)}
      ${row("Route", `${gp.pickup} → ${gp.drop}`)}
    </div>`;
}

function openDesk(account) {
  show("loginView", false);
  show("wrongDesk", false);
  show("verifyView", true);
  document.getElementById("logoutBtn").classList.remove("d-none");
  document.getElementById("whoami").textContent = account.display_name;
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
    if (data.account.role !== "SECURITY") {
      show("loginView", false);
      show("verifyView", false);
      show("wrongDesk", true);
      document.getElementById("logoutBtn").classList.remove("d-none");
      document.getElementById("whoami").textContent = data.account.display_name;
      return;
    }
    openDesk(data.account);
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove("d-none");
  }
});

document.getElementById("logoutBtn").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST", body: "{}" });
  document.getElementById("whoami").textContent = "";
  document.getElementById("logoutBtn").classList.add("d-none");
  show("verifyView", false);
  show("wrongDesk", false);
  show("loginView", true);
  document.getElementById("result").classList.add("d-none");
  const empty = document.getElementById("resultEmpty");
  if (empty) empty.classList.remove("d-none");
});

document.getElementById("verifyForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const errorBox = document.getElementById("verifyError");
  errorBox.classList.add("d-none");
  try {
    const data = await api("/api/gatepass/verify", {
      method: "POST",
      body: JSON.stringify({ gate_pass_id: document.getElementById("gatePassId").value.trim() }),
    });
    renderResult(data);
  } catch (error) {
    document.getElementById("result").classList.add("d-none");
    const empty = document.getElementById("resultEmpty");
    if (empty) empty.classList.remove("d-none");
    errorBox.textContent = error.message;
    errorBox.classList.remove("d-none");
  }
});

api("/api/auth/me").then((data) => {
  if (!data.account) return;
  document.getElementById("whoami").textContent = data.account.display_name;
  document.getElementById("logoutBtn").classList.remove("d-none");
  if (data.account.role === "SECURITY") openDesk(data.account);
  else {
    show("loginView", false);
    show("wrongDesk", true);
  }
}).catch(() => {});
