const authGateEl = document.getElementById("auth-gate");
const authFormEl = document.getElementById("auth-form");
const adminUsernameInputEl = document.getElementById("admin-username-input");
const adminPasswordInputEl = document.getElementById("admin-password-input");
const authErrorEl = document.getElementById("auth-error");
const panelAppEl = document.getElementById("panel-app");
const adminDisplayNameEl = document.getElementById("admin-display-name");
const logoutButtonEl = document.getElementById("logout-button");

const sessionListEl = document.getElementById("session-list");
const sessionCountEl = document.getElementById("session-count");
const pendingChipEl = document.getElementById("pending-chip");
const conversationEmptyEl = document.getElementById("conversation-empty");
const conversationHeaderEl = document.getElementById("conversation-header");
const conversationTitleEl = document.getElementById("conversation-title");
const conversationSubtitleEl = document.getElementById("conversation-subtitle");
const conversationMessagesEl = document.getElementById("conversation-messages");
const resolveButtonEl = document.getElementById("resolve-button");
const askContinueButtonEl = document.getElementById("ask-continue-button");
const reassignSelectEl = document.getElementById("reassign-select");
const advisorReplyFormEl = document.getElementById("advisor-reply-form");
const advisorReplyInputEl = document.getElementById("advisor-reply-input");
const askBotPanelEl = document.getElementById("ask-bot-panel");
const askBotFormEl = document.getElementById("ask-bot-form");
const askBotInputEl = document.getElementById("ask-bot-input");
const askBotResultEl = document.getElementById("ask-bot-result");
const askBotAnswerEl = document.getElementById("ask-bot-answer");
const askBotSourcesEl = document.getElementById("ask-bot-sources");
const askBotUseButtonEl = document.getElementById("ask-bot-use");
const askBotDiscardButtonEl = document.getElementById("ask-bot-discard");
const wsStatusEl = document.getElementById("ws-status");
const panelBodyEl = document.querySelector(".panel-body");
const backToListButton = document.getElementById("back-to-list");
const documentsTabButtonEl = document.getElementById("documents-tab-button");
const dashboardTabButtonEl = document.getElementById("dashboard-tab-button");
const moderacionTabButtonEl = document.getElementById("moderacion-tab-button");
const widgetTabButtonEl = document.getElementById("widget-tab-button");
const horarioTabButtonEl = document.getElementById("horario-tab-button");
const modalOverlayEl = document.getElementById("modal-overlay");
const modalContentEl = document.getElementById("modal-content");

const SENDER_LABELS = { student: "Estudiante", assistant: "Asistente", advisor: "Asesor" };

const PAGE_SIZE = 30;

let sessions = [];
let activeSessionId = null;
let filterPending = false;
let sessionsOffset = 0;
let sessionsHasMore = true;
let sessionsLoading = false;
let totalSessionsCount = 0;
let pendingCount = 0;

function getAdminToken() {
  return localStorage.getItem("admin_token") || "";
}

// dependencia_id se guarda como texto ("null" o un número) porque
// localStorage solo almacena strings; getAdminDependenciaId() lo decodifica
// de vuelta al mismo tipo que manda el backend (null o number), para poder
// compararlo con el dependencia_id que llega en los eventos del WebSocket.
function setAdminSession({ token, displayName, role, dependenciaId }) {
  localStorage.setItem("admin_token", token);
  localStorage.setItem("admin_display_name", displayName);
  localStorage.setItem("admin_role", role);
  localStorage.setItem("admin_dependencia_id", dependenciaId === null || dependenciaId === undefined ? "null" : String(dependenciaId));
}

function getAdminDependenciaId() {
  const raw = localStorage.getItem("admin_dependencia_id");
  return raw && raw !== "null" ? Number(raw) : null;
}

function getAdminRole() {
  return localStorage.getItem("admin_role") || "";
}

function clearAdminToken() {
  localStorage.removeItem("admin_token");
  localStorage.removeItem("admin_display_name");
  localStorage.removeItem("admin_role");
  localStorage.removeItem("admin_dependencia_id");
}

async function adminFetch(url, options = {}) {
  const headers = { ...(options.headers || {}), Authorization: `Bearer ${getAdminToken()}` };
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401) {
    clearAdminToken();
    showAuthGate("Tu sesión expiró o no es válida. Inicia sesión de nuevo.");
    throw new Error("unauthorized");
  }
  return res;
}

function showAuthGate(errorMessage) {
  authGateEl.hidden = false;
  panelAppEl.hidden = true;
  if (errorMessage) {
    authErrorEl.textContent = errorMessage;
    authErrorEl.hidden = false;
  } else {
    authErrorEl.hidden = true;
  }
}

let dependenciasForReassign = [];

async function loadDependenciasForReassign() {
  try {
    const res = await adminFetch("/api/admin/dependencias");
    dependenciasForReassign = await res.json();
    reassignSelectEl.innerHTML = `
      <option value="" selected disabled>Redirigir a...</option>
      <option value="general">Administrador general</option>
      ${dependenciasForReassign.map((d) => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join("")}
    `;
  } catch {
    // si falla, el selector queda con solo la opción "Administrador general"; no bloquea el resto del panel.
  }
}

function formatAdminIdentityLabel() {
  const displayName = localStorage.getItem("admin_display_name") || "";
  const role = getAdminRole();
  let roleLabel = "";
  if (role === "general") {
    roleLabel = "Administrador general";
  } else if (role === "dependencia") {
    const dep = dependenciasForReassign.find((d) => d.id === getAdminDependenciaId());
    roleLabel = dep ? dep.name : "Administrador de dependencia";
  }
  return roleLabel ? `${displayName} · ${roleLabel}` : displayName;
}

async function tryEnterPanel() {
  try {
    await loadSessions();
    await loadDependenciasForReassign();
    adminDisplayNameEl.textContent = formatAdminIdentityLabel();
    // El root no llega a /panel (require_conversation_admin lo bloquea), así
    // que estas pestañas siempre aplican para quien sí logra entrar aquí:
    // general (paridad con root en documentos) o dependencia (solo lo suyo).
    dashboardTabButtonEl.hidden = false;
    documentsTabButtonEl.hidden = false;
    horarioTabButtonEl.hidden = false;
    await loadDashboard();
    await loadDocuments();
    await loadPanelHorario();
    // El detector de hostilidad es exclusivo del administrador general
    // (igual que recategorizar documentos) -- un administrador de
    // dependencia no ve ni puede tocar esta pestaña.
    if (getAdminRole() === "general") {
      moderacionTabButtonEl.hidden = false;
      await loadPanelHostilityKeywords();
      widgetTabButtonEl.hidden = false;
      await loadPanelWidgetOrigins();
    }
    authGateEl.hidden = true;
    panelAppEl.hidden = false;
    connectWebSocket();
  } catch {
    // adminFetch ya mostró el auth-gate con el mensaje de error si la sesión era inválida.
  }
}

// --- Pestañas ------------------------------------------------------------

