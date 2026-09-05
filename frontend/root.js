const authGateEl = document.getElementById("auth-gate");
const authFormEl = document.getElementById("auth-form");
const adminUsernameInputEl = document.getElementById("admin-username-input");
const adminPasswordInputEl = document.getElementById("admin-password-input");
const authErrorEl = document.getElementById("auth-error");
const rootAppEl = document.getElementById("root-app");
const adminDisplayNameEl = document.getElementById("admin-display-name");
const logoutButtonEl = document.getElementById("logout-button");
const changePasswordButtonEl = document.getElementById("change-password-button");
const modalOverlayEl = document.getElementById("modal-overlay");
const modalContentEl = document.getElementById("modal-content");

// Claves de localStorage propias (distintas de las de panel.js): ambas
// páginas viven en el mismo origen, así que si compartieran nombre de
// clave, tener /panel y /root abiertos en el mismo navegador pisaría una
// sesión con la otra.
const TOKEN_KEY = "root_admin_token";
const DISPLAY_NAME_KEY = "root_admin_display_name";

let dependencias = [];
let admins = [];

// --- Autenticación ---------------------------------------------------

function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

function setSession(token, displayName) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(DISPLAY_NAME_KEY, displayName);
}

function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(DISPLAY_NAME_KEY);
}

async function rootFetch(url, options = {}) {
  const headers = { ...(options.headers || {}), Authorization: `Bearer ${getToken()}` };
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401 || res.status === 403) {
    clearSession();
    showAuthGate("Tu sesión expiró o no tiene permisos de root. Inicia sesión de nuevo.");
    throw new Error("unauthorized");
  }
  return res;
}

function showAuthGate(message) {
  authGateEl.hidden = false;
  rootAppEl.hidden = true;
  if (message) {
    authErrorEl.textContent = message;
    authErrorEl.hidden = false;
  } else {
    authErrorEl.hidden = true;
  }
}

async function tryEnterApp() {
  try {
    await loadDashboard();
    await loadInstitution();
    await loadDependencias();
    await loadAdmins();
    await loadDocuments(); // depende de que dependencias ya esté cargado (nombres en la tabla)
    await loadFaqCandidates();
    adminDisplayNameEl.textContent = localStorage.getItem(DISPLAY_NAME_KEY) || "";
    authGateEl.hidden = true;
    rootAppEl.hidden = false;
  } catch {
    // rootFetch ya mostró el auth-gate si la sesión no era válida.
  }
}

authFormEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = adminUsernameInputEl.value.trim();
  const password = adminPasswordInputEl.value;
  if (!username || !password) return;

  const submitButton = authFormEl.querySelector("button[type=submit]");
  submitButton.disabled = true;
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      showAuthGate("Usuario o contraseña incorrectos.");
      return;
    }
    const data = await res.json();
    adminPasswordInputEl.value = "";
    if (data.role !== "root") {
      // La cuenta existe pero no es root: no dejamos esa sesión abierta.
      fetch("/api/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${data.token}` } }).catch(() => {});
      showAuthGate("Esta cuenta no tiene permisos de administración general (root).");
      return;
    }
    setSession(data.token, data.display_name);
    await tryEnterApp();
  } catch {
    showAuthGate("No se pudo conectar con el servidor, intenta de nuevo.");
  } finally {
    submitButton.disabled = false;
  }
});

logoutButtonEl.addEventListener("click", async () => {
  try {
    await rootFetch("/api/auth/logout", { method: "POST" });
  } catch {
    // ya se mostró el auth-gate si la sesión era inválida.
  }
  clearSession();
  showAuthGate();
});

// --- Pestañas ----------------------------------------------------------

document.querySelectorAll(".root-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".root-tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    document.querySelectorAll(".root-tab-panel").forEach((p) => (p.hidden = true));
    document.getElementById(`tab-${tab.dataset.tab}`).hidden = false;
  });
});

// --- Modal genérico ------------------------------------------------------

function openModal(html, { wide = false } = {}) {
  modalContentEl.className = wide ? "modal-content wide" : "modal-content";
  modalContentEl.innerHTML = html;
  modalOverlayEl.hidden = false;
  const cancelButton = modalContentEl.querySelector(".cancel-button");
  if (cancelButton) cancelButton.addEventListener("click", closeModal);
}

