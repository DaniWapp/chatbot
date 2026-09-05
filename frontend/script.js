const chatWindow = document.getElementById("chat-window");
const emptyState = document.getElementById("empty-state");
const chatForm = document.getElementById("chat-form");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");
const statusBadge = document.getElementById("status-badge");
const escalationBanner = document.getElementById("escalation-banner");
const markSolvedButton = document.getElementById("mark-solved-button");
const bannerMarkSolvedButton = document.getElementById("banner-mark-solved-button");
const institutionLogoEl = document.getElementById("institution-logo");
const institutionSubtitleEl = document.getElementById("institution-subtitle");

async function loadInstitutionBranding() {
  try {
    const res = await fetch("/api/institution");
    if (!res.ok) return;
    const data = await res.json();
    if (data.name) {
      institutionSubtitleEl.textContent = data.name;
      document.title = `Asistente Virtual - ${data.name}`;
    }
    if (data.logo_url) {
      institutionLogoEl.src = data.logo_url;
      institutionLogoEl.alt = data.name || "";
      institutionLogoEl.hidden = false;
    }
  } catch {
    // si falla, se queda con el nombre/branding por defecto del HTML.
  }
}

const NO_INFO_TEXT =
  "No encontré información suficiente en la documentación disponible para responder esta pregunta.";

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

function generateSecureId() {
  // crypto.randomUUID() necesita un "contexto seguro" (HTTPS o localhost) y
  // falla en http://<ip-de-red>:8000, que es como se accede a veces a este
  // proyecto en la red local. crypto.getRandomValues() sí funciona sin
  // contexto seguro y es igual de criptográficamente aleatorio.
  if (window.isSecureContext && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function getSessionId() {
  // sessionStorage (no localStorage): cada pestaña nueva es un cliente
  // distinto, ya que no se comparte entre pestañas del mismo navegador.
  // Se usa un generador criptográficamente seguro (no Math.random()) porque
  // el session_id es lo único que protege el acceso a esta conversación.
  let id = sessionStorage.getItem("chat_session_id");
  if (!id) {
    id = "sesion-" + generateSecureId();
    sessionStorage.setItem("chat_session_id", id);
  }
  return id;
}

const sessionId = getSessionId();
let isEscalated = false;
let sessionWs = null;

function hideEmptyState() {
  if (emptyState) emptyState.style.display = "none";
}

function scrollToBottom() {
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function buildUserMessageEl(text) {
  const row = document.createElement("div");
  row.className = "message-row user";
  row.innerHTML = `<div class="bubble"></div>`;
  row.querySelector(".bubble").textContent = text;
  return row;
}

function addUserMessage(text) {
  chatWindow.appendChild(buildUserMessageEl(text));
  scrollToBottom();
}

function addAssistantPlaceholder() {
  const block = document.createElement("div");
  block.className = "message-block";
  block.innerHTML = `
    <div class="message-row assistant">
      <div class="bubble">
        <div class="typing-indicator-row">
          <div class="typing-indicator"><span></span><span></span><span></span></div>
          <span class="typing-caption">Buscando en los documentos oficiales...</span>
        </div>
      </div>
    </div>
  `;
  chatWindow.appendChild(block);
  scrollToBottom();
  return block;
}

function buildAssistantMessageEl(text, turnCreatedAt, initialRating) {
  const block = document.createElement("div");
  block.className = "message-block";
  block.innerHTML = `
    <div class="message-row assistant">
      <div class="bubble"></div>
    </div>
  `;
  const bubble = block.querySelector(".bubble");
  bubble.innerHTML = renderMarkdownHtml(text);
  addCopyButton(bubble, text);
  addFeedbackButtons(bubble, turnCreatedAt, initialRating);
  return block;
}

function addAssistantMessage(text, turnCreatedAt, initialRating) {
  hideEmptyState();
  chatWindow.appendChild(buildAssistantMessageEl(text, turnCreatedAt, initialRating));
  scrollToBottom();
}

function renderSources(block, sources) {
  if (!sources || sources.length === 0) return;
  const container = document.createElement("div");
  container.className = "sources";
  const items = sources
    .map((s) => {
      const page = s.page !== null && s.page !== undefined ? ` — página ${s.page}` : "";
      return `<li>${escapeHtml(s.document)}${page}</li>`;
    })
    .join("");
  container.innerHTML = `<div class="sources-title">Archivos consultados:</div><ul>${items}</ul>`;
  block.appendChild(container);
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

const COPY_ICON_SVG =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>' +
  '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
const CHECK_ICON_SVG =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<polyline points="20 6 9 17 4 12"></polyline></svg>';

// navigator.clipboard requiere un "contexto seguro" (HTTPS, o localhost) --
// probando desde el celular por IP local (http://192.168.x.x) el navegador
// no la expone en absoluto. Respaldo clásico con un textarea oculto +
// document.execCommand("copy"), que sí funciona en ese caso.
async function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // sigue al respaldo de abajo
    }
  }
  try {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    const success = document.execCommand("copy");
    document.body.removeChild(textarea);
    return success;
  } catch {
    return false;
  }
}

// Se guarda el texto tal cual se generó (antes de renderMarkdownHtml), no
// se lee de vuelta del DOM -- así se copia el texto real de la respuesta,
// no el del propio botón u otros elementos que se agreguen a la burbuja.
function addCopyButton(bubble, text) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "copy-button";
  button.title = "Copiar respuesta";
  button.setAttribute("aria-label", "Copiar respuesta");
  button.innerHTML = COPY_ICON_SVG;
  button.addEventListener("click", async () => {
    const copied = await copyToClipboard(text);
    if (!copied) return;
    button.classList.add("copied");
    button.innerHTML = CHECK_ICON_SVG;
    setTimeout(() => {
      button.classList.remove("copied");
      button.innerHTML = COPY_ICON_SVG;
    }, 1500);
  });
  bubble.appendChild(button);
}