document.querySelectorAll(".panel-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".panel-tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    document.querySelectorAll(".panel-tab-panel").forEach((p) => (p.hidden = true));
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

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function errorDetail(res) {
  const body = await res.json().catch(() => ({}));
  if (Array.isArray(body.detail)) {
    return body.detail.map((d) => d.msg).join(" ") || "Ocurrió un error.";
  }
  return body.detail || "Ocurrió un error.";
}

// --- Dashboard (pestaña): general ve agregado de todas las dependencias, dependencia solo lo suyo ---

let panelDashboardChart = null;

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
  return cards.map(([label, value]) => dashboardCardHtml(label, value)).join("");
}

function renderDashboardChart(dashboard) {
  const canvas = document.getElementById("panel-dashboard-conversations-chart");
  const trend = dashboard.conversations.daily_trend || [];

  if (panelDashboardChart) panelDashboardChart.destroy();
  panelDashboardChart = new Chart(canvas, {
    type: "line",
    data: {
      labels: trend.map((point) => point.date),
      datasets: [
        {
          label: "Conversaciones",
          data: trend.map((point) => point.count),
          borderColor: "#5b21b6",
          backgroundColor: "#5b21b626",
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
  });
}

function renderDashboardByDependenciaTable(dashboard) {
  const tbody = document.getElementById("panel-dashboard-by-dependencia-body");
  if (!tbody) return;
  const rows = dashboard.conversations.by_dependencia || [];
  tbody.innerHTML = rows.map((row) => `<tr><td>${escapeHtml(row.name)}</td><td>${row.total}</td></tr>`).join("");
}

function renderDashboardRecentDocumentsTable(dashboard) {
  const tbody = document.getElementById("panel-dashboard-recent-documents-body");
  const rows = dashboard.documents.recent || [];
  tbody.innerHTML = rows
    .map((row) => `<tr><td>${escapeHtml(row.filename)}</td><td>${formatTime(row.modified_at)}</td></tr>`)
    .join("");
}

async function loadDashboard() {
  const isGeneral = getAdminRole() === "general";
  let dashboard;
  try {
    const res = await adminFetch("/api/dashboard");
    dashboard = await res.json();
  } catch {
    return; // adminFetch ya maneja el caso de sesión inválida.
  }

  document.getElementById("panel-dashboard-title").textContent = isGeneral
    ? "Dashboard"
    : `Dashboard de ${dependenciaNameById(getAdminDependenciaId())}`;
  document.getElementById("panel-dashboard-cards").innerHTML = dashboardCardsHtml(dashboard);
  renderDashboardChart(dashboard);

  const byDependenciaCard = document.getElementById("panel-dashboard-by-dependencia-card");
  byDependenciaCard.hidden = !isGeneral;
  if (isGeneral) renderDashboardByDependenciaTable(dashboard);

  renderDashboardRecentDocumentsTable(dashboard);
}

// --- Documentos (pestaña, con modales solo para subir/vista previa): general con paridad de root, dependencia solo lo suyo ---

function dependenciaNameById(id) {
  const dep = dependenciasForReassign.find((d) => d.id === id);
  return dep ? dep.name : "—";
}

function documentDependenciaOptionsHtml(selectedId) {
  const generalOption = `<option value="" ${selectedId == null ? "selected" : ""}>General / compartido</option>`;
  const depOptions = dependenciasForReassign
    .map((d) => `<option value="${d.id}" ${d.id === selectedId ? "selected" : ""}>${escapeHtml(d.name)}</option>`)
    .join("");
  return generalOption + depOptions;
}

let allPanelDocuments = [];
let panelDocumentDependenciaFilter = "all"; // "all" | "general" | <dependencia_id numérico>

function panelDocumentMatchesDependenciaFilter(doc) {
  if (panelDocumentDependenciaFilter === "all") return true;
  if (panelDocumentDependenciaFilter === "general") return doc.dependencia_id == null;
  return doc.dependencia_id === Number(panelDocumentDependenciaFilter);
}

function renderPanelDocumentDependenciaChips(isGeneral) {
  const container = document.getElementById("panel-documents-dependencia-chips");
  if (!container) return;
  if (!isGeneral) {
    // Un administrador de dependencia solo ve sus propios documentos --
    // filtrar por dependencia no aporta nada, así que no se muestran chips.
    container.innerHTML = "";
    return;
  }
  const chips = [
    { value: "all", label: "Todos" },
    { value: "general", label: "General / compartido" },
    ...dependenciasForReassign.map((d) => ({ value: String(d.id), label: d.name })),
  ];
  container.innerHTML = chips
    .map(
      (chip) => `
        <button type="button" class="filter-chip ${panelDocumentDependenciaFilter === chip.value ? "active" : ""}" data-value="${chip.value}">
          ${escapeHtml(chip.label)}
        </button>
      `
    )
    .join("");
  container.querySelectorAll(".filter-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      panelDocumentDependenciaFilter = btn.dataset.value;
      renderPanelDocumentDependenciaChips(isGeneral);
      rerenderPanelDocumentsTable(isGeneral);
    });
  });
}

