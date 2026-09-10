const authGateEl = document.getElementById("auth-gate");
const authFormEl = document.getElementById("auth-form");
const adminUsernameInputEl = document.getElementById("admin-username-input");
const adminPasswordInputEl = document.getElementById("admin-password-input");
const authErrorEl = document.getElementById("auth-error");
const rootAppEl = document.getElementById("root-app");
const adminDisplayNameEl = document.getElementById("admin-display-name");
const logoutButtonEl = document.getElementById("logout-button");
const changePasswordButtonEl = document.getElementById("change-password-button");

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
    await loadHostilityKeywords();
    await loadWidgetOrigins();
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

// --- Dependencias --------------------------------------------------------

async function loadDependencias() {
  const res = await rootFetch("/api/root/dependencias");
  dependencias = await res.json();
  renderDependenciasTable();
  renderDocumentDependenciaChips();
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
          <button type="button" class="horario-button">Horario</button>
          <button type="button" class="danger delete-button">Eliminar</button>
        </div>
      </td>
    `;
    tr.querySelector(".edit-button").addEventListener("click", () => openDependenciaModal(dep));
    tr.querySelector(".horario-button").addEventListener("click", () => openHorarioModal(dep, "/api/root/dependencias"));
    tr.querySelector(".delete-button").addEventListener("click", () => deleteDependencia(dep));
    tbody.appendChild(tr);
  }
}

function openHorarioModal(dep, baseUrl) {
  const diasActuales = new Set(dep.horario_dias || []);
  const rangosActuales = dep.horario_rangos && dep.horario_rangos.length ? dep.horario_rangos : [["", ""]];

  openModal(`
    <h3>Horario de atención — ${escapeHtml(dep.name)}</h3>
    <form id="horario-form" class="modal-form">
      <label>Días de atención</label>
      <div class="horario-dias-checks">
        ${Object.entries(HORARIO_DIA_LABELS)
          .map(
            ([value, label]) => `
              <label class="horario-dia-check">
                <input type="checkbox" value="${value}" ${diasActuales.has(Number(value)) ? "checked" : ""} />
                ${label}
              </label>
            `
          )
          .join("")}
      </div>
      <label>Bloques de horario (uno por franja, ej. mañana y tarde)</label>
      <div id="horario-rangos-list">
        ${rangosActuales.map(([inicio, fin]) => horarioRangoRowHtml(inicio, fin)).join("")}
      </div>
      <button type="button" id="add-horario-rango-button" class="modal-secondary-button">+ Agregar bloque</button>
      <p id="horario-form-error" class="modal-error" hidden></p>
      <div class="modal-actions">
        <button type="button" class="cancel-button">Cancelar</button>
        <button type="submit" class="primary-button">Guardar</button>
      </div>
    </form>
  `);

  const rangosListEl = document.getElementById("horario-rangos-list");
  const wireRemoveButtons = () => {
    rangosListEl.querySelectorAll(".remove-rango-button").forEach((btn) => {
      btn.onclick = () => {
        if (rangosListEl.children.length > 1) btn.closest(".horario-rango-row").remove();
      };
    });
  };
  wireRemoveButtons();

  document.getElementById("add-horario-rango-button").addEventListener("click", () => {
    rangosListEl.insertAdjacentHTML("beforeend", horarioRangoRowHtml("", ""));
    wireRemoveButtons();
  });

  document.getElementById("horario-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("horario-form-error");
    errorEl.hidden = true;

    const dias = Array.from(document.querySelectorAll(".horario-dia-check input:checked")).map((el) => Number(el.value));
    const rangos = Array.from(rangosListEl.querySelectorAll(".horario-rango-row")).map((row) => ({
      inicio: row.querySelector(".horario-rango-inicio").value,
      fin: row.querySelector(".horario-rango-fin").value,
    }));

    if (dias.length === 0 || rangos.some((r) => !r.inicio || !r.fin)) {
      errorEl.textContent = "Selecciona al menos un día y completa todos los bloques de horario.";
      errorEl.hidden = false;
      return;
    }

    try {
      const res = await rootFetch(`${baseUrl}/${dep.id}/horario`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dias, rangos }),
      });
      if (!res.ok) throw new Error(await errorDetail(res));
      closeModal();
      await loadDependencias();
    } catch (err) {
      errorEl.textContent = err.message || "No se pudo guardar, intenta de nuevo.";
      errorEl.hidden = false;
    }
  });
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

function buildConversacionesSection(dashboard) {
  const c = dashboard.conversations;
  const summaryHtml = `${c.total_escalated} escaladas · ${c.pending_now} pendientes · ${c.resolved} resueltas`;
  const detailHtml = `
    <div class="dashboard-cards">
      ${dashboardCardHtml("Escaladas en los últimos 7 días", c.last_7_days)}
      ${dashboardCardHtml("Primera respuesta (promedio)", formatMinutes(c.avg_first_response_minutes))}
      ${dashboardCardHtml("Resolución (promedio)", formatMinutes(c.avg_resolution_minutes))}
    </div>
    <div class="dashboard-charts">
      <div class="dashboard-chart-card">
        <h3>Conversaciones escaladas por día (últimos 30 días)</h3>
        <canvas id="dashboard-conversations-chart"></canvas>
      </div>
    </div>
    <div class="dashboard-tables">
      <div class="dashboard-table-card">
        <h3>Conversaciones por dependencia</h3>
        <table class="data-table">
          <thead><tr><th>Dependencia</th><th>Conversaciones</th></tr></thead>
          <tbody id="dashboard-by-dependencia-body"></tbody>
        </table>
        <p id="dashboard-by-dependencia-empty" class="empty-hint" hidden>Todavía no hay conversaciones escaladas.</p>
      </div>
    </div>
  `;
  return { title: "Conversaciones", summaryHtml, detailHtml };
}

function buildDocumentosSection(documents) {
  const summaryHtml = `${documents.total} documentos · ${formatSize(documents.total_size_bytes)}`;
  const detailHtml = `
    <div class="dashboard-tables">
      <div class="dashboard-table-card">
        <h3>Documentos recientes</h3>
        <table class="data-table">
          <thead><tr><th>Archivo</th><th>Actualizado</th></tr></thead>
          <tbody id="dashboard-recent-documents-body"></tbody>
        </table>
        <p id="dashboard-recent-documents-empty" class="empty-hint" hidden>Todavía no hay documentos indexados.</p>
      </div>
    </div>
  `;
  return { title: "Documentos", summaryHtml, detailHtml };
}

function buildFaqSection(faq) {
  const summaryHtml = `${faq.pending} pendientes · ${faq.accepted} aceptadas · ${faq.rejected} rechazadas`;
  return { title: "Preguntas frecuentes", summaryHtml, detailHtml: "" };
}

function buildEquipoSection(adminTeam) {
  const summaryHtml = `${adminTeam.admins_active} administradores activos`;
  const roleCards = Object.entries(adminTeam.admins_active_by_role || {})
    .map(([role, count]) => dashboardCardHtml(`Activos - ${role.charAt(0).toUpperCase()}${role.slice(1)}`, count))
    .join("");
  const detailHtml = `
    <div class="dashboard-cards">
      ${dashboardCardHtml("Dependencias activas", adminTeam.dependencias_count)}
      ${dashboardCardHtml("Administradores inactivos", adminTeam.admins_inactive)}
      ${roleCards}
    </div>
  `;
  return { title: "Equipo de administración", summaryHtml, detailHtml };
}

function buildRendimientoSection(performance) {
  const summaryHtml = `${performance.avg_total_ms != null ? performance.avg_total_ms + " ms" : "—"} promedio · ${
    performance.cache_hit_rate != null ? performance.cache_hit_rate + "% caché" : "—"
  }`;
  const detailHtml = `
    <div class="dashboard-cards">
      ${dashboardCardHtml("Recuperación (promedio)", performance.avg_retrieval_ms != null ? `${performance.avg_retrieval_ms} ms` : "—")}
      ${dashboardCardHtml("Generación (promedio)", performance.avg_generation_ms != null ? `${performance.avg_generation_ms} ms` : "—")}
      ${dashboardCardHtml(
        "Respuestas servidas desde caché",
        performance.cache_hit_rate != null ? `${performance.cache_hits} (${performance.cache_hit_rate}%)` : performance.cache_hits
      )}
      ${dashboardCardHtml("Llamadas a Groq (total)", performance.groq_calls_total)}
      ${dashboardCardHtml("Llamadas a Groq (últimos 7 días)", performance.groq_calls_last_7_days)}
      ${dashboardCardHtml("Llamadas a Groq fallidas", performance.groq_calls_failed)}
    </div>
    <div class="dashboard-charts">
      <div class="dashboard-chart-card">
        <h3>Llamadas a Groq por día (últimos 30 días)</h3>
        <canvas id="dashboard-groq-chart"></canvas>
      </div>
    </div>
  `;
  return { title: "Rendimiento del sistema", summaryHtml, detailHtml };
}

function buildPreguntasSinRespuestaSection(unansweredQuestions) {
  const count = (unansweredQuestions.top || []).length;
  const summaryHtml = `${count} preguntas registradas`;
  const detailHtml = `
    <p class="panel-section-hint" style="margin: 0 0 10px;">
      Lo que le falta a los documentos -- prioriza qué subir o completar.
    </p>
    <table class="data-table">
      <thead><tr><th>Pregunta</th><th>Veces</th><th>Última vez</th></tr></thead>
      <tbody id="dashboard-unanswered-questions-body"></tbody>
    </table>
    <p id="dashboard-unanswered-questions-empty" class="empty-hint" hidden>No hay preguntas sin responder registradas.</p>
  `;
  return { title: "Preguntas sin respuesta suficiente", summaryHtml, detailHtml };
}

function buildFeedbackSection(feedback) {
  const summaryHtml = `👍 ${feedback.up} · 👎 ${feedback.down}${feedback.down_rate != null ? ` (${feedback.down_rate}%)` : ""}`;
  const detailHtml = `
    <p class="panel-section-hint" style="margin: 0 0 10px;">
      Respuestas que sí encontraron información, pero los estudiantes marcaron como no útil.
    </p>
    <table class="data-table">
      <thead><tr><th>Pregunta</th><th>👎</th></tr></thead>
      <tbody id="dashboard-most-disliked-body"></tbody>
    </table>
    <p id="dashboard-most-disliked-empty" class="empty-hint" hidden>Todavía no hay respuestas calificadas como no útiles.</p>
  `;
  return { title: "Feedback de estudiantes", summaryHtml, detailHtml };
}

function renderDashboardSections(dashboard) {
  const sections = [
    buildConversacionesSection(dashboard),
    buildDocumentosSection(dashboard.documents),
    buildFaqSection(dashboard.faq),
    dashboard.admin_team && buildEquipoSection(dashboard.admin_team),
    dashboard.performance && buildRendimientoSection(dashboard.performance),
    dashboard.unanswered_questions && buildPreguntasSinRespuestaSection(dashboard.unanswered_questions),
    dashboard.feedback && buildFeedbackSection(dashboard.feedback),
  ].filter(Boolean);

  document.getElementById("dashboard-sections").innerHTML = sections
    .map((s) => dashboardSectionHtml(s.title, s.summaryHtml, s.detailHtml))
    .join("");
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

function renderDashboardUnansweredQuestionsTable(dashboard) {
  const tbody = document.getElementById("dashboard-unanswered-questions-body");
  const emptyEl = document.getElementById("dashboard-unanswered-questions-empty");
  const rows = (dashboard.unanswered_questions && dashboard.unanswered_questions.top) || [];
  tbody.innerHTML = "";
  emptyEl.hidden = rows.length > 0;
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${escapeHtml(row.question)}</td><td>${row.count}</td><td>${formatTime(row.last_asked)}</td>`;
    tbody.appendChild(tr);
  }
}