const THUMBS_UP_ICON_SVG =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"></path></svg>';
const THUMBS_DOWN_ICON_SVG =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"></path></svg>';
const THUMBS_UP_FILLED_ICON_SVG =
  '<svg viewBox="0 0 24 24" fill="currentColor">' +
  '<path d="M1 21h4V9H1v12zM23 10c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z"></path></svg>';
const THUMBS_DOWN_FILLED_ICON_SVG =
  '<svg viewBox="0 0 24 24" fill="currentColor">' +
  '<path d="M15 3H6c-.83 0-1.54.5-1.84 1.22l-3.02 7.05c-.09.23-.14.47-.14.73v2c0 1.1.9 2 2 2h6.31l-.95 4.57-.03.32c0 .41.17.79.44 1.06L9.83 23l6.59-6.59c.36-.36.58-.86.58-1.41V5c0-1.1-.9-2-2-2zm4 0v12h4V3h-4z"></path></svg>';

async function submitFeedback(turnCreatedAt, rating) {
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ turn_created_at: turnCreatedAt, rating }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

// turnCreatedAt identifica la respuesta puntual a calificar (viene del
// evento "done" del streaming para una respuesta nueva, o de created_at
// del historial recargado) -- ver app/services/history.py::record_feedback.
// Si es null/undefined (ej. no se pudo determinar), no se muestran los
// botones -- no hay nada que calificar.
function addFeedbackButtons(bubble, turnCreatedAt, initialRating) {
  if (!turnCreatedAt) return;

  const container = document.createElement("div");
  container.className = "feedback-buttons";

  const upButton = document.createElement("button");
  upButton.type = "button";
  upButton.className = "feedback-button feedback-up";
  upButton.title = "Respuesta útil";
  upButton.setAttribute("aria-label", "Respuesta útil");

  const downButton = document.createElement("button");
  downButton.type = "button";
  downButton.className = "feedback-button feedback-down";
  downButton.title = "Respuesta no útil";
  downButton.setAttribute("aria-label", "Respuesta no útil");

  if (initialRating === "up") upButton.classList.add("voted");
  if (initialRating === "down") downButton.classList.add("voted");
  upButton.innerHTML = upButton.classList.contains("voted") ? THUMBS_UP_FILLED_ICON_SVG : THUMBS_UP_ICON_SVG;
  downButton.innerHTML = downButton.classList.contains("voted") ? THUMBS_DOWN_FILLED_ICON_SVG : THUMBS_DOWN_ICON_SVG;

  const vote = async (rating, clickedButton, otherButton) => {
    const ok = await submitFeedback(turnCreatedAt, rating);
    if (!ok) return;
    clickedButton.classList.add("voted");
    otherButton.classList.remove("voted");
    upButton.innerHTML = upButton.classList.contains("voted") ? THUMBS_UP_FILLED_ICON_SVG : THUMBS_UP_ICON_SVG;
    downButton.innerHTML = downButton.classList.contains("voted") ? THUMBS_DOWN_FILLED_ICON_SVG : THUMBS_DOWN_ICON_SVG;
  };

  upButton.addEventListener("click", () => vote("up", upButton, downButton));
  downButton.addEventListener("click", () => vote("down", downButton, upButton));

  container.appendChild(downButton);
  container.appendChild(upButton);
  bubble.appendChild(container);
}