function buildPanelDocumentsRowsHtml(isGeneral) {
  const searchInput = document.getElementById("panel-documents-search");
  const query = searchInput ? searchInput.value.trim().toLowerCase() : "";
  const filtered = allPanelDocuments.filter(
    (doc) =>
      (!query || doc.filename.toLowerCase().includes(query)) &&
      (!isGeneral || panelDocumentMatchesDependenciaFilter(doc))
  );

  const emptyEl = document.getElementById("panel-documents-empty");
  if (emptyEl) {
    emptyEl.hidden = filtered.length > 0;
    emptyEl.textContent =
      allPanelDocuments.length === 0 ? "Todavía no hay documentos." : "Ningún documento coincide con la búsqueda.";
  }

  return filtered
    .map((doc) => {
      const nameCell = doc.archived_at
        ? `${escapeHtml(doc.filename)} <span class="archived-badge">Archivado</span>`
        : escapeHtml(doc.filename);

      if (doc.archived_at && isGeneral) {
        return `
          <tr>
            <td>${nameCell}</td>
            <td>${formatSize(doc.size_bytes)}</td>
            <td>${escapeHtml(dependenciaNameById(doc.dependencia_id))}</td>
            <td>${escapeHtml(doc.vigente_desde || "")}</td>
            <td>
              <div class="row-actions">
                <button type="button" class="reactivate-doc-button" data-filename="${escapeHtml(doc.filename)}">Reactivar</button>
              </div>
            </td>
          </tr>
        `;
      }

      const depCell = isGeneral ? `<td>${escapeHtml(dependenciaNameById(doc.dependencia_id))}</td>` : "";
      const recategorizeControl = isGeneral
        ? `<select class="doc-dependencia-select" data-filename="${escapeHtml(doc.filename)}">${documentDependenciaOptionsHtml(doc.dependencia_id)}</select>`
        : "";
      const vigenciaCell = isGeneral
        ? `<td><input type="date" class="doc-vigencia-input" data-filename="${escapeHtml(doc.filename)}" value="${doc.vigente_desde || ""}" title="Fecha desde la cual este documento aplica -- puede ser futura" /></td>`
        : "";
      const archiveControl = isGeneral
        ? `<button type="button" class="archive-doc-button" data-filename="${escapeHtml(doc.filename)}">Archivar</button>`
        : "";
      return `
        <tr>
          <td>${nameCell}</td>
          <td>${formatSize(doc.size_bytes)}</td>
          ${depCell}
          ${vigenciaCell}
          <td>
            <div class="row-actions">
              ${recategorizeControl}
              <button type="button" class="preview-doc-button" data-filename="${escapeHtml(doc.filename)}">Vista previa</button>
              ${archiveControl}
              <button type="button" class="danger delete-doc-button" data-filename="${escapeHtml(doc.filename)}">Eliminar</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

function rerenderPanelDocumentsTable(isGeneral) {
  const tbody = document.getElementById("panel-documents-table-body");
  if (!tbody) return;
  renderPanelDocumentDependenciaChips(isGeneral);
  tbody.innerHTML = buildPanelDocumentsRowsHtml(isGeneral);

  tbody.querySelectorAll(".preview-doc-button").forEach((button) => {
    button.addEventListener("click", () => previewPanelDocument(button.dataset.filename));
  });
  tbody.querySelectorAll(".delete-doc-button").forEach((button) => {
    button.addEventListener("click", () => deletePanelDocument(button.dataset.filename));
  });
  if (isGeneral) {
    tbody.querySelectorAll(".doc-dependencia-select").forEach((select) => {
      select.addEventListener("change", () => {
        const dependenciaId = select.value === "" ? null : Number(select.value);
        recategorizePanelDocument(select.dataset.filename, { dependenciaId });
      });
    });
    tbody.querySelectorAll(".doc-vigencia-input").forEach((input) => {
      input.addEventListener("change", () => {
        recategorizePanelDocument(input.dataset.filename, { vigenteDesde: input.value || null });
      });
    });
    tbody.querySelectorAll(".archive-doc-button").forEach((button) => {
      button.addEventListener("click", () => archivePanelDocument(button.dataset.filename));
    });
    tbody.querySelectorAll(".reactivate-doc-button").forEach((button) => {
      button.addEventListener("click", () => reactivatePanelDocument(button.dataset.filename));
    });
  }
}

async function loadDocuments() {
  const isGeneral = getAdminRole() === "general";
  try {
    const res = await adminFetch("/api/admin/documents");
    allPanelDocuments = await res.json();
  } catch {
    return; // adminFetch ya maneja el caso de sesión inválida.
  }

  document.getElementById("panel-documents-title").textContent = isGeneral
    ? "Documentos"
    : `Documentos de ${dependenciaNameById(getAdminDependenciaId())}`;
  document.getElementById("panel-documents-table-head").innerHTML = `
    <th>Archivo</th>
    <th>Tamaño</th>
    ${isGeneral ? "<th>Dependencia</th>" : ""}
    ${isGeneral ? "<th>Vigente desde</th>" : ""}
    <th></th>
  `;

  rerenderPanelDocumentsTable(isGeneral);
}

document.getElementById("panel-documents-search").addEventListener("input", () => rerenderPanelDocumentsTable(getAdminRole() === "general"));
document.getElementById("panel-new-document-button").addEventListener("click", openUploadDocumentModal);

const PANEL_IMAGE_EXTENSION_PATTERN = /\.(jpe?g|png|webp)$/i;

function openUploadDocumentModal() {
  const isGeneral = getAdminRole() === "general";
  const ownDependenciaName = dependenciaNameById(getAdminDependenciaId());
  openModal(`
    <h3>Subir documento</h3>
    <p class="modal-hint">Los PDF y Word se convierten automáticamente a texto plano al subirlos para la búsqueda -- el archivo original se conserva aparte para que los estudiantes puedan descargarlo. Las imágenes (afiches de eventos, talleres, etc.) también: se extrae el texto con IA para revisarlo antes de guardar.</p>
    ${
      isGeneral
        ? ""
        : `<p class="modal-hint">Se etiquetará automáticamente con tu dependencia: <strong>${escapeHtml(ownDependenciaName)}</strong>.</p>`
    }
    <form id="panel-upload-document-form" class="modal-form">
      <label>Archivo (PDF, TXT, DOCX, XLSX, JPG, PNG o WEBP)
        <input id="panel-upload-document-file" type="file" accept=".pdf,.txt,.docx,.xlsx,.jpg,.jpeg,.png,.webp" required />
      </label>
      ${
        isGeneral
          ? `<label>Dependencia (opcional)
              <select id="panel-upload-document-dependencia">${documentDependenciaOptionsHtml(null)}</select>
            </label>`
          : ""
      }
      <label>Vigente desde (opcional)
        <input id="panel-upload-document-vigencia" type="date" />
      </label>
      <p class="modal-hint">Solo para documentos que se reemplazan con el tiempo (calendarios, precios, etc.): si dos documentos responden la misma pregunta, gana el de fecha más reciente -- puede ser una fecha futura si ya se sabe que ese documento aplicará desde entonces. Déjalo vacío para documentos generales que no vencen.</p>
      <label>Nombre del archivo (opcional)
        <input id="panel-upload-document-desired-name" type="text" placeholder="Dejar vacío para usar el nombre original" maxlength="150" />
      </label>
      <p class="modal-hint">Para PDF/DOCX/imágenes -- útil cuando el archivo trae un nombre genérico (ej. una foto de WhatsApp). En imágenes con nombre genérico se sugiere uno automáticamente tras extraer el texto.</p>
      <p id="panel-upload-document-duplicate-warning" class="modal-error" hidden></p>
      <div id="panel-upload-document-extracted-container" hidden>
        <label>Texto extraído de la imagen (revísalo y corrígelo si hace falta)
          <textarea id="panel-upload-document-extracted-text" rows="8"></textarea>
        </label>
      </div>
      <p id="panel-upload-document-error" class="modal-error" hidden></p>
      <div class="modal-actions">
        <button type="button" class="cancel-button">Cancelar</button>
        <button type="submit" class="primary-button">Subir</button>
      </div>
    </form>
  `);

  const fileInput = document.getElementById("panel-upload-document-file");
  const extractedContainer = document.getElementById("panel-upload-document-extracted-container");
  const extractedTextarea = document.getElementById("panel-upload-document-extracted-text");
  const desiredNameInput = document.getElementById("panel-upload-document-desired-name");
  const duplicateWarningEl = document.getElementById("panel-upload-document-duplicate-warning");
  const submitButton = document.querySelector("#panel-upload-document-form button[type=submit]");
  let hasExtractedText = false;

  fileInput.addEventListener("change", () => {
    hasExtractedText = false;
    extractedContainer.hidden = true;
    extractedTextarea.value = "";
    desiredNameInput.value = "";
    duplicateWarningEl.hidden = true;
    submitButton.textContent = "Subir";
  });

  document.getElementById("panel-upload-document-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("panel-upload-document-error");
    const file = fileInput.files[0];
    if (!file) return;
    const isImage = PANEL_IMAGE_EXTENSION_PATTERN.test(file.name);

    errorEl.hidden = true;

    if (isImage && !hasExtractedText) {
      submitButton.disabled = true;
      submitButton.textContent = "Extrayendo texto...";
      try {
        const extractFormData = new FormData();
        extractFormData.append("file", file);
        const res = await adminFetch("/api/admin/documents/extract-image-text", { method: "POST", body: extractFormData });
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
    if (isGeneral) {
      const dependenciaValue = document.getElementById("panel-upload-document-dependencia").value;
      if (dependenciaValue) formData.append("dependencia_id", dependenciaValue);
    }
    // Si es administrador de dependencia, no se manda dependencia_id -- el
    // backend fuerza la suya siempre, ignorando cualquier otro valor.
    const vigenciaValue = document.getElementById("panel-upload-document-vigencia").value;
    if (vigenciaValue) formData.append("vigente_desde", vigenciaValue);
    if (isImage) formData.append("extracted_text", extractedTextarea.value);
    if (desiredNameInput.value.trim()) formData.append("desired_filename", desiredNameInput.value.trim());

    try {
      const res = await adminFetch("/api/admin/documents", { method: "POST", body: formData });
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
}

async function recategorizePanelDocument(filename, { dependenciaId, vigenteDesde } = {}) {
  // Cada PUT manda los dos campos siempre -- si solo se editó uno, el otro
  // se rellena con el valor actual del documento, para no borrarlo sin
  // querer (el backend reemplaza ambos, no hace merge parcial).
  const doc = allPanelDocuments.find((d) => d.filename === filename);
  const finalDependenciaId = dependenciaId !== undefined ? dependenciaId : doc?.dependencia_id ?? null;
  const finalVigenteDesde = vigenteDesde !== undefined ? vigenteDesde : doc?.vigente_desde || null;
  try {
    const res = await adminFetch(`/api/admin/documents/${encodeURIComponent(filename)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dependencia_id: finalDependenciaId, vigente_desde: finalVigenteDesde }),
    });
    if (!res.ok) alert(await errorDetail(res));
  } catch {
    // adminFetch ya maneja el caso de sesión inválida.
  } finally {
    await loadDocuments();
  }
}