function renderDashboardMostDislikedTable(dashboard) {
  const tbody = document.getElementById("dashboard-most-disliked-body");
  const emptyEl = document.getElementById("dashboard-most-disliked-empty");
  const rows = (dashboard.feedback && dashboard.feedback.most_disliked) || [];
  tbody.innerHTML = "";
  emptyEl.hidden = rows.length > 0;
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${escapeHtml(row.question)}</td><td>${row.count}</td>`;
    tbody.appendChild(tr);
  }
}

async function loadDashboard() {
  const res = await rootFetch("/api/dashboard");
  const dashboard = await res.json();
  document.getElementById("dashboard-summary").innerHTML = dashboardSummaryHtml(dashboard);
  renderDashboardSections(dashboard);
  renderDashboardCharts(dashboard);
  renderDashboardByDependenciaTable(dashboard);
  renderDashboardRecentDocumentsTable(dashboard);
  renderDashboardUnansweredQuestionsTable(dashboard);
  renderDashboardMostDislikedTable(dashboard);
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

let documentDependenciaFilter = "all"; // "all" | "general" | <dependencia_id numérico>

async function loadDocuments() {
  const res = await rootFetch("/api/root/documents");
  documents = await res.json();
  renderDocumentDependenciaChips();
  renderDocumentsTable();
}

function renderDocumentDependenciaChips() {
  const container = document.getElementById("documents-dependencia-chips");
  const chips = [
    { value: "all", label: "Todos" },
    { value: "general", label: "General / compartido" },
    ...dependencias.map((d) => ({ value: String(d.id), label: d.name })),
  ];
  container.innerHTML = chips
    .map(
      (chip) => `
        <button type="button" class="filter-chip ${documentDependenciaFilter === chip.value ? "active" : ""}" data-value="${chip.value}">
          ${escapeHtml(chip.label)}
        </button>
      `
    )
    .join("");
  container.querySelectorAll(".filter-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      documentDependenciaFilter = btn.dataset.value;
      renderDocumentDependenciaChips();
      renderDocumentsTable();
    });
  });
}

function renderDocumentsTable() {
  const tbody = document.getElementById("documents-table-body");
  const emptyEl = document.getElementById("documents-empty");
  const searchInput = document.getElementById("documents-search");
  tbody.innerHTML = "";

  const query = searchInput ? searchInput.value.trim().toLowerCase() : "";
  const filteredDocuments = documents.filter(
    (doc) => (!query || doc.filename.toLowerCase().includes(query)) && documentMatchesDependenciaFilter(doc, documentDependenciaFilter)
  );

  emptyEl.hidden = filteredDocuments.length > 0;
  emptyEl.textContent =
    documents.length === 0 ? "Todavía no hay documentos indexados." : "Ningún documento coincide con la búsqueda.";

  for (const doc of filteredDocuments) {
    const tr = document.createElement("tr");
    const nameCell = doc.source_url
      ? `${escapeHtml(doc.filename)} <a href="${escapeHtml(doc.source_url)}" target="_blank" rel="noopener" title="Página original: ${escapeHtml(doc.source_url)}">🔗</a>`
      : escapeHtml(doc.filename);
    if (doc.archived_at) {
      tr.innerHTML = `
        <td>${nameCell} <span class="archived-badge">Archivado</span></td>
        <td>${formatSize(doc.size_bytes)}</td>
        <td>${escapeHtml(dependenciaLabelFor(doc.dependencia_id))}</td>
        <td>${escapeHtml(doc.vigente_desde || "")}</td>
        <td>${doc.downloadable ? "Sí" : "No"}</td>
        <td>
          <div class="row-actions">
            <button type="button" class="reactivate-button">Reactivar</button>
          </div>
        </td>
      `;
      tr.querySelector(".reactivate-button").addEventListener("click", () => reactivateDocument(doc));
      tbody.appendChild(tr);
      continue;
    }

    tr.innerHTML = `
      <td>${nameCell}</td>
      <td>${formatSize(doc.size_bytes)}</td>
      <td><select class="doc-dependencia-select">${documentDependenciaOptionsHtml(doc.dependencia_id, dependencias)}</select></td>
      <td><input type="date" class="doc-vigencia-input" value="${doc.vigente_desde || ""}" title="Fecha desde la cual este documento aplica -- puede ser futura" /></td>
      <td>
        <label class="downloadable-toggle" title="Si se desmarca, el documento sigue indexado y respondiendo preguntas, pero el estudiante no podrá descargarlo">
          <input type="checkbox" class="doc-downloadable-checkbox" ${doc.downloadable ? "checked" : ""} />
        </label>
      </td>
      <td>
        <div class="row-actions">
          <button type="button" class="preview-button">Vista previa</button>
          <button type="button" class="archive-button">Archivar</button>
          <button type="button" class="danger delete-button">Eliminar</button>
        </div>
      </td>
    `;
    const select = tr.querySelector(".doc-dependencia-select");
    select.addEventListener("change", () => {
      const dependenciaId = select.value === "" ? null : Number(select.value);
      recategorizeDocument(doc, { dependenciaId });
    });
    const vigenciaInput = tr.querySelector(".doc-vigencia-input");
    vigenciaInput.addEventListener("change", () => {
      recategorizeDocument(doc, { vigenteDesde: vigenciaInput.value || null });
    });
    tr.querySelector(".doc-downloadable-checkbox").addEventListener("change", (e) => {
      setDocumentDownloadable(rootFetch, "/api/root/documents", doc.filename, e.target.checked);
    });
    tr.querySelector(".preview-button").addEventListener("click", () => previewDocument(doc.filename, "/api/root/documents"));
    tr.querySelector(".archive-button").addEventListener("click", () => archiveDocument(doc));
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
    const downloadUrl = `/api/documents/${encodeURIComponent(data.filename)}/download?session_id=${encodeURIComponent("admin-" + getToken())}`;
    openModal(
      `
      <h3>Vista previa: ${escapeHtml(data.filename)}</h3>
      ${truncatedNote}
      <pre class="document-preview-text">${escapeHtml(data.text) || "(el documento no tiene texto extraíble)"}</pre>
      <div class="modal-actions">
        <a class="primary-button" href="${downloadUrl}">Descargar original</a>
        <button type="button" class="cancel-button">Cerrar</button>
      </div>
    `,
      { wide: true }
    );
  } catch {
    // rootFetch ya maneja el caso de sesión inválida.
  }
}

async function recategorizeDocument(doc, { dependenciaId, vigenteDesde } = {}) {
  // Cada PUT manda los dos campos siempre -- si solo se editó uno, el otro
  // se rellena con el valor actual del documento, para no borrarlo sin
  // querer (el backend reemplaza ambos, no hace merge parcial).
  const finalDependenciaId = dependenciaId !== undefined ? dependenciaId : doc.dependencia_id ?? null;
  const finalVigenteDesde = vigenteDesde !== undefined ? vigenteDesde : doc.vigente_desde || null;
  try {
    const res = await rootFetch(`/api/root/documents/${encodeURIComponent(doc.filename)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dependencia_id: finalDependenciaId, vigente_desde: finalVigenteDesde }),
    });
    if (!res.ok) alert(await errorDetail(res));
    await loadDocuments();
  } catch {
    // rootFetch ya maneja el caso de sesión inválida.
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

async function archiveDocument(doc) {
  if (
    !confirm(
      `¿Archivar "${doc.filename}"? Deja de responder preguntas hasta que lo reactives, pero el archivo se conserva.`
    )
  )
    return;
  try {
    const res = await rootFetch(`/api/root/documents/${encodeURIComponent(doc.filename)}/archive`, { method: "PUT" });
    if (!res.ok) {
      alert(await errorDetail(res));
      return;
    }
    await loadDocuments();
  } catch {
    // rootFetch ya maneja el caso de sesión inválida.
  }
}

async function reactivateDocument(doc) {
  try {
    const res = await rootFetch(`/api/root/documents/${encodeURIComponent(doc.filename)}/reactivate`, {
      method: "PUT",
    });
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
    <p class="modal-hint">Los PDF y Word se convierten automáticamente a texto plano al subirlos para la búsqueda -- el archivo original se conserva aparte para que los estudiantes puedan descargarlo. Las imágenes (afiches de eventos, talleres, etc.) también: se extrae el texto con IA para revisarlo antes de guardar.</p>
    <form id="upload-document-form" class="modal-form">
      <label>Archivo (PDF, TXT, DOCX, XLSX, JPG, PNG o WEBP)
        <input id="upload-document-file" type="file" accept=".pdf,.txt,.docx,.xlsx,.jpg,.jpeg,.png,.webp" required />
      </label>
      <label>Dependencia (opcional)
        <select id="upload-document-dependencia">
          <option value="">General / compartido</option>
          ${dependencias.map((d) => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join("")}
        </select>
      </label>
      <label>Vigente desde (opcional)
        <input id="upload-document-vigencia" type="date" />
      </label>
      <p class="modal-hint">Solo para documentos que se reemplazan con el tiempo (calendarios, precios, etc.): si dos documentos responden la misma pregunta, gana el de fecha más reciente -- puede ser una fecha futura si ya se sabe que ese documento aplicará desde entonces. Déjalo vacío para documentos generales que no vencen.</p>
      <label>Nombre del archivo (opcional)
        <input id="upload-document-desired-name" type="text" placeholder="Dejar vacío para usar el nombre original" maxlength="150" />
      </label>
      <p class="modal-hint">Para PDF/DOCX/imágenes -- útil cuando el archivo trae un nombre genérico (ej. una foto de WhatsApp). En imágenes con nombre genérico se sugiere uno automáticamente tras extraer el texto.</p>
      <p id="upload-document-duplicate-warning" class="modal-error" hidden></p>
      <div id="upload-document-extracted-container" hidden>
        <label>Texto extraído de la imagen (revísalo y corrígelo si hace falta)
          <textarea id="upload-document-extracted-text" rows="8"></textarea>
        </label>
      </div>
      <p id="upload-document-error" class="modal-error" hidden></p>
      <div class="modal-actions">
        <button type="button" class="cancel-button">Cancelar</button>
        <button type="submit" class="primary-button">Subir</button>
      </div>
    </form>
  `);

  const fileInput = document.getElementById("upload-document-file");
  const extractedContainer = document.getElementById("upload-document-extracted-container");
  const extractedTextarea = document.getElementById("upload-document-extracted-text");
  const desiredNameInput = document.getElementById("upload-document-desired-name");
  const duplicateWarningEl = document.getElementById("upload-document-duplicate-warning");
  const submitButton = document.querySelector("#upload-document-form button[type=submit]");
  let hasExtractedText = false;

  fileInput.addEventListener("change", () => {
    hasExtractedText = false;
    extractedContainer.hidden = true;
    extractedTextarea.value = "";
    desiredNameInput.value = "";
    duplicateWarningEl.hidden = true;
    submitButton.textContent = "Subir";
  });

  document.getElementById("upload-document-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("upload-document-error");
    const dependenciaValue = document.getElementById("upload-document-dependencia").value;
    const vigenciaValue = document.getElementById("upload-document-vigencia").value;
    const file = fileInput.files[0];
    if (!file) return;
    const isImage = IMAGE_EXTENSION_PATTERN.test(file.name);

    errorEl.hidden = true;

    // Paso 1 para imágenes: solo extraer el texto y mostrarlo para revisión
    // -- todavía no se sube/guarda nada.
    if (isImage && !hasExtractedText) {
      submitButton.disabled = true;
      submitButton.textContent = "Extrayendo texto...";
      try {
        const extractFormData = new FormData();
        extractFormData.append("file", file);
        const res = await rootFetch("/api/root/documents/extract-image-text", { method: "POST", body: extractFormData });
        if (!res.ok) throw new Error(await errorDetail(res));
        const data = await res.json();
        extractedTextarea.value = data.text || "";
        extractedContainer.hidden = false;
        if (data.suggested_filename) desiredNameInput.value = data.suggested_filename;
        if (data.duplicate) {
          duplicateWarningEl.textContent = `Esta imagen ya está subida como "${data.duplicate.filename}" (agregada el ${data.duplicate.created_at}). Si continúas, el guardado la rechazará para no duplicar contenido.`;
          duplicateWarningEl.hidden = false;
        } else {
          duplicateWarningEl.hidden = true;
        }
        hasExtractedText = true;
        submitButton.textContent = "Guardar documento";
      } catch (err) {
        errorEl.textContent = err.message || "No se pudo extraer el texto de la imagen.";
        errorEl.hidden = false;
        submitButton.textContent = "Subir";
      } finally {
        submitButton.disabled = false;
      }
      return;
    }

    submitButton.disabled = true;
    submitButton.textContent = "Subiendo...";

    const formData = new FormData();
    formData.append("file", file);
    if (dependenciaValue) formData.append("dependencia_id", dependenciaValue);
    if (vigenciaValue) formData.append("vigente_desde", vigenciaValue);
    if (isImage) formData.append("extracted_text", extractedTextarea.value);
    if (desiredNameInput.value.trim()) formData.append("desired_filename", desiredNameInput.value.trim());

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
      submitButton.textContent = isImage ? "Guardar documento" : "Subir";
    }
  });
});

// --- Indexar sitio web (app/services/crawl_job_service.py) --------------

const CRAWL_STATUS_LABELS = {
  running: "Rastreando...",
  done: "Terminado",
  cancelled: "Cancelado",
  error: "Error",
};

function crawlProgressHtml(status) {
  const summary =
    status.status === "running"
      ? `<p class="modal-hint">Página actual: ${escapeHtml(status.current_url || "-")}</p>`
      : "";
  const skippedNote = status.skipped_binary_urls.length
    ? `<p class="modal-hint">${status.skipped_binary_urls.length} archivo(s) (PDF/Word/Excel) enlazados no se indexaron automáticamente -- súbelos a mano desde "Subir documento" si los necesitas:</p>
       <ul class="crawl-skipped-list">${status.skipped_binary_urls.map((u) => `<li>${escapeHtml(u)}</li>`).join("")}</ul>`
    : "";
  const errorsNote = status.errors.length
    ? `<p class="modal-error">${status.errors.length} error(es):</p>
       <ul class="crawl-skipped-list">${status.errors.map((e) => `<li>${escapeHtml(e)}</li>`).join("")}</ul>`
    : "";
  const cancelButton =
    status.status === "running"
      ? `<button type="button" class="danger" id="crawl-cancel-button">Cancelar</button>`
      : `<button type="button" class="cancel-button">Cerrar</button>`;

  return `
    <h3>Indexando: ${escapeHtml(status.seed_url)}</h3>
    <p><strong>${CRAWL_STATUS_LABELS[status.status] || status.status}</strong> -- ${status.pages_indexed} página(s) indexada(s)${status.pages_failed ? `, ${status.pages_failed} fallida(s)` : ""}.</p>
    ${summary}
    ${skippedNote}
    ${errorsNote}
    <div class="modal-actions">${cancelButton}</div>
  `;
}

function pollCrawlJob(jobId) {
  const interval = setInterval(async () => {
    // Si el admin cerró el modal, este contenedor ya no existe -- el
    // rastreo sigue corriendo en el servidor igual, solo se deja de
    // consultar desde el navegador.
    if (!document.getElementById("crawl-progress-root")) {
      clearInterval(interval);
      return;
    }
    let status;
    try {
      const res = await rootFetch(`/api/root/crawl-site/${encodeURIComponent(jobId)}`);
      if (!res.ok) throw new Error();
      status = await res.json();
    } catch {
      return; // reintenta en el siguiente tick -- un fallo de red puntual no debe detener el seguimiento.
    }

    modalContentEl.innerHTML = `<div id="crawl-progress-root">${crawlProgressHtml(status)}</div>`;
    const cancelButton = document.getElementById("crawl-cancel-button");
    if (cancelButton) {
      cancelButton.addEventListener("click", async () => {
        cancelButton.disabled = true;
        cancelButton.textContent = "Cancelando...";
        await rootFetch(`/api/root/crawl-site/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
      });
    }
    const closeButton = document.querySelector("#crawl-progress-root .cancel-button");
    if (closeButton) {
      closeButton.addEventListener("click", () => {
        closeModal();
        loadDocuments();
      });
    }

    if (status.status !== "running") {
      clearInterval(interval);
    }
  }, 1500);
}