function addSystemNotice(text) {
  hideEmptyState();
  const row = document.createElement("div");
  row.className = "system-notice";
  row.textContent = text;
  chatWindow.appendChild(row);
  scrollToBottom();
}

function buildAdvisorMessageEl(text) {
  const block = document.createElement("div");
  block.className = "message-block";
  block.innerHTML = `
    <div class="message-row assistant">
      <div class="bubble advisor-bubble">
        <div class="sender-label">Asesor</div>
        <div class="advisor-text"></div>
      </div>
    </div>
  `;
  block.querySelector(".advisor-text").innerHTML = renderMarkdownHtml(text);
  return block;
}

function addAdvisorMessage(text) {
  hideEmptyState();
  chatWindow.appendChild(buildAdvisorMessageEl(text));
  scrollToBottom();
}

function prependHistoryMessages(messages) {
  const fragment = document.createDocumentFragment();
  messages.forEach((m) => {
    if (m.sender === "student") fragment.appendChild(buildUserMessageEl(m.message));
    else if (m.sender === "assistant") fragment.appendChild(buildAssistantMessageEl(m.message, m.created_at, m.feedback_rating));
    else if (m.sender === "advisor") fragment.appendChild(buildAdvisorMessageEl(m.message));
  });
  chatWindow.insertBefore(fragment, chatWindow.firstChild);
}