async function deletePanelDocument(filename) {
  if (!confirm(`¿Eliminar "${filename}"? También se quita del índice.`)) return;
  try {
    const res = await adminFetch(`/api/admin/documents/${encodeURIComponent(filename)}`, { method: "DELETE" });
    if (!res.ok) {
      alert(await errorDetail(res));
      return;
    }
  } catch {
    // adminFetch ya maneja el caso de sesión inválida.
  } finally {
    await loadDocuments();
  }
}

async function archivePanelDocument(filename) {
  if (!confirm(`¿Archivar "${filename}"? Deja de responder preguntas hasta que lo reactives, pero el archivo se conserva.`)) return;
  try {
    const res = await adminFetch(`/api/admin/documents/${encodeURIComponent(filename)}/archive`, { method: "PUT" });
    if (!res.ok) alert(await errorDetail(res));
  } catch {
    // adminFetch ya maneja el caso de sesión inválida.
  } finally {
    await loadDocuments();
  }
}

async function reactivatePanelDocument(filename) {
  try {
    const res = await adminFetch(`/api/admin/documents/${encodeURIComponent(filename)}/reactivate`, { method: "PUT" });
    if (!res.ok) alert(await errorDetail(res));
  } catch {
    // adminFetch ya maneja el caso de sesión inválida.
  } finally {
    await loadDocuments();
  }
}

async function previewPanelDocument(filename) {
  openModal(`<h3>Vista previa: ${escapeHtml(filename)}</h3><p>Cargando...</p>`, { wide: true });
  try {
    const res = await adminFetch(`/api/admin/documents/${encodeURIComponent(filename)}/preview`);
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
    const downloadUrl = `/api/documents/${encodeURIComponent(data.filename)}/download?session_id=${encodeURIComponent("admin-" + getAdminToken())}`;
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
    // adminFetch ya maneja el caso de sesión inválida.
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
    setAdminSession({
      token: data.token,
      displayName: data.display_name,
      role: data.role,
      dependenciaId: data.dependencia_id,
    });
    await tryEnterPanel();
  } catch {
    showAuthGate("No se pudo conectar con el servidor, intenta de nuevo.");
  } finally {
    submitButton.disabled = false;
  }
});

logoutButtonEl.addEventListener("click", async () => {
  try {
    await adminFetch("/api/auth/logout", { method: "POST" });
  } catch {
    // si la sesión ya era inválida, adminFetch ya mostró el auth-gate.
  }
  clearAdminToken();
  showAuthGate();
});