document.getElementById("new-crawl-button").addEventListener("click", () => {
  openModal(`
    <h3>Indexar sitio web</h3>
    <p class="modal-hint">Descarga la URL indicada y sigue los enlaces que encuentre dentro del mismo dominio y ruta -- cada página queda indexada como un documento más, marcada como no descargable (se muestra un enlace a la página real en vez de un botón de descarga). Puede tardar varios minutos en un sitio grande.</p>
    <form id="crawl-site-form" class="modal-form">
      <label>URL inicial
        <input id="crawl-seed-url" type="url" placeholder="https://www.unilibre.edu.co/cucuta/" required />
      </label>
      <label>Ruta permitida (opcional)
        <input id="crawl-path-prefix" type="text" placeholder="/cucuta -- vacío usa la ruta de la URL inicial" />
      </label>
      <p class="modal-hint">Nunca sigue enlaces fuera de este dominio+ruta, aunque el sitio los tenga (portales, subdominios, redes sociales, etc.).</p>
      <label>Profundidad máxima de enlaces
        <input id="crawl-max-depth" type="number" min="0" max="5" value="2" />
      </label>
      <label>Máximo de páginas
        <input id="crawl-max-pages" type="number" min="1" max="500" value="50" />
      </label>
      <label>Dependencia (opcional)
        <select id="crawl-dependencia">
          <option value="">General / compartido</option>
          ${dependencias.map((d) => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join("")}
        </select>
      </label>
      <p id="crawl-site-error" class="modal-error" hidden></p>
      <div class="modal-actions">
        <button type="button" class="cancel-button">Cancelar</button>
        <button type="submit" class="primary-button">Empezar a indexar</button>
      </div>
    </form>
  `);

  document.getElementById("crawl-site-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("crawl-site-error");
    const submitButton = e.target.querySelector("button[type=submit]");
    const dependenciaValue = document.getElementById("crawl-dependencia").value;
    errorEl.hidden = true;
    submitButton.disabled = true;
    submitButton.textContent = "Empezando...";

    try {
      const res = await rootFetch("/api/root/crawl-site", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          seed_url: document.getElementById("crawl-seed-url").value.trim(),
          allowed_path_prefix: document.getElementById("crawl-path-prefix").value.trim() || null,
          max_depth: Number(document.getElementById("crawl-max-depth").value),
          max_pages: Number(document.getElementById("crawl-max-pages").value),
          dependencia_id: dependenciaValue ? Number(dependenciaValue) : null,
        }),
      });
      if (!res.ok) throw new Error(await errorDetail(res));
      const data = await res.json();
      openModal(`<div id="crawl-progress-root"><h3>Indexando...</h3><p>Empezando el rastreo...</p></div>`);
      pollCrawlJob(data.job_id);
    } catch (err) {
      errorEl.textContent = err.message || "No se pudo iniciar el rastreo.";
      errorEl.hidden = false;
      submitButton.disabled = false;
      submitButton.textContent = "Empezar a indexar";
    }
  });
});