function closeModal() {
  modalOverlayEl.hidden = true;
  modalContentEl.innerHTML = "";
}

modalOverlayEl.addEventListener("click", (e) => {
  if (e.target === modalOverlayEl) closeModal();
});

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

async function errorDetail(res) {
  const body = await res.json().catch(() => ({}));
  if (Array.isArray(body.detail)) {
    return body.detail.map((d) => d.msg).join(" ") || "Ocurrió un error.";
  }
  return body.detail || "Ocurrió un error.";
}

// --- Dependencias --------------------------------------------------------

async function loadDependencias() {
  const res = await rootFetch("/api/root/dependencias");
  dependencias = await res.json();
  renderDependenciasTable();
}

function renderDependenciasTable() {
  const tbody = document.getElementById("dependencias-table-body");
  const emptyEl = document.getElementById("dependencias-empty");
  tbody.innerHTML = "";
  emptyEl.hidden = dependencias.length > 0;

  for (const dep of dependencias) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(dep.name)}</td>
      <td>${escapeHtml(dep.description)}</td>
      <td>
        <div class="row-actions">
          <button type="button" class="edit-button">Editar</button>
          <button type="button" class="danger delete-button">Eliminar</button>
        </div>
      </td>
    `;
    tr.querySelector(".edit-button").addEventListener("click", () => openDependenciaModal(dep));
    tr.querySelector(".delete-button").addEventListener("click", () => deleteDependencia(dep));
    tbody.appendChild(tr);
  }
}

function openDependenciaModal(dep) {
  const isEdit = Boolean(dep);
  openModal(`
    <h3>${isEdit ? "Editar dependencia" : "Nueva dependencia"}</h3>
    <form id="dependencia-form" class="modal-form">
      <label>Nombre
        <input id="dependencia-name-input" type="text" maxlength="200" required value="${isEdit ? escapeHtml(dep.name) : ""}" />
      </label>
      <label>Descripción (el chatbot la usa para decidir a quién redirigir)
        <textarea id="dependencia-description-input" maxlength="2000" required>${isEdit ? escapeHtml(dep.description) : ""}</textarea>
      </label>
      <p id="dependencia-form-error" class="modal-error" hidden></p>
      <div class="modal-actions">
        <button type="button" class="cancel-button">Cancelar</button>
        <button type="submit" class="primary-button">${isEdit ? "Guardar" : "Crear"}</button>
      </div>
    </form>
  `);

  document.getElementById("dependencia-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("dependencia-form-error");
    const name = document.getElementById("dependencia-name-input").value.trim();
    const description = document.getElementById("dependencia-description-input").value.trim();

    try {
      const url = isEdit ? `/api/root/dependencias/${dep.id}` : "/api/root/dependencias";
      const res = await rootFetch(url, {
        method: isEdit ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description }),
      });
      if (!res.ok) throw new Error(await errorDetail(res));
      closeModal();
      await loadDependencias();
      await loadAdmins(); // el nombre de dependencia mostrado junto a cada admin pudo cambiar
    } catch (err) {
      errorEl.textContent = err.message || "No se pudo guardar, intenta de nuevo.";
      errorEl.hidden = false;
    }
  });
}

async function deleteDependencia(dep) {
  if (!confirm(`¿Eliminar la dependencia "${dep.name}"?`)) return;
  try {
    const res = await rootFetch(`/api/root/dependencias/${dep.id}`, { method: "DELETE" });
    if (!res.ok) {
      alert(await errorDetail(res));
      return;
    }
    await loadDependencias();
  } catch {
    // rootFetch ya maneja el caso de sesión inválida.
  }
}

document.getElementById("new-dependencia-button").addEventListener("click", () => openDependenciaModal(null));

// --- Administradores -------------------------------------------------

const ROLE_LABELS = { root: "Root", general: "General", dependencia: "Dependencia" };

function dependenciaName(id) {
  const dep = dependencias.find((d) => d.id === id);
  return dep ? dep.name : "—";
}

async function loadAdmins() {
  const res = await rootFetch("/api/root/admins");
  admins = await res.json();
  renderAdminsTable();
}

function renderAdminsTable() {
  const tbody = document.getElementById("admins-table-body");
  const emptyEl = document.getElementById("admins-empty");
  tbody.innerHTML = "";
  emptyEl.hidden = admins.length > 0;

  for (const admin of admins) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(admin.username)}</td>
      <td>${escapeHtml(admin.display_name)}</td>
      <td>${ROLE_LABELS[admin.role] || admin.role}</td>
      <td>${admin.role === "dependencia" ? escapeHtml(dependenciaName(admin.dependencia_id)) : "—"}</td>
      <td><span class="status-badge ${admin.active ? "active" : "inactive"}">${admin.active ? "Activo" : "Inactivo"}</span></td>
      <td>
        <div class="row-actions">
          <button type="button" class="edit-button">Editar</button>
          <button type="button" class="password-button">Contraseña</button>
          <button type="button" class="danger toggle-active-button">${admin.active ? "Desactivar" : "Activar"}</button>
        </div>
      </td>
    `;
    tr.querySelector(".edit-button").addEventListener("click", () => openAdminModal(admin));
    tr.querySelector(".password-button").addEventListener("click", () => openSetPasswordModal(admin));
    tr.querySelector(".toggle-active-button").addEventListener("click", () => toggleAdminActive(admin));
    tbody.appendChild(tr);
  }
}