let notificationAudioCtx = null;
function playNotificationSound() {
  try {
    if (!notificationAudioCtx) {
      notificationAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (notificationAudioCtx.state === "suspended") notificationAudioCtx.resume();

    const oscillator = notificationAudioCtx.createOscillator();
    const gain = notificationAudioCtx.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = 880;
    gain.gain.setValueAtTime(0.15, notificationAudioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, notificationAudioCtx.currentTime + 0.4);
    oscillator.connect(gain);
    gain.connect(notificationAudioCtx.destination);
    oscillator.start();
    oscillator.stop(notificationAudioCtx.currentTime + 0.4);
  } catch {
    // Web Audio no disponible o bloqueado por el navegador; se ignora.
  }
}

function formatTime(isoString) {
  try {
    return new Date(isoString).toLocaleString();
  } catch {
    return isoString;
  }
}

function truncate(text, maxLength) {
  const singleLine = (text || "").replace(/\s+/g, " ").trim();
  return singleLine.length > maxLength ? singleLine.slice(0, maxLength - 1) + "…" : singleLine;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function getSession(sessionId) {
  return sessions.find((s) => s.session_id === sessionId);
}

function formatElapsedMinutes(isoString) {
  if (!isoString) return null;
  const ms = Date.now() - new Date(isoString).getTime();
  return Math.max(0, Math.round(ms / 60000));
}

// Solo aplica al rol general (supervisor de todo): muestra a qué
// dependencia está asignada cada conversación y cuánto lleva esperando
// (o si ya fue atendida). Para un administrador de dependencia esta
// información no aporta nada -- su lista ya es solo lo suyo -- así que
// devuelve cadena vacía y no se renderiza nada.
function dependenciaStatusText(session) {
  if (getAdminRole() !== "general") return "";
  const dep = dependenciasForReassign.find((d) => d.id === session.dependencia_id);
  const depName = session.dependencia_id == null ? "Administrador general" : dep ? dep.name : "Dependencia eliminada";
  if (!session.needs_human) return depName;
  if (session.first_response_at) return `${depName} — atendido`;
  const minutes = formatElapsedMinutes(session.dependencia_assigned_at);
  return minutes === null ? depName : `${depName} — esperando ${minutes} min`;
}

function renderSessionList() {
  sessionCountEl.textContent = `${totalSessionsCount} conversación${totalSessionsCount === 1 ? "" : "es"}`;

  pendingChipEl.hidden = pendingCount === 0 && !filterPending;
  pendingChipEl.textContent = `${pendingCount} pendiente${pendingCount === 1 ? "" : "s"}`;
  pendingChipEl.classList.toggle("active", filterPending);

  sessionListEl.innerHTML = "";
  for (const session of sessions) {
    const li = document.createElement("li");
    li.className = "session-item" + (session.session_id === activeSessionId ? " active" : "");
    li.dataset.sessionId = session.session_id;
    li.innerHTML = `
      <div class="session-id-row">
        <div class="session-id">${escapeHtml(session.student_name || session.session_id)}</div>
        ${session.needs_human ? '<span class="pending-dot" title="Necesita atención humana"></span>' : ""}
      </div>
      <div class="session-preview">${escapeHtml(truncate(session.last_message, 70))}</div>
      <div class="session-meta">
        <span>${session.turn_count} mensaje${session.turn_count === 1 ? "" : "s"}</span>
        <span>${formatTime(session.last_active)}</span>
      </div>
      ${dependenciaStatusText(session) ? `<div class="session-dependencia-status">${escapeHtml(dependenciaStatusText(session))}</div>` : ""}
    `;
    li.addEventListener("click", () => selectSession(session.session_id));
    sessionListEl.appendChild(li);
  }
}

async function fetchSessionsPage({ reset = false } = {}) {
  if (sessionsLoading) return;
  if (!reset && !sessionsHasMore) return;
  if (reset) {
    sessionsOffset = 0;
    sessionsHasMore = true;
  }

  sessionsLoading = true;
  try {
    const params = new URLSearchParams({ offset: String(sessionsOffset), limit: String(PAGE_SIZE) });
    if (filterPending) params.set("needs_human_only", "true");
    const res = await adminFetch(`/api/admin/sessions?${params.toString()}`);
    const data = await res.json();

    if (reset) {
      sessions = data.sessions;
    } else {
      const existingIds = new Set(sessions.map((s) => s.session_id));
      for (const s of data.sessions) {
        if (!existingIds.has(s.session_id)) sessions.push(s);
      }
    }
    totalSessionsCount = data.total;
    pendingCount = data.pending_count;
    sessionsHasMore = filterPending ? false : sessionsOffset + data.sessions.length < data.total;
    sessionsOffset += data.sessions.length;
    renderSessionList();
  } finally {
    sessionsLoading = false;
  }
}

async function loadSessions() {
  await fetchSessionsPage({ reset: true });
}

function isNearBottom(el, threshold = 150) {
  return el.scrollTop + el.clientHeight >= el.scrollHeight - threshold;
}

sessionListEl.addEventListener("scroll", () => {
  if (filterPending) return; // el filtro de pendientes ya trae todas de una vez, sin paginar
  if (isNearBottom(sessionListEl)) {
    fetchSessionsPage({ reset: false }).catch(() => {
      // adminFetch ya maneja el caso de token inválido mostrando el auth-gate.
    });
  }
});

function updateReplyUiForActiveSession() {
  const session = getSession(activeSessionId);
  const needsHuman = Boolean(session && session.needs_human);
  // El general ve cualquier conversación escalada, pero solo puede
  // responder/resolver la que ya tiene asignada (la suya es
  // dependencia_id === null, igual que cualquier administrador de
  // dependencia con la suya) -- debe reclamarla primero con "Redirigir a...".
  // Para un administrador de dependencia esto siempre es true sobre lo que
  // ve, ya que su lista viene filtrada por el backend a solo lo suyo.
  const canAct = Boolean(session) && session.dependencia_id === getAdminDependenciaId();
  resolveButtonEl.hidden = !(needsHuman && canAct);
  askContinueButtonEl.hidden = !(needsHuman && canAct);
  advisorReplyFormEl.hidden = !(needsHuman && canAct);
  askBotPanelEl.hidden = !(needsHuman && canAct);
  reassignSelectEl.hidden = !needsHuman;
}

function updateConversationHeader(sessionId) {
  const session = getSession(sessionId);
  conversationTitleEl.textContent = (session && session.student_name) || sessionId;

  const parts = [];
  if (session && session.student_email) parts.push(session.student_email);
  if (session && session.student_phone) parts.push(session.student_phone);
  if (session && session.needs_human) {
    parts.push(session.is_connected ? "🟢 En línea ahora" : "⚪ Sin conexión — contáctalo por correo/teléfono");
  }
  const depStatus = session ? dependenciaStatusText(session) : "";
  if (depStatus) parts.push(depStatus);

  if (parts.length > 0) {
    conversationSubtitleEl.textContent = parts.join(" · ");
    conversationSubtitleEl.hidden = false;
  } else {
    conversationSubtitleEl.hidden = true;
  }
}

function findEscalationTriggerIndex(messages, escalatedAt) {
  if (!escalatedAt) return -1;
  let bestIndex = -1;
  for (let i = 0; i < messages.length - 1; i++) {
    const isTurnPair =
      messages[i].sender === "student" &&
      messages[i + 1].sender === "assistant" &&
      messages[i].created_at === messages[i + 1].created_at;
    if (isTurnPair && messages[i].created_at <= escalatedAt) {
      bestIndex = i;
    }
  }
  return bestIndex;
}

const MESSAGE_PAGE_SIZE = 50;
let conversationHasMoreOlder = false;
let conversationNextCursor = null;

async function selectSession(sessionId) {
  activeSessionId = sessionId;
  renderSessionList();

  conversationEmptyEl.hidden = true;
  conversationHeaderEl.hidden = false;
  panelBodyEl.classList.add("showing-conversation");
  updateReplyUiForActiveSession();
  updateConversationHeader(sessionId);

  conversationMessagesEl.innerHTML = "";
  conversationHasMoreOlder = false;
  conversationNextCursor = null;

  // Limpiar cualquier borrador del asistente de la conversación anterior --
  // no debe arrastrarse de una conversación a otra.
  askBotResultEl.hidden = true;
  askBotInputEl.value = "";

  const res = await adminFetch(`/api/admin/sessions/${encodeURIComponent(sessionId)}/messages?limit=${MESSAGE_PAGE_SIZE}`);
  const data = await res.json();
  if (sessionId !== activeSessionId) return; // el usuario cambió de conversación mientras cargaba

  const session = getSession(sessionId);
  const triggerIndex = findEscalationTriggerIndex(data.messages, session && session.escalated_at);

  data.messages.forEach((m, index) => {
    appendMessageToView(m.sender, m.message, m.created_at, index === triggerIndex);
  });

  // Prellenar la herramienta de "preguntar al asistente" con la última
  // pregunta real del estudiante -- el asesor la edita/mejora en vez de
  // transcribirla de cero.
  const lastStudentMessage = [...data.messages].reverse().find((m) => m.sender === "student");
  askBotInputEl.value = lastStudentMessage ? lastStudentMessage.message : "";

  conversationHasMoreOlder = data.has_more;
  conversationNextCursor = data.next_cursor;
  ensureLoadOlderButton();

  conversationMessagesEl.scrollTop = conversationMessagesEl.scrollHeight;
}

async function loadOlderMessages() {
  if (!conversationHasMoreOlder || !conversationNextCursor) return;
  const sessionIdAtRequest = activeSessionId;
  const btn = conversationMessagesEl.querySelector(".load-older-button");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Cargando...";
  }
  try {
    const params = new URLSearchParams({ before: conversationNextCursor, limit: String(MESSAGE_PAGE_SIZE) });
    const res = await adminFetch(`/api/admin/sessions/${encodeURIComponent(sessionIdAtRequest)}/messages?${params.toString()}`);
    const data = await res.json();
    if (sessionIdAtRequest !== activeSessionId) return; // cambió de conversación mientras cargaba

    const previousScrollHeight = conversationMessagesEl.scrollHeight;
    if (btn) btn.remove();

    prependMessagesToView(data.messages);

    conversationHasMoreOlder = data.has_more;
    conversationNextCursor = data.next_cursor;
    ensureLoadOlderButton();

    // Mantiene la posición visual del usuario tras insertar contenido arriba.
    conversationMessagesEl.scrollTop = conversationMessagesEl.scrollHeight - previousScrollHeight;
  } finally {
    const stillThere = conversationMessagesEl.querySelector(".load-older-button");
    if (stillThere) {
      stillThere.disabled = false;
      stillThere.textContent = "Cargar mensajes anteriores";
    }
  }
}

function ensureLoadOlderButton() {
  const existing = conversationMessagesEl.querySelector(".load-older-button");
  if (!conversationHasMoreOlder) {
    if (existing) existing.remove();
    return;
  }
  if (existing) return;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "load-older-button";
  btn.textContent = "Cargar mensajes anteriores";
  btn.addEventListener("click", loadOlderMessages);
  conversationMessagesEl.prepend(btn);
}

function buildMessageElement(sender, message, createdAt, isEscalationTrigger) {
  const div = document.createElement("div");
  div.className = `message ${sender}` + (isEscalationTrigger ? " escalation-trigger" : "");
  div.innerHTML = `
    <span class="message-label-row">
      <span class="message-label">${SENDER_LABELS[sender] || sender}</span>
      ${isEscalationTrigger ? '<span class="pending-dot" title="Disparó la solicitud de atención humana"></span>' : ""}
    </span>
    <div class="message-text"></div>
    <span class="message-time"></span>
  `;
  const textEl = div.querySelector(".message-text");
  if (sender === "student") {
    textEl.textContent = message;
  } else {
    textEl.innerHTML = renderMarkdownHtml(message);
  }
  div.querySelector(".message-time").textContent = formatTime(createdAt);
  return div;
}

function appendMessageToView(sender, message, createdAt, isEscalationTrigger) {
  conversationMessagesEl.appendChild(buildMessageElement(sender, message, createdAt, isEscalationTrigger));
}

function prependMessagesToView(messages) {
  const fragment = document.createDocumentFragment();
  messages.forEach((m) => fragment.appendChild(buildMessageElement(m.sender, m.message, m.created_at, false)));
  conversationMessagesEl.insertBefore(fragment, conversationMessagesEl.firstChild);
}

function flashSessionRow(sessionId) {
  const row = sessionListEl.querySelector(`[data-session-id="${CSS.escape(sessionId)}"]`);
  if (row) {
    row.classList.add("flash");
    setTimeout(() => row.classList.remove("flash"), 1200);
  }
}

function touchSession(
  sessionId,
  {
    lastActive,
    lastMessage,
    needsHuman,
    incrementTurns,
    studentName,
    studentEmail,
    escalatedAt,
    dependenciaId,
    dependenciaAssignedAt,
    firstResponseAt,
  }
) {
  let session = getSession(sessionId);
  const isNew = !session;
  if (isNew) {
    session = { session_id: sessionId, last_active: lastActive, turn_count: 0, last_message: lastMessage, needs_human: false };
    sessions.push(session);
    if (!filterPending) totalSessionsCount += 1;
  }
  const wasPending = session.needs_human;
  session.last_active = lastActive;
  if (lastMessage !== undefined) session.last_message = lastMessage;
  if (needsHuman !== undefined) session.needs_human = needsHuman;
  if (incrementTurns) session.turn_count += 1;
  if (studentName !== undefined) session.student_name = studentName;
  if (studentEmail !== undefined) session.student_email = studentEmail;
  if (escalatedAt !== undefined) session.escalated_at = escalatedAt;
  if (dependenciaId !== undefined) session.dependencia_id = dependenciaId;
  if (dependenciaAssignedAt !== undefined) session.dependencia_assigned_at = dependenciaAssignedAt;
  if (firstResponseAt !== undefined) session.first_response_at = firstResponseAt;

  if (needsHuman !== undefined && needsHuman !== wasPending) {
    pendingCount += needsHuman ? 1 : -1;
  }

  if (filterPending && !session.needs_human) {
    // Con el filtro de pendientes activo, una sesión que ya no lo es
    // desaparece de la vista (fue resuelta o nunca lo fue).
    sessions = sessions.filter((s) => s.session_id !== sessionId);
  } else {
    sessions.sort((a, b) => (a.last_active < b.last_active ? 1 : -1));
  }
  renderSessionList();
  if (sessionId === activeSessionId) {
    updateReplyUiForActiveSession();
    updateConversationHeader(sessionId);
  }
  flashSessionRow(sessionId);
}

let panelWs = null;

function connectWebSocket() {
  if (panelWs && (panelWs.readyState === WebSocket.OPEN || panelWs.readyState === WebSocket.CONNECTING)) return;

  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocol}//${location.host}/api/ws/panel?token=${encodeURIComponent(getAdminToken())}`);
  panelWs = ws;

  ws.onopen = () => {
    wsStatusEl.textContent = "En vivo";
    wsStatusEl.classList.remove("offline");
  };

  ws.onclose = () => {
    if (panelWs === ws) panelWs = null;
    wsStatusEl.textContent = "Desconectado";
    wsStatusEl.classList.add("offline");
    if (getAdminToken()) setTimeout(connectWebSocket, 3000);
  };

  ws.onerror = () => ws.close();

  ws.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch {
      return;
    }

    if (data.type === "escalated") {
      touchSession(data.session_id, {
        lastActive: data.escalated_at,
        needsHuman: true,
        studentName: data.student_name,
        studentEmail: data.student_email,
        escalatedAt: data.escalated_at,
        dependenciaId: data.dependencia_id,
        dependenciaAssignedAt: data.escalated_at,
        firstResponseAt: null,
      });
      playNotificationSound();
    } else if (data.type === "student_message") {
      touchSession(data.session_id, { lastActive: data.created_at, lastMessage: data.message });
      if (data.session_id === activeSessionId) {
        appendMessageToView("student", data.message, data.created_at);
        conversationMessagesEl.scrollTop = conversationMessagesEl.scrollHeight;
      }
      playNotificationSound();
    } else if (data.type === "advisor_message") {
      touchSession(data.session_id, { lastActive: data.created_at, lastMessage: data.message });
      if (data.session_id === activeSessionId) {
        appendMessageToView("advisor", data.message, data.created_at);
        conversationMessagesEl.scrollTop = conversationMessagesEl.scrollHeight;
      }
    } else if (data.type === "resolved") {
      touchSession(data.session_id, { lastActive: data.resolved_at, needsHuman: false });
    } else if (data.type === "reassigned") {
      if (getAdminRole() === "general") {
        // El general ve todo, sin importar la dependencia: la conversación
        // nunca desaparece de su lista, solo cambia de dueño.
        const session = getSession(data.session_id);
        if (session) {
          session.dependencia_id = data.dependencia_id;
          session.dependencia_assigned_at = data.dependencia_assigned_at;
          session.first_response_at = null;
          renderSessionList();
          if (data.session_id === activeSessionId) updateReplyUiForActiveSession();
        } else {
          loadSessions();
        }
      } else if (data.dependencia_id === getAdminDependenciaId()) {
        // Ahora pertenece a mi bandeja: recargar para traerla con sus datos completos.
        loadSessions();
        playNotificationSound();
      } else {
        // Ya no me pertenece (yo la redirigí, o me la quitaron).
        sessions = sessions.filter((s) => s.session_id !== data.session_id);
        if (activeSessionId === data.session_id) {
          activeSessionId = null;
          conversationHeaderEl.hidden = true;
          conversationEmptyEl.hidden = false;
          panelBodyEl.classList.remove("showing-conversation");
        }
        renderSessionList();
      }
    }
  };
}