// --- Preguntas frecuentes sugeridas -------------------------------------

let faqCandidates = [];

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

// --- Moderación: detector de hostilidad -----------------------------------

const hostilityKeywordsTab = wireSimpleListTab({
  fetchFn: rootFetch,
  listUrl: "/api/root/hostility-keywords",
  createUrl: "/api/root/hostility-keywords",
  deleteUrlFor: (keyword) => `/api/root/hostility-keywords/${keyword.id}`,
  createBody: (phrase) => ({ phrase }),
  formId: "new-hostility-keyword-form",
  inputId: "new-hostility-keyword-input",
  errorId: "hostility-keyword-error",
  tbodyId: "hostility-keywords-table-body",
  emptyId: "hostility-keywords-empty",
  deleteButtonSelector: ".delete-hostility-keyword-button",
  rowHtml: (keyword) => `
    <td>${escapeHtml(keyword.phrase)}</td>
    <td>
      <div class="row-actions">
        <button type="button" class="danger delete-hostility-keyword-button">Eliminar</button>
      </div>
    </td>
  `,
  confirmMessage: (keyword) => `¿Eliminar "${keyword.phrase}" de la lista de hostilidad?`,
});

async function loadHostilityKeywords() {
  await hostilityKeywordsTab.load();
}

// --- Widget embebible: orígenes permitidos --------------------------------

