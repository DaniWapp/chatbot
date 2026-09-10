# Flujo de escalamiento y atención humana

Este documento describe, paso a paso y con el mecanismo real, qué pasa
desde que un estudiante pide hablar con un asesor humano hasta que la
conversación se resuelve. Complementa
[flujo-chat-en-vivo.md](flujo-chat-en-vivo.md) (que cubre solo el chat
automático del bot, y explícitamente no entra en este flujo) y
[casos-de-uso.md](casos-de-uso.md) (que describe el mismo terreno desde
el punto de vista de qué puede hacer cada actor, no de cómo está
implementado por dentro).

## 1. El estudiante escala -- `POST /api/escalate`

1. El estudiante envía nombre, correo y, opcionalmente, un teléfono.
2. `_classify_department_for_session` decide a qué dependencia
   corresponde, en este orden de intentos:
   - Si no hay ninguna dependencia creada, o la sesión no tiene ninguna
     pregunta previa, se deja `dependencia_id=None` (bandeja del
     administrador general) sin llamar al LLM.
   - Si hay historial, se recupera contexto para la última pregunta
     (`chat_service.retrieve_context`, el mismo mecanismo que usa el
     bot para responder) y se le pasa al LLM la pregunta más los
     documentos relevantes con su dependencia ya etiquetada
     (`llm.classify_department`).
   - Cualquier fallo del LLM también cae en `None` -- clasificar mal
     nunca bloquea el escalamiento, en el peor caso la conversación
     queda en la bandeja general.
3. `history_service.escalate_session` guarda los datos de contacto,
   marca `needs_human=1` y registra `escalated_at` en `session_meta`.
4. Se notifica el evento `{"type": "escalated", ...}` vía
   `ws_manager.broadcast_to_dependencia(dependencia_id, ...)` -- llega a
   los paneles de esa dependencia específica y, siempre, a los de rol
   `general` (ver sección 4).