pendingChipEl.addEventListener("click", async () => {
  filterPending = !filterPending;
  try {
    await fetchSessionsPage({ reset: true });
  } catch {
    // adminFetch ya maneja el caso de token inválido mostrando el auth-gate.
  }
});

backToListButton.addEventListener("click", () => {
  panelBodyEl.classList.remove("showing-conversation");
});

resolveButtonEl.addEventListener("click", async () => {
  if (!activeSessionId) return;
  resolveButtonEl.disabled = true;
  try {
    await adminFetch(`/api/admin/sessions/${encodeURIComponent(activeSessionId)}/resolve`, { method: "POST" });
  } catch {
    // adminFetch ya maneja el caso de token inválido mostrando el auth-gate.
  } finally {
    resolveButtonEl.disabled = false;
  }
});

reassignSelectEl.addEventListener("change", async (e) => {
  const value = e.target.value;
  if (!value || !activeSessionId) return;
  const dependenciaId = value === "general" ? null : Number(value);
  const sessionId = activeSessionId;
  reassignSelectEl.disabled = true;
  try {
    await adminFetch(`/api/admin/sessions/${encodeURIComponent(sessionId)}/reassign`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dependencia_id: dependenciaId }),
    });
    // La propia conexión de este admin también recibe el evento "reassigned"
    // por WebSocket (se transmite a la dependencia vieja, la suya), que ya
    // se encarga de sacar la conversación de su lista si corresponde.
  } catch {
    // adminFetch ya maneja el caso de sesión inválida.
  } finally {
    reassignSelectEl.value = "";
    reassignSelectEl.disabled = false;
  }
});

