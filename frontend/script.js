const chatWindow = document.getElementById("chat-window");
const emptyState = document.getElementById("empty-state");
const chatForm = document.getElementById("chat-form");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");
const statusBadge = document.getElementById("status-badge");

const NO_INFO_TEXT =
  "No encontré información suficiente en la documentación disponible para responder esta pregunta.";

function getSessionId() {
  let id = localStorage.getItem("chat_session_id");
  if (!id) {
    id = "sesion-" + Math.random().toString(36).slice(2) + Date.now();
    localStorage.setItem("chat_session_id", id);
  }
  return id;
}

const sessionId = getSessionId();

function hideEmptyState() {
  if (emptyState) emptyState.style.display = "none";
}

function scrollToBottom() {
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function addUserMessage(text) {
  const row = document.createElement("div");
  row.className = "message-row user";
  row.innerHTML = `<div class="bubble"></div>`;
  row.querySelector(".bubble").textContent = text;
  chatWindow.appendChild(row);
  scrollToBottom();
}

function addAssistantPlaceholder() {
  const block = document.createElement("div");
  block.className = "message-block";
  block.innerHTML = `
    <div class="message-row assistant">
      <div class="bubble">
        <div class="typing-indicator"><span></span><span></span><span></span></div>
      </div>
    </div>
  `;
  chatWindow.appendChild(block);
  scrollToBottom();
  return block;
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
  container.innerHTML = `<div class="sources-title">Fuentes:</div><ul>${items}</ul>`;
  block.appendChild(container);
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

async function sendMessage(text) {
  hideEmptyState();
  addUserMessage(text);
  const block = addAssistantPlaceholder();
  const bubble = block.querySelector(".bubble");

  sendButton.disabled = true;

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: text }),
    });

    if (!response.ok || !response.body) {
      const err = await response.json().catch(() => ({}));
      bubble.textContent = err.detail || "Ocurrió un error al contactar al asistente.";
      sendButton.disabled = false;
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let answerText = "";
    let firstDelta = true;
    let sources = [];

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

        if (event.type === "meta") {
          sources = event.sources || [];
        } else if (event.type === "delta") {
          if (firstDelta) {
            bubble.textContent = "";
            firstDelta = false;
          }
          answerText += event.text;
          bubble.textContent = answerText;
          scrollToBottom();
        } else if (event.type === "error") {
          bubble.textContent = "Error: " + event.message;
        }
      }
    }

    if (answerText.trim() === NO_INFO_TEXT) {
      bubble.classList.add("no-info");
    } else {
      renderSources(block, sources);
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

async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    if (data.status === "ok" && data.groq_configured) {
      statusBadge.classList.remove("offline");
      statusBadge.title = `Conectado — ${data.documents_indexed} fragmentos indexados`;
    } else if (data.status === "ok" && !data.groq_configured) {
      statusBadge.classList.add("offline");
      statusBadge.title = "GROQ_API_KEY no configurada en el servidor";
    }
  } catch {
    statusBadge.classList.add("offline");
    statusBadge.title = "No se pudo conectar con el backend";
  }
}

checkHealth();
