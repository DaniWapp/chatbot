// Funciones y constantes compartidas entre root.js (/root) y panel.js
// (/panel) -- ambos paneles de administración muestran features
// solapadas (Dashboard, Documentos, Moderación, Widget, Horario) para
// roles distintos, y antes de este archivo cada uno reimplementaba la
// misma lógica por separado.
//
// Script clásico (sin bundler, sin type="module", mismo patrón que
// markdown-render.js): define funciones/constantes globales y se carga
// con un <script src="..."> ANTES de root.js/panel.js en su respectivo
// HTML. A diferencia de markdown-render.js, no tiene ningún efecto
// secundario al cargar (no llama nada por su cuenta).

// --- Utilidades genéricas --------------------------------------------------

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(isoString) {
  try {
    return new Date(isoString).toLocaleString();
  } catch {
    return isoString;
  }
}

function formatMinutes(minutes) {
  if (minutes == null) return "—";
  if (minutes < 60) return `${minutes.toFixed(1)} min`;
  return `${(minutes / 60).toFixed(1)} h`;
}

async function errorDetail(res) {
  const body = await res.json().catch(() => ({}));
  if (Array.isArray(body.detail)) {
    return body.detail.map((d) => d.msg).join(" ") || "Ocurrió un error.";
  }
  return body.detail || "Ocurrió un error.";
}

// --- Modal genérico ---------------------------------------------------------
// Requiere que la página ya tenga #modal-overlay/#modal-content en el DOM
// (root.html y panel.html los tienen ambos).

const modalOverlayEl = document.getElementById("modal-overlay");
const modalContentEl = document.getElementById("modal-content");

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

// --- Dashboard: builders compartidos ----------------------------------------

function dashboardCardHtml(label, value, extraClass) {
  return `
    <div class="dashboard-card${extraClass ? " " + extraClass : ""}">
      <span class="dashboard-card-value">${value}</span>
      <span class="dashboard-card-label">${escapeHtml(label)}</span>
    </div>
  `;
}

function dashboardSummaryHtml(dashboard) {
  const c = dashboard.conversations;
  const d = dashboard.documents;
  const f = dashboard.faq;
  const cards = [
    ["Pendientes ahora", c.pending_now],
    ["Conversaciones escaladas", c.total_escalated],
    ["Primera respuesta (promedio)", formatMinutes(c.avg_first_response_minutes)],
    ["Documentos indexados", d.total],
    ["FAQ pendientes por revisar", f.pending],
  ];
  return cards.map(([label, value]) => dashboardCardHtml(label, value, "dashboard-card-hero")).join("");
}

function dashboardSectionHtml(title, summaryHtml, detailHtml) {
  return `
    <details class="dashboard-section">
      <summary>
        <span class="dashboard-section-title">${escapeHtml(title)}</span>
        <span class="dashboard-section-preview">${summaryHtml}</span>
      </summary>
      <div class="dashboard-section-detail">${detailHtml}</div>
    </details>
  `;
}

// --- Documentos: filtro y selector de dependencia compartidos ---------------
// Antes existían dos veces con cuerpo idéntico, cada una leyendo un
// global distinto de su propia página (root.js: `dependencias` /
// `documentDependenciaFilter`; panel.js: `dependenciasForReassign` /
// `panelDocumentDependenciaFilter`) -- ahora reciben ese valor como
// parámetro en vez de depender de un global de la página.

const IMAGE_EXTENSION_PATTERN = /\.(jpe?g|png|webp)$/i;

function documentDependenciaOptionsHtml(selectedId, dependenciasList) {
  const generalOption = `<option value="" ${selectedId == null ? "selected" : ""}>General / compartido</option>`;
  const depOptions = dependenciasList
    .map((d) => `<option value="${d.id}" ${d.id === selectedId ? "selected" : ""}>${escapeHtml(d.name)}</option>`)
    .join("");
  return generalOption + depOptions;
}

function documentMatchesDependenciaFilter(doc, filterValue) {
  if (filterValue === "all") return true;
  if (filterValue === "general") return doc.dependencia_id == null;
  return doc.dependencia_id === Number(filterValue);
}

// A diferencia de recategorizar (dependencia/vigencia, solo root/general),
// marcar un documento como descargable o no está disponible para
// cualquier rol -- fetchFn es rootFetch o adminFetch según quién llama,
// mismo patrón que wireSimpleListTab.
async function setDocumentDownloadable(fetchFn, basePath, filename, downloadable) {
  try {
    const res = await fetchFn(`${basePath}/${encodeURIComponent(filename)}/downloadable`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ downloadable }),
    });
    if (!res.ok) alert(await errorDetail(res));
  } catch {
    // rootFetch/adminFetch ya manejan el caso de sesión inválida.
  }
}

// --- Horario: piezas compartidas del formulario -----------------------------

const HORARIO_DIA_LABELS = { 1: "Lun", 2: "Mar", 3: "Mié", 4: "Jue", 5: "Vie", 6: "Sáb", 7: "Dom" };

function horarioRangoRowHtml(inicio, fin) {
  return `
    <div class="horario-rango-row">
      <input type="time" class="horario-rango-inicio" value="${inicio || ""}" required />
      <span>a</span>
      <input type="time" class="horario-rango-fin" value="${fin || ""}" required />
      <button type="button" class="danger remove-rango-button">Quitar</button>
    </div>
  `;
}

// --- Fábrica genérica: pestaña de lista simple (agregar/eliminar) -----------
// Usada por Moderación (palabras de hostilidad) y Widget (orígenes
// permitidos) en root.js y panel.js -- las dos parejas eran, antes de
// esta extracción, línea por línea idénticas salvo el prefijo del id en
// el DOM, el endpoint (/api/root/... vs /api/admin/...) y el fetch
// helper (rootFetch vs adminFetch). Cubre: cargar la lista, pintar la
// tabla, el submit del formulario de "agregar", y el botón "Eliminar"
// por fila.

function wireSimpleListTab({
  fetchFn,
  listUrl,
  createUrl,
  deleteUrlFor,
  createBody,
  formId,
  inputId,
  errorId,
  tbodyId,
  emptyId,
  deleteButtonSelector,
  rowHtml,
  confirmMessage,
}) {
  async function load() {
    const res = await fetchFn(listUrl);
    const items = await res.json();
    renderTable(items);
    return items;
  }

  function renderTable(items) {
    const tbody = document.getElementById(tbodyId);
    const emptyEl = document.getElementById(emptyId);
    tbody.innerHTML = "";
    emptyEl.hidden = items.length > 0;
    for (const item of items) {
      const tr = document.createElement("tr");
      tr.innerHTML = rowHtml(item);
      tr.querySelector(deleteButtonSelector).addEventListener("click", () => removeItem(item));
      tbody.appendChild(tr);
    }
  }

  async function removeItem(item) {
    if (!confirm(confirmMessage(item))) return;
    try {
      const res = await fetchFn(deleteUrlFor(item), { method: "DELETE" });
      if (!res.ok) alert(await errorDetail(res));
      await load();
    } catch {
      // fetchFn ya maneja el caso de sesión inválida.
    }
  }

  document.getElementById(formId).addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById(inputId);
    const errorEl = document.getElementById(errorId);
    const value = input.value.trim();
    if (!value) return;

    errorEl.hidden = true;
    try {
      const res = await fetchFn(createUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(createBody(value)),
      });
      if (!res.ok) {
        errorEl.textContent = await errorDetail(res);
        errorEl.hidden = false;
        return;
      }
      input.value = "";
      await load();
    } catch {
      // fetchFn ya maneja el caso de sesión inválida.
    }
  });

  return { load };
}