const widgetOriginsTab = wireSimpleListTab({
  fetchFn: rootFetch,
  listUrl: "/api/root/widget-origins",
  createUrl: "/api/root/widget-origins",
  deleteUrlFor: (origin) => `/api/root/widget-origins/${origin.id}`,
  createBody: (origin) => ({ origin }),
  formId: "new-widget-origin-form",
  inputId: "new-widget-origin-input",
  errorId: "widget-origin-error",
  tbodyId: "widget-origins-table-body",
  emptyId: "widget-origins-empty",
  deleteButtonSelector: ".delete-widget-origin-button",
  rowHtml: (origin) => `
    <td>${escapeHtml(origin.origin)}</td>
    <td>
      <div class="row-actions">
        <button type="button" class="danger delete-widget-origin-button">Eliminar</button>
      </div>
    </td>
  `,
  confirmMessage: (origin) => `¿Quitar "${origin.origin}" de los sitios permitidos para embeber el widget?`,
});

async function loadWidgetOrigins() {
  await widgetOriginsTab.load();
  document.getElementById("widget-snippet-code").textContent =
    `<script src="${location.origin}/static/widget-loader.js"></scr` + `ipt>`;
}

// --- Arranque ----------------------------------------------------------

if (getToken()) {
  tryEnterApp();
} else {
  showAuthGate();
}