function dependenciaOptionsHtml(selectedId) {
  return dependencias
    .map((d) => `<option value="${d.id}" ${d.id === selectedId ? "selected" : ""}>${escapeHtml(d.name)}</option>`)
    .join("");
}

function openAdminModal(admin) {
  const isEdit = Boolean(admin);
  const role = isEdit ? admin.role : "general";
  openModal(`
    <h3>${isEdit ? "Editar administrador" : "Nuevo administrador"}</h3>
    <form id="admin-form" class="modal-form">
      ${
        isEdit
          ? ""
          : `<label>Correo electrónico (usuario)
              <input id="admin-username-field" type="email" maxlength="100" required />
            </label>
            <label>Contraseña
              <input id="admin-password-field" type="password" minlength="8" maxlength="200" required />
            </label>`
      }
      <label>Nombre para mostrar
        <input id="admin-display-name-field" type="text" maxlength="200" required value="${isEdit ? escapeHtml(admin.display_name) : ""}" />
      </label>
      <label>Rol
        <select id="admin-role-field">
          <option value="general" ${role === "general" ? "selected" : ""}>General</option>
          <option value="dependencia" ${role === "dependencia" ? "selected" : ""}>Dependencia</option>
          <option value="root" ${role === "root" ? "selected" : ""}>Root</option>
        </select>
      </label>
      <label id="admin-dependencia-field-wrapper" ${role === "dependencia" ? "" : "hidden"}>
        Dependencia
        <select id="admin-dependencia-field">${dependenciaOptionsHtml(isEdit ? admin.dependencia_id : null)}</select>
      </label>
      <p id="admin-form-error" class="modal-error" hidden></p>
      <div class="modal-actions">
        <button type="button" class="cancel-button">Cancelar</button>
        <button type="submit" class="primary-button">${isEdit ? "Guardar" : "Crear"}</button>
      </div>
    </form>
  `);

  const roleField = document.getElementById("admin-role-field");
  const dependenciaWrapper = document.getElementById("admin-dependencia-field-wrapper");
  roleField.addEventListener("change", () => {
    dependenciaWrapper.hidden = roleField.value !== "dependencia";
  });

  document.getElementById("admin-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("admin-form-error");
    const selectedRole = roleField.value;
    const dependenciaId =
      selectedRole === "dependencia" ? Number(document.getElementById("admin-dependencia-field").value) : null;
    const displayName = document.getElementById("admin-display-name-field").value.trim();

    try {
      let res;
      if (isEdit) {
        res = await rootFetch(`/api/root/admins/${admin.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ display_name: displayName, role: selectedRole, dependencia_id: dependenciaId }),
        });
      } else {
        const username = document.getElementById("admin-username-field").value.trim();
        const password = document.getElementById("admin-password-field").value;
        res = await rootFetch("/api/root/admins", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            username,
            password,
            display_name: displayName,
            role: selectedRole,
            dependencia_id: dependenciaId,
          }),
        });
      }
      if (!res.ok) throw new Error(await errorDetail(res));
      closeModal();
      await loadAdmins();
    } catch (err) {
      errorEl.textContent = err.message || "No se pudo guardar, intenta de nuevo.";
      errorEl.hidden = false;
    }
  });
}

function openSetPasswordModal(admin) {
  openModal(`
    <h3>Nueva contraseña para ${escapeHtml(admin.display_name)}</h3>
    <form id="set-password-form" class="modal-form">
      <label>Nueva contraseña
        <input id="set-password-field" type="password" minlength="8" maxlength="200" required />
      </label>
      <label>Confirmar contraseña
        <input id="set-password-confirm-field" type="password" minlength="8" maxlength="200" required />
      </label>
      <p id="set-password-error" class="modal-error" hidden></p>
      <div class="modal-actions">
        <button type="button" class="cancel-button">Cancelar</button>
        <button type="submit" class="primary-button">Guardar</button>
      </div>
    </form>
  `);

  document.getElementById("set-password-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("set-password-error");
    const password = document.getElementById("set-password-field").value;
    const confirmPassword = document.getElementById("set-password-confirm-field").value;
    if (password !== confirmPassword) {
      errorEl.textContent = "Las contraseñas no coinciden.";
      errorEl.hidden = false;
      return;
    }
    try {
      const res = await rootFetch(`/api/root/admins/${admin.id}/set-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!res.ok) throw new Error(await errorDetail(res));
      closeModal();
    } catch (err) {
      errorEl.textContent = err.message || "No se pudo guardar, intenta de nuevo.";
      errorEl.hidden = false;
    }
  });
}