askContinueButtonEl.addEventListener("click", async () => {
  if (!activeSessionId) return;
  askContinueButtonEl.disabled = true;
  try {
    await adminFetch(`/api/admin/sessions/${encodeURIComponent(activeSessionId)}/ask-continue`, { method: "POST" });
  } catch {
    // adminFetch ya maneja el caso de token inválido mostrando el auth-gate.
  } finally {
    askContinueButtonEl.disabled = false;
  }
});

advisorReplyFormEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = advisorReplyInputEl.value.trim();
  if (!message || !activeSessionId) return;

  advisorReplyInputEl.value = "";
  await adminFetch(`/api/admin/sessions/${encodeURIComponent(activeSessionId)}/reply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
});

// Se guarda aparte del DOM (en vez de leer askBotAnswerEl.textContent) porque
// ese elemento ahora contiene el markdown ya renderizado a HTML -- su
// textContent pierde la sintaxis original (**negrita**, tablas con "|"), que
// es justo lo que se quiere conservar al copiarla a la respuesta del asesor.
let lastAskBotAnswerRaw = "";

askBotFormEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = askBotInputEl.value.trim();
  if (!question || !activeSessionId) return;

  const submitButton = askBotFormEl.querySelector("button[type=submit]");
  submitButton.disabled = true;
  askBotResultEl.hidden = true;
  try {
    const res = await adminFetch(`/api/admin/sessions/${encodeURIComponent(activeSessionId)}/ask-bot`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      lastAskBotAnswerRaw = err.detail || "No se pudo consultar al asistente, intenta de nuevo.";
      askBotAnswerEl.textContent = lastAskBotAnswerRaw;
      askBotSourcesEl.textContent = "";
      askBotResultEl.hidden = false;
      return;
    }
    const data = await res.json();
    lastAskBotAnswerRaw = data.answer;
    askBotAnswerEl.innerHTML = renderMarkdownHtml(data.answer);
    askBotSourcesEl.textContent = data.has_sufficient_info
      ? (data.sources || []).map((s) => `${s.document} (pág. ${s.page})`).join(" · ")
      : "El asistente no encontró suficiente información en la documentación -- revisa si igual sirve, o escribe la respuesta tú mismo.";
    askBotResultEl.hidden = false;
  } catch {
    // adminFetch ya maneja el caso de token inválido mostrando el auth-gate.
  } finally {
    submitButton.disabled = false;
  }
});

askBotUseButtonEl.addEventListener("click", () => {
  advisorReplyInputEl.value = lastAskBotAnswerRaw;
  advisorReplyInputEl.focus();
  askBotResultEl.hidden = true;
});

askBotDiscardButtonEl.addEventListener("click", () => {
  askBotResultEl.hidden = true;
});

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible" || !getAdminToken() || authGateEl.hidden === false) return;
  // El navegador puede congelar el WebSocket en segundo plano (ahorro de
  // batería en móviles) sin disparar "onclose"; al volver a la pestaña se
  // refresca la lista por si se perdieron eventos, y se reconecta si hace
  // falta (connectWebSocket ya evita duplicar una conexión viva).
  loadSessions();
  connectWebSocket();
});

// --- Moderación: detector de hostilidad -----------------------------------

async function loadPanelHostilityKeywords() {
  const res = await adminFetch("/api/admin/hostility-keywords");
  const keywords = await res.json();
  renderPanelHostilityKeywordsTable(keywords);
}

function renderPanelHostilityKeywordsTable(keywords) {
  const tbody = document.getElementById("panel-hostility-keywords-table-body");
  const emptyEl = document.getElementById("panel-hostility-keywords-empty");
  tbody.innerHTML = "";
  emptyEl.hidden = keywords.length > 0;

  for (const keyword of keywords) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(keyword.phrase)}</td>
      <td>
        <div class="row-actions">
          <button type="button" class="danger delete-hostility-keyword-button">Eliminar</button>
        </div>
      </td>
    `;
    tr.querySelector(".delete-hostility-keyword-button").addEventListener("click", () => deletePanelHostilityKeyword(keyword));
    tbody.appendChild(tr);
  }
}

document.getElementById("panel-new-hostility-keyword-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("panel-new-hostility-keyword-input");
  const errorEl = document.getElementById("panel-hostility-keyword-error");
  const phrase = input.value.trim();
  if (!phrase) return;

  errorEl.hidden = true;
  try {
    const res = await adminFetch("/api/admin/hostility-keywords", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phrase }),
    });
    if (!res.ok) {
      errorEl.textContent = await errorDetail(res);
      errorEl.hidden = false;
      return;
    }
    input.value = "";
    await loadPanelHostilityKeywords();
  } catch {
    // adminFetch ya maneja el caso de sesión inválida.
  }
});