function addCheckinPrompt(text) {
  hideEmptyState();
  const block = document.createElement("div");
  block.className = "message-block";
  block.innerHTML = `
    <div class="message-row assistant">
      <div class="bubble advisor-bubble">
        <div class="sender-label">Asesor</div>
        <div class="advisor-text"></div>
        <div class="checkin-actions">
          <button type="button" class="checkin-button checkin-yes">Sí, por favor</button>
          <button type="button" class="checkin-button checkin-no">No, gracias</button>
        </div>
      </div>
    </div>
  `;
  block.querySelector(".advisor-text").textContent = text;
  const actions = block.querySelector(".checkin-actions");
  const yesButton = block.querySelector(".checkin-yes");
  const noButton = block.querySelector(".checkin-no");

  const respond = async (wantsMoreHelp) => {
    yesButton.disabled = true;
    noButton.disabled = true;
    try {
      const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/checkin-response`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ wants_more_help: wantsMoreHelp }),
      });
      const data = await res.json().catch(() => null);
      if (data && data.created_at) latestRenderedMessageAt = data.created_at;
    } catch {
      // si falla la llamada, igual reflejamos la elección localmente para no bloquear al estudiante.
    }
    actions.remove();
    if (wantsMoreHelp) {
      addSystemNotice("Perfecto, continúa cuando quieras.");
    } else {
      isEscalated = false;
      hideEscalationBanner();
      addSystemNotice("Marcaste esta conversación como solucionada. El asistente virtual está disponible de nuevo.");
    }
  };

  yesButton.addEventListener("click", () => respond(true));
  noButton.addEventListener("click", () => respond(false));

  chatWindow.appendChild(block);
  scrollToBottom();
}

function showEscalationBanner() {
  escalationBanner.hidden = false;
  markSolvedButton.hidden = true;
}

function hideEscalationBanner() {
  escalationBanner.hidden = true;
  markSolvedButton.hidden = false;
}

function connectSessionWebSocket() {
  if (sessionWs && (sessionWs.readyState === WebSocket.OPEN || sessionWs.readyState === WebSocket.CONNECTING)) return;
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  sessionWs = new WebSocket(`${protocol}//${location.host}/api/ws/chat/${encodeURIComponent(sessionId)}`);

  sessionWs.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch {
      return;
    }
    if (data.type === "advisor_message" && data.message_type === "checkin") {
      addCheckinPrompt(data.message);
      latestRenderedMessageAt = data.created_at;
      playNotificationSound();
    } else if (data.type === "advisor_message") {
      addAdvisorMessage(data.message);
      latestRenderedMessageAt = data.created_at;
      playNotificationSound();
    } else if (data.type === "resolved") {
      isEscalated = false;
      hideEscalationBanner();
      addSystemNotice("Tu conversación fue marcada como resuelta. El asistente virtual está disponible de nuevo.");
    } else if (data.type === "reassigned") {
      addSystemNotice(data.message);
    }
  };

  sessionWs.onclose = () => {
    sessionWs = null;
    if (isEscalated) setTimeout(connectSessionWebSocket, 3000);
  };

  sessionWs.onerror = () => sessionWs && sessionWs.close();
}

async function submitEscalation(name, email, container, onError) {
  try {
    const res = await fetch("/api/escalate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, name, email }),
    });
    if (!res.ok) throw new Error("escalate failed");

    sessionStorage.setItem("chat_student_name", name);
    sessionStorage.setItem("chat_student_email", email);
    isEscalated = true;
    container.remove();
    addSystemNotice("Hemos escalado tu pregunta a un asesor humano. En breve te contactará aquí mismo.");
    showEscalationBanner();
    connectSessionWebSocket();
  } catch {
    onError();
  }
}

function showEscalationForm(container) {
  container.innerHTML = `
    <div class="escalate-card">
      <p class="escalate-form-intro">Para conectarte con un asesor humano, cuéntanos quién eres:</p>
      <form class="escalate-form">
        <input type="text" class="escalate-name" placeholder="Nombre completo" required maxlength="200" />
        <input type="email" class="escalate-email" placeholder="Correo electrónico" required maxlength="200" />
        <button type="submit">Enviar</button>
      </form>
    </div>
  `;
  const form = container.querySelector(".escalate-form");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const name = form.querySelector(".escalate-name").value.trim();
    const email = form.querySelector(".escalate-email").value.trim();
    if (!name || !email) return;

    const submitBtn = form.querySelector("button[type=submit]");
    submitBtn.disabled = true;

    submitEscalation(name, email, container, () => {
      submitBtn.disabled = false;
      const errorEl = document.createElement("p");
      errorEl.className = "escalate-error";
      errorEl.textContent = "No se pudo enviar, intenta de nuevo.";
      form.appendChild(errorEl);
    });
  });
}

function addSuggestionOptions(block, suggestions) {
  if (!suggestions || !suggestions.length) return;
  const container = document.createElement("div");
  container.className = "suggestions-container";
  const label = document.createElement("p");
  label.className = "suggestions-label";
  label.textContent = "¿Quisiste decir alguna de estas preguntas?";
  container.appendChild(label);
  suggestions.forEach((text) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "suggestion-button";
    button.innerHTML = `
      <span class="suggestion-button-text">${escapeHtml(text)}</span>
      <svg class="suggestion-button-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="22" y1="2" x2="11" y2="13"></line>
        <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
      </svg>
    `;
    button.addEventListener("click", () => {
      container.remove();
      sendMessage(text);
    });
    container.appendChild(button);
  });
  block.appendChild(container);
}