async function toggleAdminActive(admin) {
  const nextActive = !admin.active;
  const verb = nextActive ? "activar" : "desactivar";
  if (!confirm(`¿Seguro que quieres ${verb} a "${admin.display_name}"?`)) return;
  try {
    const res = await rootFetch(`/api/root/admins/${admin.id}/set-active`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active: nextActive }),
    });
    if (!res.ok) {
      alert(await errorDetail(res));
      return;
    }
    await loadAdmins();
  } catch {
    // rootFetch ya maneja el caso de sesión inválida.
  }
}

document.getElementById("new-admin-button").addEventListener("click", () => openAdminModal(null));

// --- Cambiar mi propia contraseña -------------------------------------

changePasswordButtonEl.addEventListener("click", () => {
  openModal(`
    <h3>Cambiar mi contraseña</h3>
    <form id="change-password-form" class="modal-form">
      <label>Contraseña actual
        <input id="current-password-field" type="password" required />
      </label>
      <label>Nueva contraseña
        <input id="new-password-field" type="password" minlength="8" maxlength="200" required />
      </label>
      <label>Confirmar nueva contraseña
        <input id="new-password-confirm-field" type="password" minlength="8" maxlength="200" required />
      </label>
      <p id="change-password-error" class="modal-error" hidden></p>
      <div class="modal-actions">
        <button type="button" class="cancel-button">Cancelar</button>
        <button type="submit" class="primary-button">Cambiar</button>
      </div>
    </form>
  `);

  document.getElementById("change-password-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("change-password-error");
    const currentPassword = document.getElementById("current-password-field").value;
    const newPassword = document.getElementById("new-password-field").value;
    const confirmPassword = document.getElementById("new-password-confirm-field").value;
    if (newPassword !== confirmPassword) {
      errorEl.textContent = "Las contraseñas nuevas no coinciden.";
      errorEl.hidden = false;
      return;
    }
    try {
      const res = await rootFetch("/api/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      if (!res.ok) throw new Error(await errorDetail(res));
      closeModal();
      // Cambiar la contraseña invalida esta misma sesión: hay que volver a entrar.
      clearSession();
      showAuthGate("Contraseña actualizada. Inicia sesión de nuevo.");
    } catch (err) {
      errorEl.textContent = err.message || "No se pudo cambiar la contraseña.";
      errorEl.hidden = false;
    }
  });
});

// --- Dashboard -----------------------------------------------------------

let dashboardConversationsChart = null;
let dashboardGroqChart = null;