async function deletePanelHostilityKeyword(keyword) {
  if (!confirm(`¿Eliminar "${keyword.phrase}" de la lista de hostilidad?`)) return;
  try {
    const res = await adminFetch(`/api/admin/hostility-keywords/${keyword.id}`, { method: "DELETE" });
    if (!res.ok) alert(await errorDetail(res));
    await loadPanelHostilityKeywords();
  } catch {
    // adminFetch ya maneja el caso de sesión inválida.
  }
}

// --- Widget embebible: orígenes permitidos --------------------------------

async function loadPanelWidgetOrigins() {
  const res = await adminFetch("/api/admin/widget-origins");
  const origins = await res.json();
  renderPanelWidgetOriginsTable(origins);
  document.getElementById("panel-widget-snippet-code").textContent =
    `<script src="${location.origin}/static/widget-loader.js"></scr` + `ipt>`;
}

function renderPanelWidgetOriginsTable(origins) {
  const tbody = document.getElementById("panel-widget-origins-table-body");
  const emptyEl = document.getElementById("panel-widget-origins-empty");
  tbody.innerHTML = "";
  emptyEl.hidden = origins.length > 0;

  for (const origin of origins) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(origin.origin)}</td>
      <td>
        <div class="row-actions">
          <button type="button" class="danger delete-widget-origin-button">Eliminar</button>
        </div>
      </td>
    `;
    tr.querySelector(".delete-widget-origin-button").addEventListener("click", () => deletePanelWidgetOrigin(origin));
    tbody.appendChild(tr);
  }
}

document.getElementById("panel-new-widget-origin-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("panel-new-widget-origin-input");
  const errorEl = document.getElementById("panel-widget-origin-error");
  const origin = input.value.trim();
  if (!origin) return;

  errorEl.hidden = true;
  try {
    const res = await adminFetch("/api/admin/widget-origins", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ origin }),
    });
    if (!res.ok) {
      errorEl.textContent = await errorDetail(res);
      errorEl.hidden = false;
      return;
    }
    input.value = "";
    await loadPanelWidgetOrigins();
  } catch {
    // adminFetch ya maneja el caso de sesión inválida.
  }
});

async function deletePanelWidgetOrigin(origin) {
  if (!confirm(`¿Quitar "${origin.origin}" de los sitios permitidos para embeber el widget?`)) return;
  try {
    const res = await adminFetch(`/api/admin/widget-origins/${origin.id}`, { method: "DELETE" });
    if (!res.ok) alert(await errorDetail(res));
    await loadPanelWidgetOrigins();
  } catch {
    // adminFetch ya maneja el caso de sesión inválida.
  }
}

// --- Horario de atención ---------------------------------------------------

const PANEL_HORARIO_DIA_LABELS = { 1: "Lun", 2: "Mar", 3: "Mié", 4: "Jue", 5: "Vie", 6: "Sáb", 7: "Dom" };

function panelHorarioRangoRowHtml(inicio, fin) {
  return `
    <div class="horario-rango-row">
      <input type="time" class="horario-rango-inicio" value="${inicio || ""}" required />
      <span>a</span>
      <input type="time" class="horario-rango-fin" value="${fin || ""}" required />
      <button type="button" class="danger remove-rango-button">Quitar</button>
    </div>
  `;
}

function panelHorarioFormHtml(dep) {
  const diasActuales = new Set(dep.horario_dias || []);
  const rangosActuales = dep.horario_rangos && dep.horario_rangos.length ? dep.horario_rangos : [["", ""]];
  return `
    <form id="panel-horario-form" class="modal-form" data-dependencia-id="${dep.id}">
      <label>Días de atención</label>
      <div class="horario-dias-checks">
        ${Object.entries(PANEL_HORARIO_DIA_LABELS)
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
      <div id="panel-horario-rangos-list">
        ${rangosActuales.map(([inicio, fin]) => panelHorarioRangoRowHtml(inicio, fin)).join("")}
      </div>
      <button type="button" id="panel-add-horario-rango-button" class="modal-secondary-button">+ Agregar bloque</button>
      <p id="panel-horario-form-error" class="modal-error" hidden></p>
      <div class="modal-actions">
        <button type="submit" class="primary-button">Guardar</button>
      </div>
    </form>
  `;
}

function wirePanelHorarioForm(onSaved) {
  const form = document.getElementById("panel-horario-form");
  const rangosListEl = document.getElementById("panel-horario-rangos-list");
  const wireRemoveButtons = () => {
    rangosListEl.querySelectorAll(".remove-rango-button").forEach((btn) => {
      btn.onclick = () => {
        if (rangosListEl.children.length > 1) btn.closest(".horario-rango-row").remove();
      };
    });
  };
  wireRemoveButtons();

  document.getElementById("panel-add-horario-rango-button").addEventListener("click", () => {
    rangosListEl.insertAdjacentHTML("beforeend", panelHorarioRangoRowHtml("", ""));
    wireRemoveButtons();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("panel-horario-form-error");
    errorEl.hidden = true;

    const dias = Array.from(form.querySelectorAll(".horario-dia-check input:checked")).map((el) => Number(el.value));
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
      const dependenciaId = form.dataset.dependenciaId;
      const res = await adminFetch(`/api/admin/dependencias/${dependenciaId}/horario`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dias, rangos }),
      });
      if (!res.ok) throw new Error(await errorDetail(res));
      await onSaved();
    } catch (err) {
      errorEl.textContent = err.message || "No se pudo guardar, intenta de nuevo.";
      errorEl.hidden = false;
    }
  });
}

async function loadPanelHorario() {
  const contentEl = document.getElementById("panel-horario-content");
  if (getAdminRole() === "dependencia") {
    const dep = dependenciasForReassign.find((d) => d.id === getAdminDependenciaId());
    if (!dep) {
      contentEl.innerHTML = "<p class=\"empty-hint\">No se encontró tu dependencia.</p>";
      return;
    }
    contentEl.innerHTML = panelHorarioFormHtml(dep);
    wirePanelHorarioForm(async () => {
      await loadDependenciasForReassign();
      await loadPanelHorario();
    });
    return;
  }

  // general: tabla con todas las dependencias, cada una editable.
  const rows = dependenciasForReassign
    .map(
      (dep) => `
        <tr>
          <td>${escapeHtml(dep.name)}</td>
          <td>
            <div class="row-actions">
              <button type="button" class="edit-horario-button" data-id="${dep.id}">Editar horario</button>
            </div>
          </td>
        </tr>
      `
    )
    .join("");
  contentEl.innerHTML = `
    <table class="data-table">
      <thead><tr><th>Dependencia</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="empty-hint" ${dependenciasForReassign.length ? "hidden" : ""}>No hay dependencias configuradas.</p>
  `;
  contentEl.querySelectorAll(".edit-horario-button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const dep = dependenciasForReassign.find((d) => d.id === Number(btn.dataset.id));
      openModal(`<h3>Horario de atención — ${escapeHtml(dep.name)}</h3>${panelHorarioFormHtml(dep)}`);
      wirePanelHorarioForm(async () => {
        closeModal();
        await loadDependenciasForReassign();
        await loadPanelHorario();
      });
    });
  });
}

if (getAdminToken()) {
  tryEnterPanel();
} else {
  showAuthGate();
}
