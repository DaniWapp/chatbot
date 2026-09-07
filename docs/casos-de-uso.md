# Casos de uso

Catálogo completo de los casos de uso del sistema: qué puede hacer cada
actor, en qué condiciones, y qué pasa exactamente paso a paso. Para
**cómo usar** cada pantalla ver [manual-usuario.md](manual-usuario.md);
este documento describe el **comportamiento del sistema** ante cada
acción -- pensado para sustentar el proyecto o para entender el alcance
funcional completo sin leer código.

Cada caso de uso referencia el archivo/endpoint real que lo implementa,
para poder verificarlo o profundizar en el código.

## Índice de actores

1. [Estudiante](#1-estudiante) -- usuario del chat, sin cuenta ni autenticación.
2. [Asesor de dependencia](#2-asesor-de-dependencia) -- cuenta de administrador con rol `dependencia`.
3. [Administrador general](#3-administrador-general) -- cuenta con rol `general`, supervisa todas las dependencias.
4. [Administrador root](#4-administrador-root) -- cuenta con rol `root`, administra el sistema completo.
5. [Sistema](#5-sistema-casos-de-uso-automáticos) -- procesos automáticos sin intervención humana.
6. [Sitio anfitrión del widget](#6-sitio-anfitrión-del-widget) -- actor externo que embebe el chat.

Los roles de administrador (dependencia, general, root) heredan: todo lo
que puede hacer un asesor de dependencia también puede hacerlo el
general, y buena parte de lo del general también aplica a root -- las
secciones 2-4 solo listan las diferencias y adiciones de cada nivel, no
repiten lo ya cubierto.

---

## 1. Estudiante

### CU-01: Hacer una pregunta al asistente virtual

- **Actor:** Estudiante.
- **Precondición:** Ninguna -- no requiere cuenta. Al abrir el chat se
  genera un `session_id` anónimo que persiste en el navegador.
- **Flujo principal:**
  1. El estudiante escribe una pregunta y la envía.
  2. El sistema busca los fragmentos de documentos más relevantes
     (embeddings + FAISS + re-ranking, ver
     [conceptos-chunks-y-faiss.md](conceptos-chunks-y-faiss.md)).
  3. El LLM (Groq) genera una respuesta basada **solo** en esos
     fragmentos, transmitida palabra por palabra (streaming).
  4. La respuesta se muestra con sus fuentes citadas (documento y página).
- **Flujos alternos:**
  - Si la conversación ya fue escalada a un asesor humano (`needs_human`),
    el chatbot no responde -- ver CU-04.
  - Si el mensaje contiene lenguaje hostil detectado, ver CU-39.
- **Postcondición:** El turno (pregunta + respuesta) queda guardado en
  `turns`, asociado al `session_id`.
- **Referencia:** `POST /api/chat/stream`, `app/services/chat_service.py`.

### CU-02: Recibir sugerencias cuando no hay información suficiente

- **Actor:** Estudiante.
- **Precondición:** Ninguno de los fragmentos recuperados (por
  embeddings ni por coincidencia léxica) fue considerado realmente
  relevante por el re-ranker (`RERANK_MIN_SCORE`) -- ver
  [busqueda-lexica-bm25.md](busqueda-lexica-bm25.md).
- **Flujo principal:**
  1. El sistema responde que no encontró información suficiente.
  2. Busca, entre todo el contenido indexado (sin aplicar el umbral),
     hasta 3 preguntas relacionadas que sí podría responder.
  3. Se muestran como chips; si el estudiante hace clic en una, se envía
     como si la hubiera escrito él.
- **Flujo alterno:** Si no hay ninguna pregunta relacionada razonable, se
  omiten las sugerencias y solo se ofrece el botón de atención humana
  (CU-03).
- **Referencia:** `app/rag/retriever.py::retrieve_below_threshold`.

### CU-03: Solicitar atención humana (escalar)

- **Actor:** Estudiante.
- **Precondición:** El chatbot no encontró información suficiente (o el
  estudiante lo pide explícitamente).
- **Flujo principal:**
  1. El estudiante completa nombre completo y correo electrónico
     (teléfono opcional, "por si no hay atención en línea") y envía.
  2. El sistema decide (best-effort, vía LLM) a qué dependencia
     corresponde la pregunta, según la descripción de cada dependencia.
  3. La conversación queda marcada como pendiente y se notifica en
     tiempo real al panel de esa dependencia.
  4. El chatbot deja de responder automáticamente en esta sesión.
- **Flujos alternos:**
  - **Fuera de horario de atención** (ver CU-21): el sistema le avisa al
    estudiante el horario configurado y le confirma que su pregunta
    quedó guardada; si dejó teléfono, se lo hace saber explícitamente
    ("Dejaste tu correo y teléfono para que te contacten directamente").
  - Si la dependencia asignada no responde dentro del tiempo límite, ver
    CU-36 (auto-escalamiento).
- **Postcondición:** `session_meta.needs_human = 1`, `escalated_at`
  registrado, dependencia asignada.
- **Referencia:** `POST /api/escalate`, `app/services/admin_service.py::is_within_horario`.

### CU-04: Conversar con un asesor humano en tiempo real

- **Actor:** Estudiante.
- **Precondición:** Conversación escalada (CU-03) y asignada a una
  dependencia.
- **Flujo principal:**
  1. El estudiante ve un aviso de que su pregunta fue enviada a un asesor.
  2. Cuando el asesor responde (CU-12), el mensaje aparece en el chat en
     tiempo real (WebSocket), con el nombre real del asesor -- y su
     dependencia, si tiene una vinculada -- en vez de una etiqueta
     genérica.
  3. La conversación sigue así, mensaje por mensaje, hasta que se marca
     como resuelta.
- **Flujo alterno:** Si la pestaña estuvo en segundo plano y el
  navegador cortó el WebSocket sin avisar, al volver el chat recupera
  los mensajes perdidos mientras tanto (`catchUpMissedMessages`).
- **Referencia:** `WS /api/ws/chat/{session_id}`, `frontend/script.js`.

### CU-05: Responder al chequeo "¿Necesita algo más?"

- **Actor:** Estudiante.
- **Precondición:** Un asesor disparó la pregunta de seguimiento (CU-14).
- **Flujo principal:**
  1. Aparecen dos botones en el chat: "Sí, por favor" / "No, gracias".
  2. Si responde "No", la conversación se marca como resuelta
     automáticamente (equivalente a CU-06).
  3. Si responde "Sí", el asesor recibe la respuesta y sigue atendiendo.
- **Referencia:** `POST /api/sessions/{session_id}/checkin-response`.

### CU-06: Marcar la conversación como solucionada

- **Actor:** Estudiante.
- **Precondición:** Está en atención humana (CU-04).
- **Flujo principal:**
  1. El estudiante presiona "Marcar como solucionado".
  2. El chatbot vuelve a responder automáticamente sus próximas
     preguntas en esa misma sesión.
- **Postcondición:** `resolved_at` registrado, `resolved_by = "student"`;
  posible generación de sugerencia de FAQ si la resolución vino de un
  asesor (ver CU-37).
- **Referencia:** `POST /api/sessions/{session_id}/mark-solved`.

### CU-07: Calificar una respuesta del asistente

- **Actor:** Estudiante.
- **Precondición:** El asistente (no un asesor humano) respondió una
  pregunta.
- **Flujo principal:**
  1. El estudiante presiona 👍 o 👎 debajo de la respuesta.
  2. Puede cambiar su voto votando de nuevo sobre la misma respuesta.
- **Postcondición:** Queda registrado en `answer_feedback`, visible en el
  Dashboard (sección "Feedback de estudiantes", ver CU-35) como insumo
  para detectar respuestas que necesitan mejorarse.
- **Referencia:** `POST /api/sessions/{session_id}/feedback`.

### CU-08: Descargar el documento original citado como fuente

- **Actor:** Estudiante.
- **Precondición:** Una respuesta cita un documento como fuente.
- **Flujo principal:**
  1. El estudiante hace clic en la fuente citada.
  2. El sistema sirve el archivo original (PDF/DOCX/XLSX tal como se
     subió, no el `.txt` derivado usado internamente para indexar).
- **Referencia:** `GET /api/documents/{filename}/download`.

---

## 2. Asesor de dependencia

Accede a `/panel` con una cuenta de rol `dependencia`, creada
previamente por root (CU-30). Solo ve y gestiona lo de **su propia**
dependencia.

### CU-09: Iniciar sesión en el panel

- **Actor:** Asesor de dependencia (también general y root en sus
  paneles respectivos).
- **Flujo principal:** Ingresa usuario (correo) y contraseña.
- **Flujo alterno:** Credenciales inválidas → mensaje de error, sin
  indicar cuál de los dos datos falló. Cuenta desactivada (CU-30) →
  no puede iniciar sesión aunque la contraseña sea correcta.
- **Referencia:** `POST /api/auth/login`.

### CU-10: Ver y filtrar conversaciones asignadas a su dependencia

- **Actor:** Asesor de dependencia.
- **Flujo principal:**
  1. Ve la lista de conversaciones escaladas hacia su dependencia.
  2. Puede filtrar solo las pendientes (sin respuesta todavía) con el
     chip "X pendientes".
- **Referencia:** `GET /api/admin/sessions`.

### CU-11: Atender una conversación escalada

- **Actor:** Asesor de dependencia.
- **Precondición:** Conversación asignada a su dependencia.
- **Flujo principal:**
  1. Abre la conversación y ve el historial completo (incluida la
     interacción previa con el chatbot).
  2. Escribe una respuesta en el campo de asesor y la envía.
  3. El estudiante la recibe en tiempo real (CU-04), con el nombre real
     del asesor.
- **Postcondición:** `first_response_at` se registra la primera vez
  (usado para medir tiempos de atención en el Dashboard).
- **Referencia:** `POST /api/admin/sessions/{session_id}/reply`.

### CU-12: Pedirle ayuda al chatbot para redactar una respuesta

- **Actor:** Asesor de dependencia.
- **Precondición:** Está atendiendo una conversación (CU-11).
- **Flujo principal:**
  1. El asesor puede reescribir/mejorar la pregunta del estudiante (por
     si estaba muy corta o ambigua) en un campo separado.
  2. Presiona "Preguntar al asistente": el chatbot busca en los
     documentos oficiales y sugiere una respuesta con sus fuentes.
  3. El asesor decide: "Usar esta respuesta" (la copia al campo de
     respuesta para revisar/editar) o "Descartar".
  4. Nada se envía al estudiante automáticamente -- siempre requiere que
     el asesor presione "Enviar" explícitamente.
- **Postcondición:** Nada de este intercambio queda visible para el
  estudiante ni se guarda en el historial de la conversación.
- **Referencia:** `POST /api/admin/sessions/{session_id}/ask-bot`.

### CU-13: Preguntar "¿Necesita algo más?"

- **Actor:** Asesor de dependencia.
- **Referencia:** `POST /api/admin/sessions/{session_id}/ask-continue`
  (ver CU-05 para la respuesta del estudiante).

### CU-14: Marcar una conversación como resuelta

- **Actor:** Asesor de dependencia.
- **Flujo principal:**
  1. El asesor presiona "Marcar como resuelto".
  2. El chatbot vuelve a responder automáticamente al estudiante.
  3. Si la última respuesta del asesor sí resolvió una pregunta real, el
     sistema dispara CU-37 (sugerencia automática de FAQ).
- **Referencia:** `POST /api/admin/sessions/{session_id}/resolve`.

### CU-15: Redirigir una conversación a otra dependencia

- **Actor:** Asesor de dependencia (típicamente cuando el enrutamiento
  automático se equivocó).
- **Flujo principal:**
  1. Usa el selector "Redirigir a..." y elige la dependencia correcta.
  2. La conversación desaparece de su lista y aparece en la de la nueva
     dependencia; el estudiante recibe un aviso de que se sigue
     gestionando su solicitud.
- **Referencia:** `POST /api/admin/sessions/{session_id}/reassign`.

### CU-16: Consultar el Dashboard de su dependencia

- **Actor:** Asesor de dependencia.
- **Flujo principal:** Ve, en secciones plegables con un resumen visible
  a primera vista: conversaciones (escaladas/pendientes/resueltas,
  tiempos promedio, gráfica de tendencia), documentos (total y
  recientes), y preguntas frecuentes (pendientes/aceptadas/rechazadas) --
  todo limitado a su propia dependencia.
- **Referencia:** `GET /api/dashboard`, `app/services/dashboard_service.py`.

### CU-17: Subir un documento propio

- **Actor:** Asesor de dependencia.
- **Flujo principal:**
  1. Sube un archivo (PDF, TXT, DOCX o XLSX).
  2. Queda etiquetado automáticamente con su propia dependencia (no
     puede elegir otra).
  3. Se indexa automáticamente (CU-40); el chatbot puede usarlo en
     segundos.
- **Referencia:** `POST /api/admin/documents`.

### CU-18: Eliminar o archivar un documento propio

- **Actor:** Asesor de dependencia.
- **Precondición:** El documento pertenece a su propia dependencia.
- **Flujo alterno:** Intentar sobre un documento de otra dependencia →
  rechazado (403).
- **Referencia:** `DELETE /api/admin/documents/{filename}`,
  `PUT /api/admin/documents/{filename}/archive`.

### CU-19: Configurar el horario de atención de su dependencia

- **Actor:** Asesor de dependencia.
- **Flujo principal:**
  1. Define los días (lun-vie, etc.) y uno o más bloques horarios
     (permite horarios partidos, ej. por almuerzo).
  2. Ese horario es lo que consulta CU-03 para decidir si hay atención
     en línea al momento de escalar.
- **Flujo alterno:** Sin configurar (ambos campos vacíos) se trata como
  disponible siempre.
- **Referencia:** `PUT /api/admin/dependencias/{dependencia_id}/horario`,
  `app/services/admin_service.py::is_within_horario`.

### CU-20: Cambiar su propia contraseña

- **Actor:** Cualquier administrador autenticado (dependencia, general o root).
- **Referencia:** `POST /api/auth/change-password`.

---

## 3. Administrador general

Todo lo de la sección 2, pero sin quedar limitado a una sola
dependencia. Diferencias:

### CU-21: Ver todas las conversaciones del sistema

- **Actor:** Administrador general.
- **Flujo principal:** Ve las conversaciones escaladas de **todas** las
  dependencias, con la dependencia y el tiempo de espera visibles para
  cada una.
- **Flujo alterno:** Sobre una conversación de otra dependencia, solo
  puede **leerla** -- no responder ni resolver -- hasta reclamarla
  (CU-22).

### CU-22: Reclamar una conversación de otra dependencia

- **Actor:** Administrador general.
- **Flujo principal:** Usa "Redirigir a..." y se elige a sí mismo; a
  partir de ahí puede responderla y resolverla como cualquier otra.
- **Referencia:** `POST /api/admin/sessions/{session_id}/reassign`.

### CU-23: Gestionar documentos de cualquier dependencia

- **Actor:** Administrador general.
- **Flujo principal:** Ve y administra los documentos de **todas** las
  dependencias (paridad con root); al subir puede elegir cualquier
  dependencia o dejarlo general/compartido; puede **recategorizar**
  (cambiar la dependencia) un documento ya subido -- algo que un
  administrador de dependencia no puede hacer.
- **Referencia:** `PUT /api/admin/documents/{filename}` (recategorizar).

### CU-24: Ver el Dashboard agregado con desglose por dependencia

- **Actor:** Administrador general.
- **Flujo principal:** Ve los números agregados de todas las
  dependencias, más una tabla adicional "Conversaciones por
  dependencia" que un administrador de dependencia no ve.

### CU-25: Gestionar palabras de moderación

- **Actor:** Administrador general (exclusivo -- una dependencia no ve
  esta pestaña).
- **Flujo principal:** Agrega o elimina palabras/frases que activan el
  detector de hostilidad (ver CU-39). Comparte la misma lista que root.
- **Referencia:** `POST /api/admin/hostility-keywords`,
  `DELETE /api/admin/hostility-keywords/{keyword_id}`.

### CU-26: Gestionar los orígenes autorizados del widget embebible

- **Actor:** Administrador general (exclusivo -- una dependencia no ve
  esta pestaña).
- **Flujo principal:** Agrega o elimina dominios autorizados a embeber
  el chat como burbuja flotante; obtiene el snippet `<script>` para
  pegar en el sitio autorizado (ver CU-41).
- **Referencia:** `POST /api/admin/widget-origins`,
  `DELETE /api/admin/widget-origins/{origin_id}`,
  [widget-embebible.md](widget-embebible.md).

### CU-27: Configurar el horario de cualquier dependencia

- **Actor:** Administrador general.
- **Diferencia con CU-19:** No está limitado a una dependencia propia --
  puede configurar el horario de cualquiera desde el panel.

---

## 4. Administrador root

Todo lo de las secciones 2 y 3 (root también puede, técnicamente,
resolver conversaciones vía la misma API, aunque su panel `/root` está
pensado para **administrar el sistema**, no para atender estudiantes).
Adicional y exclusivo de root:

### CU-28: Configurar los datos de la institución

- **Actor:** Root.
- **Flujo principal:** Cambia el nombre de la institución (visible en el
  chat y en los encabezados de los paneles), una información adicional
  opcional, y el logo (PNG/JPG/SVG/WEBP).
- **Referencia:** `PUT /api/root/institution`.

### CU-29: Gestionar dependencias

- **Actor:** Root.
- **Flujo principal:**
  1. Crea una dependencia con nombre y descripción -- la descripción es
     la que usa el LLM para decidir el enrutamiento automático (CU-03),
     así que entre más específica, mejor.
  2. Puede editarla o eliminarla.
- **Flujo alterno:** No se puede eliminar una dependencia que todavía
  tenga un administrador asignado.
- **Referencia:** `POST /api/root/dependencias`,
  `DELETE /api/root/dependencias/{dependencia_id}`.

### CU-30: Gestionar cuentas de administrador

- **Actor:** Root.
- **Flujo principal:**
  1. Crea una cuenta: usuario (correo), contraseña (mínimo 8
     caracteres), nombre para mostrar, y rol (general, dependencia --
     eligiendo cuál -- o root).
  2. Puede editar (nombre/rol/dependencia), cambiarle la contraseña, o
     desactivar/activar la cuenta (una cuenta inactiva no puede iniciar
     sesión, pero conserva su historial).
- **Referencia:** `POST /api/root/admins`, `PUT /api/root/admins/{admin_id}`,
  `POST /api/root/admins/{admin_id}/set-password`,
  `POST /api/root/admins/{admin_id}/set-active`.

### CU-31: Gestionar documentos globales (paridad con CU-23, más archivo/vista previa)

- **Actor:** Root.
- **Flujo principal:** Sube, etiqueta, recategoriza, elimina, archiva o
  reactiva cualquier documento del sistema; puede previsualizar su
  contenido antes de decidir.
- **Referencia:** `POST /api/root/documents`,
  `PUT /api/root/documents/{filename}/archive`,
  `GET /api/root/documents/{filename}/preview`.

### CU-32: Revisar sugerencias automáticas de preguntas frecuentes

- **Actor:** Root.
- **Precondición:** El sistema generó al menos una sugerencia (CU-37).
- **Flujo principal:**
  1. Root lee la pregunta y respuesta sugeridas (puede editarlas antes
     de decidir).
  2. **Aceptar:** se agrega al documento de FAQ de la dependencia
     correspondiente y se reindexa automáticamente -- el chatbot puede
     responderla desde ese momento.
  3. **Descartar:** se elimina sin agregarse a ningún documento.
- **Referencia:** `POST /api/root/faq-candidates/{candidate_id}/accept`,
  `POST /api/root/faq-candidates/{candidate_id}/reject`.

### CU-33: Gestionar palabras de moderación globales

- **Actor:** Root (mismo mecanismo que CU-25, con alcance de todo el sistema).
- **Referencia:** `POST /api/root/hostility-keywords`.

### CU-34: Gestionar el widget embebible (alcance completo)

- **Actor:** Root (mismo mecanismo que CU-26).
- **Referencia:** `POST /api/root/widget-origins`.

### CU-35: Consultar el Dashboard completo del sistema

- **Actor:** Root.
- **Flujo principal:** Ve, en secciones plegables con un resumen visible
  a primera vista, todo lo de CU-24 más las secciones exclusivas de
  root: equipo de administración (dependencias y administradores
  activos/inactivos por rol), rendimiento del sistema (tiempos de
  respuesta del bot, uso de Groq y tasa de acierto de caché),
  preguntas sin respuesta suficiente (prioriza qué documentar), y
  feedback de estudiantes (👍/👎 y las peor calificadas).
- **Referencia:** `GET /api/dashboard` con
  `include_admin_and_performance=True`,
  `app/services/dashboard_service.py`.

---

## 5. Sistema (casos de uso automáticos)

Estos no los dispara ninguna persona directamente -- corren en segundo
plano como parte del comportamiento normal del sistema.

### CU-36: Auto-escalamiento por SLA vencido

- **Disparador:** Una conversación lleva más de 5 minutos
  (`AUTO_ESCALATION_TIMEOUT_SECONDS`) asignada a una dependencia sin que
  ningún asesor haya respondido todavía.
- **Flujo principal:** El sistema la redirige automáticamente hacia el
  administrador general (mismo mecanismo que CU-15/CU-22) y le avisa al
  estudiante que su solicitud se sigue gestionando -- sin que nadie
  tenga que hacer nada manualmente.
- **Referencia:** `app/main.py::_auto_escalation_loop`,
  `history_service.find_unattended_sessions`.

### CU-37: Generación automática de sugerencia de FAQ

- **Disparador:** Un asesor resuelve una conversación (CU-14) o el
  estudiante la marca como solucionada (CU-06) tras recibir una
  respuesta útil de un asesor.
- **Flujo principal:**
  1. El sistema reescribe esa pregunta y respuesta en formato
     profesional de FAQ (vía LLM).
  2. Compara contra las FAQ ya aceptadas de esa dependencia para evitar
     proponer un duplicado.
  3. Si es nueva, queda pendiente de revisión para root (CU-32).
- **Referencia:** `app/api/routes.py::_maybe_generate_faq_candidate`,
  `app/rag/llm.py::generate_faq_candidate`.

### CU-38: Indexación automática de un documento subido

- **Disparador:** Cualquier subida de documento (CU-17, CU-23, CU-31).
- **Flujo principal:**
  1. Si es PDF/DOCX, se convierte a `.txt`; si es XLSX, cada hoja se
     procesa como una "página" (ver
     [conceptos-chunks-y-faiss.md](conceptos-chunks-y-faiss.md)).
  2. El texto se divide en fragmentos (chunks) de 1000 caracteres con
     150 de traslape.
  3. Cada fragmento se convierte en un vector de 384 dimensiones
     (embeddings) y se agrega al índice FAISS.
- **Postcondición:** El documento es buscable por el chatbot sin
  reiniciar el servidor ni ningún paso manual adicional.
- **Referencia:** `app/rag/document_loader.py`, `app/rag/chunker.py`,
  [flujo-subida-documentos.md](flujo-subida-documentos.md).

### CU-39: Detección de hostilidad y bloqueo temporal

- **Disparador:** Un mensaje del estudiante contiene una palabra o frase
  de la lista de moderación (CU-25/CU-33).
- **Flujo principal:**
  1. El sistema cuenta un "aviso" para esa sesión.
  2. Al acumular 3 avisos seguidos (`HOSTILITY_STRIKE_LIMIT`), la sesión
     queda bloqueada temporalmente (2 horas, `HOSTILITY_BLOCK_HOURS`) --
     no puede seguir chateando desde esa sesión.
- **Nota de alcance:** El bloqueo es por `session_id`, no por IP -- más
  fácil de evitar abriendo una sesión nueva, pero sin riesgo de afectar
  a otros estudiantes que compartan la misma red.
- **Referencia:** `app/services/hostility_service.py`.

### CU-40: Respaldo automático de la base de datos

- **Disparador:** Cada `HISTORY_BACKUP_INTERVAL_SECONDS` mientras el
  servidor está corriendo.
- **Flujo principal:** Copia `history.db` a un respaldo, en un hilo
  aparte para no bloquear las conexiones WebSocket activas.
- **Referencia:** `app/main.py::_history_backup_loop`,
  `history_service.backup_now`.

---

## 6. Sitio anfitrión del widget

### CU-41: Embeber el chat como burbuja flotante en un sitio externo

- **Actor:** Un sitio web institucional autorizado (CU-26/CU-34).
- **Precondición:** Su dominio fue agregado a la lista de orígenes
  permitidos.
- **Flujo principal:**
  1. El sitio pega el snippet `<script src="...">` provisto por el panel.
  2. Al cargar la página, aparece un botón flotante; al hacer clic, se
     abre el chat embebido (`/widget`) dentro de un iframe.
  3. El backend arma dinámicamente la política CSP
     (`frame-ancestors`) para permitir solo los orígenes autorizados.
- **Flujo alterno:** Si el dominio no está autorizado, el navegador
  bloquea el iframe -- el chat no se muestra en ese sitio.
- **Postcondición:** Revocar el permiso (CU-26/CU-34) bloquea nuevas
  cargas del sitio de inmediato; una pestaña que ya tenía el chat
  abierto sigue funcionando hasta que se recargue.
- **Referencia:** [widget-embebible.md](widget-embebible.md),
  `app/services/widget_service.py`.