function formatMinutes(minutes) {
  if (minutes == null) return "—";
  if (minutes < 60) return `${minutes.toFixed(1)} min`;
  return `${(minutes / 60).toFixed(1)} h`;
}

function dashboardCardHtml(label, value) {
  return `
    <div class="dashboard-card">
      <span class="dashboard-card-value">${value}</span>
      <span class="dashboard-card-label">${escapeHtml(label)}</span>
    </div>
  `;
}

function dashboardCardsHtml(dashboard) {
  const c = dashboard.conversations;
  const d = dashboard.documents;
  const f = dashboard.faq;
  const cards = [
    ["Conversaciones escaladas", c.total_escalated],
    ["Resueltas", c.resolved],
    ["Pendientes ahora", c.pending_now],
    ["Escaladas en los últimos 7 días", c.last_7_days],
    ["Primera respuesta (promedio)", formatMinutes(c.avg_first_response_minutes)],
    ["Resolución (promedio)", formatMinutes(c.avg_resolution_minutes)],
    ["Documentos indexados", d.total],
    ["Tamaño total de documentos", formatSize(d.total_size_bytes)],
    ["FAQ pendientes por revisar", f.pending],
    ["FAQ aceptadas", f.accepted],
  ];

  if (dashboard.admin_team) {
    cards.push(["Dependencias activas", dashboard.admin_team.dependencias_count]);
    cards.push(["Administradores activos", dashboard.admin_team.admins_active]);
  }
  if (dashboard.performance) {
    cards.push([
      "Tiempo de respuesta del bot (promedio)",
      dashboard.performance.avg_total_ms != null ? `${dashboard.performance.avg_total_ms} ms` : "—",
    ]);
    cards.push([
      "Respuestas servidas desde caché",
      dashboard.performance.cache_hit_rate != null
        ? `${dashboard.performance.cache_hits} (${dashboard.performance.cache_hit_rate}%)`
        : dashboard.performance.cache_hits,
    ]);
    cards.push(["Llamadas a Groq (total)", dashboard.performance.groq_calls_total]);
    cards.push(["Llamadas a Groq (últimos 7 días)", dashboard.performance.groq_calls_last_7_days]);
    cards.push(["Llamadas a Groq fallidas", dashboard.performance.groq_calls_failed]);
  }

  return cards.map(([label, value]) => dashboardCardHtml(label, value)).join("");
}

function trendChartConfig(trend, label, color) {
  return {
    type: "line",
    data: {
      labels: trend.map((point) => point.date),
      datasets: [
        {
          label,
          data: trend.map((point) => point.count),
          borderColor: color,
          backgroundColor: `${color}26`,
          tension: 0.25,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
    },
  };
}

function renderDashboardCharts(dashboard) {
  const conversationsCanvas = document.getElementById("dashboard-conversations-chart");
  const groqCanvas = document.getElementById("dashboard-groq-chart");

  if (dashboardConversationsChart) dashboardConversationsChart.destroy();
  dashboardConversationsChart = new Chart(
    conversationsCanvas,
    trendChartConfig(dashboard.conversations.daily_trend || [], "Conversaciones", "#2563eb")
  );

  if (dashboardGroqChart) dashboardGroqChart.destroy();
  dashboardGroqChart = new Chart(
    groqCanvas,
    trendChartConfig(dashboard.performance ? dashboard.performance.groq_calls_daily_trend || [] : [], "Llamadas a Groq", "#16a34a")
  );
}

function renderDashboardByDependenciaTable(dashboard) {
  const tbody = document.getElementById("dashboard-by-dependencia-body");
  const emptyEl = document.getElementById("dashboard-by-dependencia-empty");
  const rows = dashboard.conversations.by_dependencia || [];
  tbody.innerHTML = "";
  emptyEl.hidden = rows.length > 0;
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${escapeHtml(row.name)}</td><td>${row.total}</td>`;
    tbody.appendChild(tr);
  }
}

function renderDashboardRecentDocumentsTable(dashboard) {
  const tbody = document.getElementById("dashboard-recent-documents-body");
  const emptyEl = document.getElementById("dashboard-recent-documents-empty");
  const rows = dashboard.documents.recent || [];
  tbody.innerHTML = "";
  emptyEl.hidden = rows.length > 0;
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${escapeHtml(row.filename)}</td><td>${formatTime(row.modified_at)}</td>`;
    tbody.appendChild(tr);
  }
}

async function loadDashboard() {
  const res = await rootFetch("/api/dashboard");
  const dashboard = await res.json();
  document.getElementById("dashboard-cards").innerHTML = dashboardCardsHtml(dashboard);
  renderDashboardCharts(dashboard);
  renderDashboardByDependenciaTable(dashboard);
  renderDashboardRecentDocumentsTable(dashboard);
}

// --- Institución -------------------------------------------------------

async function loadInstitution() {
  const res = await rootFetch("/api/institution");
  const data = await res.json();
  document.getElementById("institution-name-input").value = data.name || "";
  document.getElementById("institution-extra-input").value = data.extra_info || "";
  const preview = document.getElementById("institution-logo-preview");
  if (data.logo_url) {
    preview.src = data.logo_url;
    preview.hidden = false;
  } else {
    preview.hidden = true;
  }
}

document.getElementById("institution-logo-input").addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const preview = document.getElementById("institution-logo-preview");
  preview.src = URL.createObjectURL(file);
  preview.hidden = false;
});

