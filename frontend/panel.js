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
const documentsButtonEl = document.getElementById("documents-button");
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
    // que este botón siempre aplica para quien sí logra entrar aquí: general
    // (paridad con root en documentos) o dependencia (solo los suyos).
    documentsButtonEl.hidden = false;
    authGateEl.hidden = true;
    panelAppEl.hidden = false;
    connectWebSocket();
  } catch {
    // adminFetch ya mostró el auth-gate con el mensaje de error si la sesión era inválida.
  }
}

// --- Modal genérico ------------------------------------------------------

function openModal(html) {
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

// --- Documentos (modal): general con paridad de root, dependencia solo lo suyo ---

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

async function openDocumentsModal() {
  const isGeneral = getAdminRole() === "general";
  let documents = [];
  try {
    const res = await adminFetch("/api/admin/documents");
    documents = await res.json();
  } catch {
    return; // adminFetch ya maneja el caso de sesión inválida.
  }

  const rowsHtml = documents
    .map((doc) => {
      const depCell = isGeneral ? `<td>${escapeHtml(dependenciaNameById(doc.dependencia_id))}</td>` : "";
      const recategorizeControl = isGeneral
        ? `<select class="doc-dependencia-select" data-filename="${escapeHtml(doc.filename)}">${documentDependenciaOptionsHtml(doc.dependencia_id)}</select>`
        : "";
      return `
        <tr>
          <td>${escapeHtml(doc.filename)}</td>
          <td>${formatSize(doc.size_bytes)}</td>
          ${depCell}
          <td>
            <div class="row-actions">
              ${recategorizeControl}
              <button type="button" class="danger delete-doc-button" data-filename="${escapeHtml(doc.filename)}">Eliminar</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");

  openModal(`
    <div class="panel-section-header">
      <h3>Documentos${isGeneral ? "" : " de tu dependencia"}</h3>
      <button type="button" id="panel-new-document-button" class="primary-button">+ Subir documento</button>
    </div>
    <table class="data-table">
      <thead>
        <tr>
          <th>Archivo</th>
          <th>Tamaño</th>
          ${isGeneral ? "<th>Dependencia</th>" : ""}
          <th></th>
        </tr>
      </thead>
      <tbody id="panel-documents-table-body">${rowsHtml}</tbody>
    </table>
    <p id="panel-documents-empty" class="empty-hint" ${documents.length ? "hidden" : ""}>Todavía no hay documentos.</p>
    <div class="modal-actions">
      <button type="button" class="cancel-button">Cerrar</button>
    </div>
  `);

  modalContentEl.querySelectorAll(".delete-doc-button").forEach((button) => {
    button.addEventListener("click", () => deletePanelDocument(button.dataset.filename));
  });
  if (isGeneral) {
    modalContentEl.querySelectorAll(".doc-dependencia-select").forEach((select) => {
      select.addEventListener("change", () => recategorizePanelDocument(select.dataset.filename, select));
    });
  }

  document.getElementById("panel-new-document-button").addEventListener("click", openUploadDocumentModal);
}

function openUploadDocumentModal() {
  const isGeneral = getAdminRole() === "general";
  openModal(`
    <h3>Subir documento</h3>
    <form id="panel-upload-document-form" class="modal-form">
      <label>Archivo (PDF, TXT, DOCX o XLSX)
        <input id="panel-upload-document-file" type="file" accept=".pdf,.txt,.docx,.xlsx" required />
      </label>
      ${
        isGeneral
          ? `<label>Dependencia (opcional)
              <select id="panel-upload-document-dependencia">${documentDependenciaOptionsHtml(null)}</select>
            </label>`
          : ""
      }
      <p id="panel-upload-document-error" class="modal-error" hidden></p>
      <div class="modal-actions">
        <button type="button" class="cancel-button">Cancelar</button>
        <button type="submit" class="primary-button">Subir</button>
      </div>
    </form>
  `);

  document.getElementById("panel-upload-document-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("panel-upload-document-error");
    const fileInput = document.getElementById("panel-upload-document-file");
    const file = fileInput.files[0];
    if (!file) return;

    const submitButton = e.target.querySelector("button[type=submit]");
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

    try {
      const res = await adminFetch("/api/admin/documents", { method: "POST", body: formData });
      if (!res.ok) throw new Error(await errorDetail(res));
      await openDocumentsModal();
    } catch (err) {
      errorEl.textContent = err.message || "No se pudo subir el documento.";
      errorEl.hidden = false;
      submitButton.disabled = false;
      submitButton.textContent = "Subir";
    }
  });
}

async function recategorizePanelDocument(filename, selectEl) {
  const dependenciaId = selectEl.value === "" ? null : Number(selectEl.value);
  selectEl.disabled = true;
  try {
    const res = await adminFetch(`/api/admin/documents/${encodeURIComponent(filename)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dependencia_id: dependenciaId }),
    });
    if (!res.ok) alert(await errorDetail(res));
  } catch {
    // adminFetch ya maneja el caso de sesión inválida.
  } finally {
    await openDocumentsModal();
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
    await openDocumentsModal();
  }
}

documentsButtonEl.addEventListener("click", openDocumentsModal);

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
  div.querySelector(".message-text").textContent = message;
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
      askBotAnswerEl.textContent = err.detail || "No se pudo consultar al asistente, intenta de nuevo.";
      askBotSourcesEl.textContent = "";
      askBotResultEl.hidden = false;
      return;
    }
    const data = await res.json();
    askBotAnswerEl.textContent = data.answer;
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
  advisorReplyInputEl.value = askBotAnswerEl.textContent;
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

if (getAdminToken()) {
  tryEnterPanel();
} else {
  showAuthGate();
}
