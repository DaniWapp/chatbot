# Manual de usuario

Guía de uso del chatbot para cada tipo de usuario del sistema: estudiantes,
asesores de dependencia, el administrador general, y el administrador root.
Para la documentación técnica del proyecto ver el
[README.md](../README.md); este manual solo cubre **cómo usar** cada
pantalla.

## Índice

1. [Estudiantes: el chat](#1-estudiantes-el-chat)
2. [Asesores: el panel de atención (`/panel`)](#2-asesores-el-panel-de-atención-panel)
3. [Administrador general: particularidades](#3-administrador-general-particularidades)
4. [Root: panel de administración (`/root`)](#4-root-panel-de-administración-root)
5. [Preguntas frecuentes / solución de problemas](#5-preguntas-frecuentes--solución-de-problemas)

---

## 1. Estudiantes: el chat

Dirección: la página principal del sitio (por ejemplo `https://chatbot.nubecol.com`).

### 1.1 Hacer una pregunta

1. Escribe tu pregunta en el cuadro de texto de abajo ("Escribe tu pregunta...").
2. Presiona **Enviar** (o Enter).
3. La respuesta aparece palabra por palabra, basada únicamente en los
   documentos oficiales cargados por la institución.

### 1.2 Cuando el chatbot no tiene la respuesta

Si el chatbot no encuentra información suficiente, puede pasar dos cosas:

- **Te propone hasta 3 preguntas alternativas** que sí puede responder,
  por si tu pregunta estaba escrita de forma muy corta o ambigua. Haz clic
  en la que se parezca a lo que querías preguntar.
- Aparece el botón **"Solicitar atención humana"**. Al hacer clic:
  1. Completa **Nombre completo** y **Correo electrónico**.
  2. Presiona **Enviar**.
  3. Tu conversación queda en manos de un asesor humano, que te responderá
     ahí mismo (no necesitas recargar la página ni volver a escribir).

### 1.3 Mientras esperas o hablas con un asesor humano

- Verás un aviso indicando que tu pregunta fue enviada a un asesor.
- Si nadie te atiende en varios minutos, el sistema redirige
  automáticamente tu conversación a otro administrador y te avisa que se
  sigue gestionando tu solicitud — no tienes que hacer nada.
- Cuando el asesor te responde, el mensaje aparece en tu chat en tiempo real.
- El asesor puede preguntarte "¿Te puedo ayudar con algo más?" — responde
  Sí o No con los botones que aparecen.

### 1.4 Marcar tu conversación como solucionada

Con el botón **"Marcar como solucionado"** (visible arriba, mientras estás
en atención humana) le devuelves el control al asistente virtual: vuelve a
responder automáticamente tus próximas preguntas, en vez de esperar a un
asesor.

---

## 2. Asesores: el panel de atención (`/panel`)

Dirección: `/panel` (por ejemplo `https://chatbot.nubecol.com/panel`).
Requiere una cuenta de administrador (rol **dependencia** o **general**)
creada previamente por el root.

### 2.1 Iniciar sesión

Ingresa tu usuario (correo electrónico) y contraseña, y presiona **Entrar**.

### 2.2 La lista de conversaciones

- A la izquierda ves todas las conversaciones escaladas que te corresponden
  (si eres administrador de una dependencia, solo las tuyas; si eres
  **general**, ver la sección 3).
- El botón **"X pendientes"** filtra solo las que aún no tienen respuesta.
- Haz clic en una conversación para abrirla.

### 2.3 Atender una conversación

Al abrir una conversación verás:

- El historial completo (lo que el estudiante preguntó, lo que el bot
  respondió antes de escalar, y los mensajes de asesor/estudiante desde
  que se escaló).
- **"Reescribe la pregunta del estudiante para consultar al asistente..."**:
  un campo ya prellenado con la última pregunta del estudiante — ver 2.4.
- El campo **"Escribe tu respuesta como asesor..."** para responder
  directamente.
- Botones de acción: **"¿Necesita algo más?"** y **"Marcar como resuelto"**.
- El selector **"Redirigir a..."** para enviar la conversación a otra
  dependencia (o a ti mismo, si eres el general y quieres reclamarla).

### 2.4 Pedirle ayuda al chatbot para responder (herramienta del asesor)

Si no sabes qué responder, puedes apoyarte en el propio chatbot **sin que
el estudiante vea nada de esto**:

1. En el campo superior, edita/mejora la pregunta del estudiante si hace
   falta (por ejemplo, si la escribió de forma muy corta o ambigua).
2. Presiona **"Preguntar al asistente"**.
3. El chatbot busca en los documentos oficiales y te muestra una respuesta
   sugerida, con sus fuentes.
4. Decide:
   - **"Usar esta respuesta"**: la copia al campo de respuesta del asesor,
     para que la revises/edites antes de enviarla.
   - **"Descartar"**: la borra sin usarla; puedes reformular la pregunta y
     volver a intentar, o escribir la respuesta completamente a mano.
5. Nunca se envía nada automáticamente al estudiante — siempre debes
   presionar **Enviar** en el campo de respuesta del asesor tú mismo.

Si el chatbot tampoco encuentra información, te lo indica claramente: en
ese caso, escribe la respuesta manualmente con la información real que
tengas.

### 2.5 Resolver o continuar la conversación

- **"¿Necesita algo más?"**: le pregunta al estudiante si necesita algo
  más (responde con botones Sí/No desde su chat).
- **"Marcar como resuelto"**: cierra la atención humana; el chatbot vuelve
  a responder automáticamente al estudiante. Si tu respuesta fue útil, el
  sistema puede proponerle al root (ver sección 4.6) agregarla como
  pregunta frecuente.

### 2.6 Dashboard (pestaña "Dashboard")

Todo administrador (dependencia o general) tiene una pestaña **Dashboard**
junto a "Conversaciones" con un resumen de la actividad reciente:

- **Tarjetas de números**: conversaciones escaladas, resueltas, pendientes
  ahora, escaladas en los últimos 7 días, tiempo promedio de primera
  respuesta y de resolución, documentos indexados y su tamaño total, y
  preguntas frecuentes pendientes/aceptadas.
- **Gráfica de conversaciones escaladas por día** (últimos 30 días).
- **Documentos recientes**: los últimos archivos subidos o modificados.
- Si eres **administrador de dependencia**, todo lo anterior está
  limitado a **tu propia dependencia**. Si eres **general**, ves los
  números agregados de **todas** las dependencias, más una tabla
  adicional de "Conversaciones por dependencia" con el desglose de cada
  una.

### 2.7 Documentos (pestaña "Documentos")

Todo administrador (dependencia o general) puede subir y eliminar
documentos directamente desde el panel, sin depender de root:

1. Presiona **"Documentos"** en la parte superior del panel.
2. Verás la lista de documentos que puedes gestionar:
   - Si eres **administrador de dependencia**, solo ves (y puedes subir o
     eliminar) los documentos etiquetados con **tu propia dependencia** —
     no ves los de otras dependencias ni los generales/compartidos, y no
     puedes elegir otra dependencia al subir: siempre queda etiquetado
     con la tuya automáticamente.
   - Si eres **general**, ves y administras **todos** los documentos de
     todas las dependencias (igual que root), incluida la opción de
     recategorizar (cambiar la dependencia de un documento ya subido).
3. **"+ Subir documento"**: elige un archivo (PDF, TXT, DOCX o XLSX) y
   confirma. Se indexa automáticamente en unos segundos — no hace falta
   ningún paso adicional para que el chatbot empiece a usarlo.
4. **"Eliminar"**: quita el documento y su contenido del índice del
   chatbot de inmediato.

---

## 3. Administrador general: particularidades

El rol **general** es el supervisor de todo el sistema, con algunas
diferencias respecto a un administrador de dependencia normal:

- **Ve todas** las conversaciones escaladas, sin importar a qué dependencia
  fueron asignadas — con la dependencia y el tiempo de espera visibles.
- Sobre una conversación que pertenece a otra dependencia, **solo puede
  leerla** (no responder ni resolver) hasta que la **reclame**: usa el
  selector "Redirigir a..." y elige redirigirla hacia ti mismo.
- Si una dependencia no atiende una conversación en 5 minutos, el sistema
  la redirige automáticamente hacia el general (y notifica al estudiante
  que su solicitud se sigue gestionando) — es un respaldo automático, no
  requiere ninguna acción manual.
- En la pestaña **"Documentos"** (ver 2.7), el general tiene exactamente
  las mismas capacidades que root: ve todos los documentos de todas las
  dependencias, puede subir eligiendo cualquier dependencia (o dejarlo
  general/compartido), recategorizar y eliminar cualquiera.
- En la pestaña **"Dashboard"** (ver 2.6), el general ve los números
  agregados de todas las dependencias, con el desglose adicional por
  dependencia que un administrador de dependencia no ve.

---

## 4. Root: panel de administración (`/root`)

Dirección: `/root`. Requiere una cuenta con rol **root** (se crea la
primera vez desde el servidor con `scripts/create_root.py`; el resto de
administradores los crea el propio root desde este panel). El root **no**
atiende conversaciones — administra el sistema.

### 4.1 Pestaña "Dashboard"

Es la primera pestaña, la que se abre al iniciar sesión. Resume lo más
importante que ha sucedido en todo el sistema:

- **Tarjetas de números**: conversaciones escaladas, resueltas, pendientes
  ahora, escaladas en los últimos 7 días, tiempos promedio de primera
  respuesta y de resolución, documentos indexados y su tamaño total,
  preguntas frecuentes pendientes/aceptadas, dependencias activas y
  administradores activos, tiempo de respuesta del bot y uso de Groq
  (llamadas totales, últimos 7 días y fallidas).
- **Dos gráficas** (últimos 30 días): conversaciones escaladas por día, y
  llamadas a Groq por día.
- **Tabla "Conversaciones por dependencia"**: cuántas conversaciones ha
  recibido cada dependencia.
- **Tabla "Documentos recientes"**: los últimos archivos subidos o
  modificados.

Root es el único rol que ve las secciones de equipo de administración y
de rendimiento/Groq -- general y dependencia (ver 2.6) solo ven las
secciones de conversaciones, documentos y FAQ.

### 4.2 Pestaña "Institución"

- Cambia el **nombre de la institución** (aparece en el chat y en el
  encabezado de los paneles) y una **información adicional** opcional.
- **"Cambiar logo"**: sube una imagen (PNG, JPG, SVG o WEBP) para el logo
  que ven los estudiantes y administradores.
- Presiona **"Guardar cambios"**.

### 4.3 Pestaña "Dependencias"

- **"+ Nueva dependencia"**: crea un departamento/facultad/oficina con
  **nombre** y **descripción**.
- La descripción es importante: el chatbot la usa para decidir
  automáticamente a qué dependencia redirigir cada pregunta escalada —
  entre más clara y específica, mejor el enrutamiento.
- Puedes editar o eliminar una dependencia existente desde la tabla (no se
  puede eliminar una que todavía tenga un administrador asignado).

### 4.4 Pestaña "Administradores"

- **"+ Nuevo administrador"**: crea una cuenta con:
  - **Usuario**: debe ser un correo electrónico (ej. `nombre@institucion.com`).
  - **Contraseña** (mínimo 8 caracteres).
  - **Nombre para mostrar**.
  - **Rol**: General, Dependencia, o Root.
  - Si el rol es **Dependencia**, elige a cuál.
- Desde la tabla puedes: **Editar** (nombre/rol/dependencia), cambiar su
  **Contraseña**, o **Desactivar/Activar** la cuenta (una cuenta inactiva
  no puede iniciar sesión, pero no se borra su historial).

### 4.5 Pestaña "Documentos"

- **"+ Subir documento"**: sube un archivo (PDF, TXT, DOCX o XLSX) y,
  opcionalmente, **etiquétalo con una dependencia** (o déjalo como
  "General / compartido"). Etiquetar un documento ayuda al chatbot a
  decidir a quién redirigir las preguntas relacionadas con su contenido.
- Cada documento se indexa automáticamente al subirlo (no hace falta
  ningún paso adicional) — la respuesta puede tardar unos segundos
  mientras se procesa.
- Puedes **recategorizar** (cambiar la dependencia de un documento ya
  subido) o **eliminarlo** desde la tabla.

### 4.6 Pestaña "Preguntas frecuentes" (sugeridas automáticamente)

Cuando un asesor resuelve una conversación que sí respondió, el sistema
reescribe esa pregunta y respuesta en formato profesional de FAQ y la deja
aquí, pendiente de revisión (evitando duplicar una FAQ que ya existe):

1. Lee la **"Pregunta sugerida"** y la **"Respuesta sugerida"**.
2. Puedes **editar el texto** libremente antes de decidir.
3. **"Aceptar"**: se agrega al documento de preguntas frecuentes de la
   dependencia correspondiente y se reindexa automáticamente — el chatbot
   ya puede responder esa pregunta a partir de ese momento.
4. **"Descartar"**: la propuesta se elimina sin agregarse a ningún documento.

---

## 5. Preguntas frecuentes / solución de problemas

**El chatbot dice "No encontré información suficiente" pero sí debería
saberlo.**
Puede que el documento correspondiente no esté cargado, no esté bien
etiquetado, o que la pregunta sea muy corta/ambigua (prueba con las
sugerencias que ofrece, o reformúlala con más detalle). Si de verdad falta
información, avísale al root para que suba o corrija el documento.

**Olvidé mi contraseña de administrador.**
Pide al root que te la cambie desde la pestaña "Administradores" → botón
**"Contraseña"** de tu usuario.

**No veo el botón para responder/resolver una conversación (como
administrador general).**
Debes reclamarla primero: usa "Redirigir a..." y elige redirigirla hacia
ti mismo (ver sección 3).

**Subí un documento y el chatbot sigue sin usarlo.**
Espera unos segundos (la ingesta puede tardar un poco en archivos grandes)
y vuelve a preguntar. Si sigue sin funcionar, confirma que el archivo no
esté vacío o dañado, y que el formato sea uno de los permitidos (PDF, TXT,
DOCX, XLSX).

**El estudiante ve la pregunta que reescribí para consultar al asistente.**
No — esa reescritura es privada del asesor; el estudiante solo ve lo que
el asesor decide enviarle con el botón "Enviar" del campo de respuesta.
