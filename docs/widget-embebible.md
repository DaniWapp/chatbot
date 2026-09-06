# Widget embebible: cómo funciona

Este documento explica el mecanismo técnico detrás de embeber el chat como
una burbuja flotante en otros sitios institucionales. Para cómo *usarlo*
desde `/root`/`/panel`, ver
[manual-usuario.md, sección 4.7](manual-usuario.md#47-pestaña-widget).

## Las tres piezas

1. **`frontend/widget-loader.js`** -- el único archivo que un sitio
   anfitrión necesita pegar:
   ```html
   <script src="https://chatbot.nubecol.com/static/widget-loader.js"></script>
   ```
   Es JS autocontenido, sin dependencias: calcula su propio origen con
   `document.currentScript.src` (así funciona igual sin hardcodear el
   dominio), inyecta un botón flotante y, al hacer clic, crea un
   `<iframe src="<origen>/widget">` (~380×600px en escritorio, pantalla
   completa en móvil).

2. **`/widget`** (`app/main.py::serve_widget`) -- una página de chat
   compacta. Reutiliza **exactamente** `frontend/script.js` y
   `frontend/style.css` sin fork (`frontend/widget.html` tiene el mismo
   `<body>`, los mismos ids, los mismos `<script>` que `index.html`);
   `frontend/widget.css` solo sobreescribe lo necesario para que quepa en
   un panel angosto (oculta la cabecera de marca, quita el
   centrado/max-width de página completa).

3. **Orígenes permitidos** (`widget_allowed_origins` en `history.py`,
   `app/services/widget_service.py`) -- la lista, editable por root/admin
   general desde `/root` y `/panel`, de qué sitios pueden embeberlo.

## La restricción real: CSP `frame-ancestors`

Cada vez que se pide `/widget`, el backend arma la cabecera de la
respuesta **en ese momento**, consultando la tabla:

```python
origins = widget_service.list_origins()
sources = " ".join(o["origin"] for o in origins) or "'none'"
headers = {**_NO_CACHE_HEADERS, "Content-Security-Policy": f"frame-ancestors {sources}"}
```

`frame-ancestors` es la directiva CSP que le dice al navegador "solo
déjame cargar dentro de un iframe si la página que me embebe es uno de
estos orígenes". **Sin ninguna URL agregada, el valor es `'none'` --
fail-closed por defecto: nadie puede embeberlo hasta que un admin
autorice un sitio explícitamente.**

Puntos importantes sobre esta restricción:

- **Es del navegador, no un chequeo de este backend.** El servidor sirve
  `/widget` igual sin importar quién lo pida -- es el navegador del
  visitante el que decide, al ver la cabecera, si deja que la página
  anfitriona muestre ese iframe o lo bloquea.
- **Se evalúa solo al cargar el iframe, no de forma continua.** Si un
  sitio estaba autorizado, cargó el chat, y *después* un admin quita ese
  origen de la lista, la pestaña que ya tenía el iframe abierto sigue
  funcionando -- el navegador no vuelve a chequear un frame ya cargado.
  El cambio aplica en el **siguiente intento de carga** (recargar la
  página o abrir una pestaña nueva).
- **No se toca `CORSMiddleware`/`ALLOWED_ORIGINS` para nada de esto.** El
  iframe hace sus llamadas (`/api/chat/stream`, etc.) al mismo origen de
  su propio `src` -- es decir, al backend del chatbot, no al origen del
  sitio anfitrión. Eso es una petición del mismo origen desde el punto de
  vista del navegador, así que CORS no interviene. `ALLOWED_ORIGINS` sigue
  siendo un mecanismo aparte, para llamadas *cross-origin* de verdad.
- **No hay cookies de sesión involucradas.** El chat (`/api/chat/stream`
  y el resto de endpoints de estudiante) nunca usó cookies -- el
  `session_id` viaja siempre como campo explícito del cuerpo/URL de cada
  petición (ver [flujo-chat-en-vivo.md](flujo-chat-en-vivo.md)). Esto evita
  por completo el problema clásico de cookies de sesión bloqueadas en
  iframes de terceros (Safari ITP, partición de almacenamiento de Chrome,
  etc.) -- el mecanismo de este chatbot ni siquiera depende de eso.

## Cómo se guarda una URL

`widget_service.add_origin(raw_url)` acepta la URL completa de una página
(por conveniencia, para que un admin pueda simplemente copiar la barra de
direcciones del sitio) pero solo guarda su **origen real**:

```python
parsed = urlparse(raw_url.strip())
# exige scheme in {http, https} y netloc no vacío
normalized = f"{parsed.scheme}://{parsed.netloc}".lower()
```

`https://facultad.edu.co/admisiones?ref=x` se guarda como
`https://facultad.edu.co` -- es lo único que `frame-ancestors` necesita
(y lo único que tiene sentido comparar: el navegador reporta el origen de
la página, no su ruta completa).

## Verificarlo manualmente

```bash
curl -sD - -o /dev/null http://localhost:8000/widget | grep -i content-security-policy
```

Sin orígenes agregados: `content-security-policy: frame-ancestors 'none'`.
Con al menos uno agregado: aparece en la lista, separado por espacios.