function addEscalationOption(block) {
  if (isEscalated) return;
  const container = document.createElement("div");
  container.className = "escalate-container";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "escalate-button";
  button.textContent = "Solicitar atención humana";
  button.addEventListener("click", () => {
    const savedName = sessionStorage.getItem("chat_student_name");
    const savedEmail = sessionStorage.getItem("chat_student_email");
    if (savedName && savedEmail) {
      button.disabled = true;
      submitEscalation(savedName, savedEmail, container, () => {
        button.disabled = false;
      });
    } else {
      showEscalationForm(container);
    }
  });
  container.appendChild(button);
  block.appendChild(container);
}

const CHAT_HISTORY_PAGE_SIZE = 50;
let chatHistoryHasMoreOlder = false;
let chatHistoryNextCursor = null;

function ensureLoadOlderButton() {
  const existing = chatWindow.querySelector(".load-older-button");
  if (!chatHistoryHasMoreOlder) {
    if (existing) existing.remove();
    return;
  }
  if (existing) return;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "load-older-button";
  btn.textContent = "Cargar mensajes anteriores";
  btn.addEventListener("click", loadOlderChatHistory);
  chatWindow.insertBefore(btn, chatWindow.firstChild);
}

async function loadOlderChatHistory() {
  if (!chatHistoryHasMoreOlder || !chatHistoryNextCursor) return;
  const btn = chatWindow.querySelector(".load-older-button");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Cargando...";
  }
  try {
    const params = new URLSearchParams({ before: chatHistoryNextCursor, limit: String(CHAT_HISTORY_PAGE_SIZE) });
    const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/history?${params.toString()}`);
    if (!res.ok) return;
    const data = await res.json();

    const previousScrollHeight = chatWindow.scrollHeight;
    if (btn) btn.remove();

    prependHistoryMessages(data.messages);

    chatHistoryHasMoreOlder = data.has_more;
    chatHistoryNextCursor = data.next_cursor;
    ensureLoadOlderButton();

    // Mantiene la posición visual del usuario tras insertar contenido arriba.
    chatWindow.scrollTop = chatWindow.scrollHeight - previousScrollHeight;
  } catch {
    // si falla, se deja el botón disponible para reintentar.
  } finally {
    const stillThere = chatWindow.querySelector(".load-older-button");
    if (stillThere) {
      stillThere.disabled = false;
      stillThere.textContent = "Cargar mensajes anteriores";
    }
  }
}

// Última fecha (created_at) de un mensaje ya renderizado en pantalla. Sirve
// para "ponerse al día" (catchUpMissedMessages) cuando la pestaña estuvo en
// segundo plano: el navegador puede congelar el WebSocket sin avisar (ver
// connectSessionWebSocket), así que reconectar el canal en vivo no basta --
// hay que ir a buscar lo que se haya perdido mientras tanto.
let latestRenderedMessageAt = null;

function renderHistoryMessage(m, isLast) {
  if (m.sender === "student") {
    addUserMessage(m.message);
  } else if (m.sender === "assistant") {
    addAssistantMessage(m.message, m.created_at, m.feedback_rating);
  } else if (m.sender === "advisor" && m.message_type === "checkin") {
    if (isLast) addCheckinPrompt(m.message);
    else addAdvisorMessage(m.message);
  } else if (m.sender === "advisor") {
    addAdvisorMessage(m.message);
  }
  latestRenderedMessageAt = m.created_at;
}

async function loadChatHistory() {
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/history?limit=${CHAT_HISTORY_PAGE_SIZE}`);
    if (!res.ok) return;
    const data = await res.json();
    const messages = data.messages;
    if (!messages.length) return;

    messages.forEach((m, index) => renderHistoryMessage(m, index === messages.length - 1));
    markSolvedButton.hidden = false;

    chatHistoryHasMoreOlder = data.has_more;
    chatHistoryNextCursor = data.next_cursor;
    ensureLoadOlderButton();
  } catch {
    // si falla, el chat simplemente empieza vacío; no bloquea el uso normal.
  }
}