5. Se revisa `admin_service.is_within_horario(dependencia_id)`: si está
   fuera del horario configurado (ver
   [manual-usuario.md](manual-usuario.md#43-pestaña-dependencias)), la
   respuesta incluye el texto del horario para que el frontend le avise
   al estudiante que su pregunta quedó guardada para cuando abran.
6. Desde este momento, `chat_service.needs_human(session_id)` devuelve
   `True` y el bot deja de responder automáticamente en esta sesión
   (verificado al inicio de `stream_answer`, ver
   [flujo-chat-en-vivo.md](flujo-chat-en-vivo.md#3-núcleo-del-pipeline----appserviceschat_servicepystream_answer)).

## 2. El asesor responde -- `POST /admin/sessions/{id}/reply`

1. `require_conversation_admin` exige una sesión de administrador válida
   (rol `dependencia` o `general`; root nunca llega a esta ruta).
2. `_ensure_admin_can_act_on_session` exige que la conversación esté
   asignada **ahora mismo** a la dependencia de ese administrador. El
   general no tiene pase libre aquí (a diferencia de solo leerla, ver
   sección 4): si la conversación es de otra dependencia, debe
   reclamarla primero (sección 5).
3. Se calcula el nombre a mostrar (`_advisor_label`, ver sección 6) y se
   guarda el mensaje (`history_service.add_admin_message`, `sender=
   "advisor"`) -- la primera vez marca también `first_response_at`
   (usado por el Dashboard para medir tiempos de atención).
4. Se difunde el mismo evento `{"type": "advisor_message", ...,
   "advisor_name": ...}` por dos canales distintos, con scope distinto:
   - `_broadcast_session_event` → `ws_manager.broadcast_to_dependencia`:
     para que **otros** asesores de la misma dependencia (y el general)
     vean la respuesta en tiempo real si tienen la conversación abierta.
   - `ws_manager.broadcast_to_session`: para el chat del **estudiante**
     (solo le llega si tiene el chat abierto en ese momento -- si no,
     lo recibe al cargar el historial la próxima vez, ver sección 7).

`POST /admin/sessions/{id}/ask-continue` (el botón "¿Necesita algo
más?") sigue exactamente el mismo mecanismo, con `message_type="checkin"`
y un texto fijo en vez del mensaje libre del asesor.

## 3. Herramienta de apoyo del asesor -- `POST /admin/sessions/{id}/ask-bot`

Reutiliza el mismo pipeline de recuperación + LLM que usa el bot
(`chat_service.draft_answer_for_admin`), pero **no guarda nada** en el
historial de la conversación ni se transmite a nadie por WebSocket -- el
resultado vive solo en la respuesta HTTP de esta llamada. Es la
diferencia clave frente a `reply`: nada de esto llega al estudiante a
menos que el asesor copie el texto al campo de respuesta y presione
"Enviar" (que sí pasa por el flujo de la sección 2). Al reutilizar ese
mismo pipeline, la respuesta sugerida al asesor también se beneficia del
filtrado por fuentes realmente usadas (`FUENTES_USADAS`, ver
[flujo-chat-en-vivo.md](flujo-chat-en-vivo.md)) -- no cita fragmentos que
pasaron el re-ranking pero que el LLM no usó de verdad.

## 4. Quién ve y quién puede actuar sobre una conversación

Dos chequeos de autorización distintos, con reglas distintas a propósito:

| | `_ensure_admin_can_view_session` | `_ensure_admin_can_act_on_session` |
|---|---|---|
| Rol `dependencia` | Solo las suyas (`dependencia_id` coincide) | Solo las suyas |
| Rol `general` | **Cualquiera** (supervisor de todo el sistema) | Solo las asignadas a él (`dependencia_id IS NULL`) |

El general puede leer cualquier conversación de cualquier dependencia
(para supervisar), pero no responderla ni resolverla hasta reclamarla
(sección 5) -- evita que "supervisar" se confunda con "intervenir sin
que la dependencia dueña se entere".

`_ensure_admin_can_view_session` es control de acceso real, no solo
ocultamiento en la lista: conocer un `session_id` ajeno (por ejemplo
copiado de la URL) no basta para leer una conversación de otra
dependencia.

## 5. Redirigir/reclamar una conversación -- `_perform_reassignment`

Helper único, reusado por dos disparadores distintos:

- **Manual:** `POST /admin/sessions/{id}/reassign` (el selector
  "Redirigir a..." del panel).
- **Automático:** `app/main.py::_auto_escalation_loop`, cada
  `AUTO_ESCALATION_CHECK_INTERVAL_SECONDS`, para las conversaciones que
  llevan más de `AUTO_ESCALATION_TIMEOUT_SECONDS` (5 minutos por
  defecto) asignadas sin que nadie haya respondido todavía
  (`history_service.find_unattended_sessions`, que usa exactamente
  `first_response_at IS NULL` como señal de "sin atender").

En ambos casos, `_perform_reassignment` reasigna en la base de datos y
dispara **tres** notificaciones: a la dependencia anterior (para que
desaparezca de su lista), a la nueva (para que aparezca en la suya), y
al estudiante (`"Seguimos gestionando tu solicitud; en breve un asesor
te atenderá."`) -- así el auto-escalamiento por SLA se ve, desde el
punto de vista de todos los involucrados, exactamente igual que una
redirección manual.

## 6. De dónde sale el nombre que ve el estudiante -- `_advisor_label`

El estudiante nunca ve la etiqueta genérica "Asesor" salvo en mensajes
guardados antes de que existiera este mecanismo. Desde `reply_to_session`
y `ask_continue`, `_advisor_label(identity)` construye el texto real:

```python
def _advisor_label(identity: AdminIdentity) -> str:
    if identity.dependencia_id is None:
        return identity.display_name
    dependencia = admin_service.get_dependencia(identity.dependencia_id)
    if not dependencia:
        return identity.display_name
    return f"{identity.display_name} · {dependencia['name']}"
```

- Rol `dependencia`: `"Nombre · Nombre de su dependencia"`.
- Rol `general`: solo `"Nombre"` -- no está vinculado a ninguna
  dependencia en particular, aunque supervise todas.

Ese texto se **guarda**, no solo se transmite: la columna
`admin_messages.sender_name` (migrada con `_ensure_column`, `TEXT`
nulable) persiste el resultado exacto de `_advisor_label` en el momento
del envío. Guardarlo en vez de recalcularlo al leer tiene una razón
concreta: si el admin cambia después su nombre para mostrar o su
dependencia (`PUT /root/admins/{id}`), los mensajes ya enviados siguen
mostrando quién los escribió *en ese momento*, no quién es ese admin
hoy.

`SessionMessage.sender_name` (`Optional[str] = None`) expone ese campo
en ambos endpoints de historial (`GET /sessions/{id}/history`, público
para el estudiante, y `GET /admin/sessions/{id}/messages`, para el
panel). El frontend (`frontend/script.js`) usa
`escapeHtml(advisorName || "Asesor")` en cada burbuja de asesor -- el
`|| "Asesor"` es exactamente lo que cubre los mensajes anteriores a este
cambio, que tienen `sender_name = NULL`.

## 7. Reconectar sin perder mensajes

El WebSocket de sesión (`ws_manager.broadcast_to_session`) solo entrega
mensajes a quien tiene el chat **abierto en ese instante** -- no hay cola
de mensajes pendientes por WebSocket. Dos mecanismos cubren el resto:

- **Historial paginado** (`get_history_page` /
  `GET /sessions/{id}/history`): al cargar el chat, siempre se trae la
  transcripción completa guardada (turnos del bot + `admin_messages`),
  con `sender_name` incluido -- así una respuesta enviada mientras el
  estudiante tenía la pestaña cerrada aparece igual al volver a abrirla.
- **`catchUpMissedMessages`** (`frontend/script.js`): si la pestaña
  estuvo en segundo plano, el navegador puede congelar el WebSocket sin
  avisar (se sigue viendo "conectado" pero ya no llegan mensajes). Al
  recuperar el foco, el frontend vuelve a pedir el historial desde
  `latestRenderedMessageAt` para rellenar el hueco, en vez de confiar en
  que la reconexión del WebSocket sola baste.

## 8. Cierre -- resolver la conversación

`POST /admin/sessions/{id}/resolve` (o `POST
/sessions/{id}/mark-solved` desde el lado del estudiante, ver
CU-06/CU-14 en [casos-de-uso.md](casos-de-uso.md)) marca `resolved_at` y
dispara `_maybe_generate_faq_candidate`: si la última respuesta del
asesor sí resolvió algo, el sistema reescribe esa pregunta/respuesta en
formato de FAQ vía LLM y la deja pendiente de revisión para root (tabla
`faq_candidates`) -- documentado en detalle como CU-37 en
[casos-de-uso.md](casos-de-uso.md#cu-37-generación-automática-de-sugerencia-de-faq).
A partir de aquí, `chat_service.needs_human` vuelve a ser `False` y el
bot retoma el control de la sesión.