document.getElementById("institution-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("institution-form-error");
  const successEl = document.getElementById("institution-form-success");
  errorEl.hidden = true;
  successEl.hidden = true;

  const name = document.getElementById("institution-name-input").value.trim();
  const extraInfo = document.getElementById("institution-extra-input").value.trim();
  const logoFile = document.getElementById("institution-logo-input").files[0];

  const formData = new FormData();
  formData.append("name", name);
  formData.append("extra_info", extraInfo);
  if (logoFile) formData.append("logo", logoFile);

  try {
    const res = await rootFetch("/api/root/institution", { method: "PUT", body: formData });
    if (!res.ok) throw new Error(await errorDetail(res));
    successEl.hidden = false;
    document.getElementById("institution-logo-input").value = "";
  } catch (err) {
    errorEl.textContent = err.message || "No se pudo guardar, intenta de nuevo.";
    errorEl.hidden = false;
  }
});

// --- Documentos ----------------------------------------------------------

let documents = [];

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function loadDocuments() {
  const res = await rootFetch("/api/root/documents");
  documents = await res.json();
  renderDocumentsTable();
}

function documentDependenciaOptionsHtml(selectedId) {
  const generalOption = `<option value="" ${selectedId == null ? "selected" : ""}>General / compartido</option>`;
  const depOptions = dependencias
    .map((d) => `<option value="${d.id}" ${d.id === selectedId ? "selected" : ""}>${escapeHtml(d.name)}</option>`)
    .join("");
  return generalOption + depOptions;
}