async function catchUpMissedMessages() {
  if (!latestRenderedMessageAt) return;
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/history?limit=${CHAT_HISTORY_PAGE_SIZE}`);
    if (!res.ok) return;
    const data = await res.json();
    const missed = data.messages.filter((m) => m.created_at > latestRenderedMessageAt);
    missed.forEach((m, index) => {
      renderHistoryMessage(m, index === missed.length - 1);
      playNotificationSound();
    });
  } catch {
    // best-effort: si falla, el usuario siempre puede recargar la página.
  }
}

async function checkSessionStatus() {
  try {
    const res = await fetch(`/api/session-status/${encodeURIComponent(sessionId)}`);
    const data = await res.json();
    if (data.needs_human) {
      isEscalated = true;
      showEscalationBanner();
      connectSessionWebSocket();
      await catchUpMissedMessages();
    } else if (isEscalated) {
      // Se resolvió mientras la pestaña estaba en segundo plano.
      isEscalated = false;
      hideEscalationBanner();
      addSystemNotice("Tu conversación fue marcada como resuelta. El asistente virtual está disponible de nuevo.");
    }
  } catch {
    // si falla, se asume que no está escalada; no bloquea el chat normal
  }
}

// El indicador de "escribiendo" (los 3 punticos) debe verse al menos este
// tiempo, sin importar qué tan rápido llegue la respuesta -- una respuesta
// servida desde caché puede resolver en pocos ms, y desaparecer el
// indicador casi al instante se siente artificial/roto. Pasado este
// tiempo, se muestra el contenido completo de una vez (sin animación de
// tecleo), tanto si vino de caché como de Groq.
const MIN_TYPING_INDICATOR_MS = 300;

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// FastAPI devuelve "detail" como texto simple para errores propios (ej.
// HTTPException), pero como una lista de objetos para errores de
// validación automática de Pydantic (ej. mensaje demasiado largo) --
// mostrar esa lista tal cual con textContent la convierte en
// "[object Object]". Aquí se normaliza a un texto legible en ambos casos.
function extractErrorMessage(err) {
  if (typeof err.detail === "string" && err.detail.trim()) return err.detail;
  if (Array.isArray(err.detail) && err.detail.length > 0) {
    return "Tu mensaje no es válido. Verifica que no esté vacío ni sea demasiado largo.";
  }
  return "Ocurrió un error al contactar al asistente.";
}

async function sendMessage(text) {
  hideEmptyState();
  if (!isEscalated) markSolvedButton.hidden = false;
  addUserMessage(text);
  const block = addAssistantPlaceholder();
  const bubble = block.querySelector(".bubble");
  const captionEl = block.querySelector(".typing-caption");
  const placeholderShownAt = performance.now();

  sendButton.disabled = true;

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: text }),
    });

    if (!response.ok || !response.body) {
      const err = await response.json().catch(() => ({}));
      bubble.textContent = extractErrorMessage(err);
      sendButton.disabled = false;
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let answerText = "";
    let sources = [];
    let suggestions = [];
    let wasEscalated = false;
    let errorMessage = null;
    let turnCreatedAt = null;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split("\n\n");
      buffer = parts.pop();

      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const jsonStr = line.slice(5).trim();
        if (!jsonStr) continue;

        let event;
        try {
          event = JSON.parse(jsonStr);
        } catch {
          continue;
        }

        // A propósito no se toca el DOM aquí por cada delta: se acumula el
        // texto completo y recién se muestra de una sola vez más abajo,
        // una vez cumplido MIN_TYPING_INDICATOR_MS -- ver comentario arriba.
        if (event.type === "meta") {
          sources = event.sources || [];
          if (captionEl) {
            captionEl.textContent = event.has_sufficient_info
              ? "Encontró información relevante, generando tu respuesta..."
              : "No encontró coincidencias directas, buscando alternativas...";
          }
        } else if (event.type === "delta") {
          answerText += event.text;
        } else if (event.type === "escalated") {
          wasEscalated = true;
        } else if (event.type === "done") {
          suggestions = event.suggestions || [];
          turnCreatedAt = event.turn_created_at || null;
        } else if (event.type === "error") {
          errorMessage = event.message;
        }
      }
    }

    // Aproximación con el reloj del navegador: el streaming no devuelve el
    // created_at exacto del servidor, pero solo se usa para no reprocesar
    // este turno si más tarde hay que "ponerse al día" tras una
    // desconexión (catchUpMissedMessages) -- una pequeña diferencia de
    // reloj no rompe nada ahí.
    latestRenderedMessageAt = new Date().toISOString();

    const remaining = MIN_TYPING_INDICATOR_MS - (performance.now() - placeholderShownAt);
    if (remaining > 0) await wait(remaining);

    if (wasEscalated) {
      // La barra persistente ya avisa que un asesor está atendiendo; no hace
      // falta repetirlo en cada mensaje. Se quita el placeholder: el mensaje
      // del estudiante, ya visible, es suficiente contexto.
      block.remove();
    } else if (errorMessage) {
      bubble.textContent = "Error: " + errorMessage;
    } else {
      bubble.innerHTML = renderMarkdownHtml(answerText);
      addCopyButton(bubble, answerText);
      addFeedbackButtons(bubble, turnCreatedAt);
      if (answerText.trim() === NO_INFO_TEXT) {
        bubble.classList.add("no-info");
        addSuggestionOptions(block, suggestions);
        addEscalationOption(block);
      } else {
        renderSources(block, sources);
      }
    }
  } catch (err) {
    bubble.textContent = "No se pudo conectar con el servidor. Verifica que el backend esté activo.";
  } finally {
    sendButton.disabled = false;
    scrollToBottom();
  }
}

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = messageInput.value.trim();
  if (!text) return;
  messageInput.value = "";
  sendMessage(text);
});

document.querySelectorAll(".suggestion-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    sendMessage(chip.textContent);
  });
});

async function markConversationAsSolved(triggerButton) {
  triggerButton.disabled = true;
  const wasEscalated = isEscalated;
  try {
    await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/mark-solved`, { method: "POST" });
    isEscalated = false;
    hideEscalationBanner();
    markSolvedButton.hidden = true;
    addSystemNotice(
      wasEscalated
        ? "Marcaste esta conversación como solucionada. El asistente virtual está disponible de nuevo."
        : "Marcaste esta conversación como solucionada. ¡Gracias!"
    );
  } catch {
    addSystemNotice("No se pudo marcar la conversación como solucionada, intenta de nuevo.");
  } finally {
    triggerButton.disabled = false;
  }
}

markSolvedButton.addEventListener("click", () => markConversationAsSolved(markSolvedButton));
bannerMarkSolvedButton.addEventListener("click", () => markConversationAsSolved(bannerMarkSolvedButton));

async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    if (data.status === "ok" && data.groq_configured) {
      statusBadge.classList.remove("offline");
      statusBadge.textContent = "Conectado";
      statusBadge.title = `Conectado — ${data.documents_indexed} fragmentos indexados`;
    } else if (data.status === "ok" && !data.groq_configured) {
      statusBadge.classList.add("offline");
      statusBadge.textContent = "Sin conexión";
      statusBadge.title = "GROQ_API_KEY no configurada en el servidor";
    }
  } catch {
    statusBadge.classList.add("offline");
    statusBadge.textContent = "Sin conexión";
    statusBadge.title = "No se pudo conectar con el backend";
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  // El navegador puede congelar el WebSocket en segundo plano (ahorro de
  // batería en móviles) sin disparar "onclose"; al volver a la pestaña se
  // vuelve a consultar el estado y se reconecta si hace falta
  // (connectSessionWebSocket ya evita duplicar una conexión viva).
  checkSessionStatus();
});

checkHealth();
loadInstitutionBranding();
loadChatHistory().then(checkSessionStatus);