function renderDocumentsTable() {
  const tbody = document.getElementById("documents-table-body");
  const emptyEl = document.getElementById("documents-empty");
  const searchInput = document.getElementById("documents-search");
  tbody.innerHTML = "";

  const query = searchInput ? searchInput.value.trim().toLowerCase() : "";
  const filteredDocuments = query
    ? documents.filter((doc) => doc.filename.toLowerCase().includes(query))
    : documents;

  emptyEl.hidden = filteredDocuments.length > 0;
  emptyEl.textContent =
    documents.length === 0 ? "Todavía no hay documentos indexados." : "Ningún documento coincide con la búsqueda.";

  for (const doc of filteredDocuments) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(doc.filename)}</td>
      <td>${formatSize(doc.size_bytes)}</td>
      <td><select class="doc-dependencia-select">${documentDependenciaOptionsHtml(doc.dependencia_id)}</select></td>
      <td>
        <div class="row-actions">
          <button type="button" class="preview-button">Vista previa</button>
          <button type="button" class="danger delete-button">Eliminar</button>
        </div>
      </td>
    `;
    const select = tr.querySelector(".doc-dependencia-select");
    select.addEventListener("change", () => recategorizeDocument(doc, select));
    tr.querySelector(".preview-button").addEventListener("click", () => previewDocument(doc.filename, "/api/root/documents"));
    tr.querySelector(".delete-button").addEventListener("click", () => deleteDocument(doc));
    tbody.appendChild(tr);
  }
}

async function previewDocument(filename, basePath) {
  openModal(`<h3>Vista previa: ${escapeHtml(filename)}</h3><p>Cargando...</p>`, { wide: true });
  try {
    const res = await rootFetch(`${basePath}/${encodeURIComponent(filename)}/preview`);
    if (!res.ok) {
      openModal(
        `<h3>Vista previa: ${escapeHtml(filename)}</h3><p class="modal-error">${escapeHtml(await errorDetail(res))}</p><div class="modal-actions"><button type="button" class="cancel-button">Cerrar</button></div>`,
        { wide: true }
      );
      return;
    }
    const data = await res.json();
    const truncatedNote = data.truncated
      ? `<p class="modal-hint">Mostrando solo los primeros ${data.text.length.toLocaleString("es")} caracteres del texto extraído.</p>`
      : "";
    openModal(
      `
      <h3>Vista previa: ${escapeHtml(data.filename)}</h3>
      ${truncatedNote}
      <pre class="document-preview-text">${escapeHtml(data.text) || "(el documento no tiene texto extraíble)"}</pre>
      <div class="modal-actions">
        <button type="button" class="cancel-button">Cerrar</button>
      </div>
    `,
      { wide: true }
    );
  } catch {
    // rootFetch ya maneja el caso de sesión inválida.
  }
}

async function recategorizeDocument(doc, selectEl) {
  const dependenciaId = selectEl.value === "" ? null : Number(selectEl.value);
  selectEl.disabled = true;
  try {
    const res = await rootFetch(`/api/root/documents/${encodeURIComponent(doc.filename)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dependencia_id: dependenciaId }),
    });
    if (!res.ok) alert(await errorDetail(res));
    await loadDocuments();
  } catch {
    // rootFetch ya maneja el caso de sesión inválida.
  } finally {
    selectEl.disabled = false;
  }
}

async function deleteDocument(doc) {
  if (!confirm(`¿Eliminar "${doc.filename}"? También se quita del índice.`)) return;
  try {
    const res = await rootFetch(`/api/root/documents/${encodeURIComponent(doc.filename)}`, { method: "DELETE" });
    if (!res.ok) {
      alert(await errorDetail(res));
      return;
    }
    await loadDocuments();
  } catch {
    // rootFetch ya maneja el caso de sesión inválida.
  }
}

document.getElementById("documents-search").addEventListener("input", renderDocumentsTable);

document.getElementById("new-document-button").addEventListener("click", () => {
  openModal(`
    <h3>Subir documento</h3>
    <p class="modal-hint">Los PDF y Word se convierten automáticamente a texto plano al subirlos -- el archivo original no se conserva en el servidor, solo su contenido.</p>
    <form id="upload-document-form" class="modal-form">
      <label>Archivo (PDF, TXT, DOCX o XLSX)
        <input id="upload-document-file" type="file" accept=".pdf,.txt,.docx,.xlsx" required />
      </label>
      <label>Dependencia (opcional)
        <select id="upload-document-dependencia">
          <option value="">General / compartido</option>
          ${dependencias.map((d) => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join("")}
        </select>
      </label>
      <p id="upload-document-error" class="modal-error" hidden></p>
      <div class="modal-actions">
        <button type="button" class="cancel-button">Cancelar</button>
        <button type="submit" class="primary-button">Subir</button>
      </div>
    </form>
  `);

  document.getElementById("upload-document-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("upload-document-error");
    const fileInput = document.getElementById("upload-document-file");
    const dependenciaValue = document.getElementById("upload-document-dependencia").value;
    const file = fileInput.files[0];
    if (!file) return;

    const submitButton = e.target.querySelector("button[type=submit]");
    submitButton.disabled = true;
    submitButton.textContent = "Subiendo...";

    const formData = new FormData();
    formData.append("file", file);
    if (dependenciaValue) formData.append("dependencia_id", dependenciaValue);

    try {
      const res = await rootFetch("/api/root/documents", { method: "POST", body: formData });
      if (!res.ok) throw new Error(await errorDetail(res));
      const data = await res.json();
      closeModal();
      await loadDocuments();
      if (data.final_filename && data.final_filename !== file.name) {
        alert(`El documento se guardó como "${data.final_filename}".`);
      }
    } catch (err) {
      errorEl.textContent = err.message || "No se pudo subir el documento.";
      errorEl.hidden = false;
      submitButton.disabled = false;
      submitButton.textContent = "Subir";
    }
  });
});

// --- Preguntas frecuentes sugeridas -------------------------------------

let faqCandidates = [];

function formatTime(isoString) {
  try {
    return new Date(isoString).toLocaleString();
  } catch {
    return isoString;
  }
}

function dependenciaLabelFor(dependenciaId) {
  if (dependenciaId == null) return "General / compartido";
  const dep = dependencias.find((d) => d.id === dependenciaId);
  return dep ? dep.name : `Dependencia ${dependenciaId}`;
}

async function loadFaqCandidates() {
  const res = await rootFetch("/api/root/faq-candidates?status=pending");
  faqCandidates = await res.json();
  renderFaqCandidates();
}

function renderFaqCandidates() {
  const container = document.getElementById("faq-candidates-list");
  const emptyEl = document.getElementById("faq-candidates-empty");
  container.innerHTML = "";
  emptyEl.hidden = faqCandidates.length > 0;

  for (const candidate of faqCandidates) {
    const card = document.createElement("div");
    card.className = "faq-candidate-card";
    card.innerHTML = `
      <div class="faq-candidate-meta">${escapeHtml(dependenciaLabelFor(candidate.dependencia_id))} · ${formatTime(candidate.created_at)}</div>
      <div class="faq-candidate-original">
        <strong>Pregunta original:</strong> ${escapeHtml(candidate.original_question)}<br />
        <strong>Respuesta del asesor:</strong> ${escapeHtml(candidate.original_answer)}
      </div>
      <label>Pregunta sugerida
        <input type="text" class="faq-question-input" maxlength="2000" value="${escapeHtml(candidate.suggested_question)}" />
      </label>
      <label>Respuesta sugerida
        <textarea class="faq-answer-input" maxlength="5000">${escapeHtml(candidate.suggested_answer)}</textarea>
      </label>
      <p class="modal-error faq-candidate-error" hidden></p>
      <div class="faq-candidate-actions">
        <button type="button" class="cancel-button reject-button">Descartar</button>
        <button type="button" class="primary-button accept-button">Aceptar</button>
      </div>
    `;
    const questionInput = card.querySelector(".faq-question-input");
    const answerInput = card.querySelector(".faq-answer-input");
    const errorEl = card.querySelector(".faq-candidate-error");

    card.querySelector(".reject-button").addEventListener("click", async () => {
      if (!confirm("¿Descartar esta propuesta de pregunta frecuente?")) return;
      try {
        const res = await rootFetch(`/api/root/faq-candidates/${candidate.id}/reject`, { method: "POST" });
        if (!res.ok) throw new Error(await errorDetail(res));
        await loadFaqCandidates();
      } catch (err) {
        errorEl.textContent = err.message || "No se pudo descartar, intenta de nuevo.";
        errorEl.hidden = false;
      }
    });

    const acceptButton = card.querySelector(".accept-button");
    acceptButton.addEventListener("click", async () => {
      const question = questionInput.value.trim();
      const answer = answerInput.value.trim();
      if (!question || !answer) return;
      acceptButton.disabled = true;
      errorEl.hidden = true;
      try {
        const saveRes = await rootFetch(`/api/root/faq-candidates/${candidate.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question, answer }),
        });
        if (!saveRes.ok) throw new Error(await errorDetail(saveRes));

        const acceptRes = await rootFetch(`/api/root/faq-candidates/${candidate.id}/accept`, { method: "POST" });
        if (!acceptRes.ok) throw new Error(await errorDetail(acceptRes));

        await loadFaqCandidates();
      } catch (err) {
        errorEl.textContent = err.message || "No se pudo aceptar, intenta de nuevo.";
        errorEl.hidden = false;
        acceptButton.disabled = false;
      }
    });

    container.appendChild(card);
  }
}

// --- Arranque ----------------------------------------------------------

if (getToken()) {
  tryEnterApp();
} else {
  showAuthGate();
}
