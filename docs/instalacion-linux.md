# Instalación en un servidor Linux (VPS), paso a paso por SSH

El [README.md](../README.md) (sección 6) explica cómo instalar el
proyecto en Windows para desarrollo local. Esta guía es el equivalente
para un **servidor Linux real** (un VPS, alquilado o propio), pensada
para dejarlo accesible desde internet con su propio dominio y HTTPS --
exactamente el mismo tipo de despliegue que ya usa en producción el
ejemplo real de este repositorio (`chatbot.nubecol.com`).

Todo se hace por **SSH**, sin necesidad de acceso gráfico al servidor. No
necesitas subir ningún archivo desde tu computador: todo el código se
descarga con `git clone` directamente en el servidor.

## 0. Alcance y qué vas a necesitar

- Un servidor Linux recién creado, con acceso por SSH y un usuario con
  privilegios `sudo` (la mayoría de proveedores de VPS te dan esto por
  defecto).
- Un dominio (o subdominio) que ya apunte a la IP pública del servidor --
  solo hace falta a partir del paso 14 (HTTPS). Si todavía no tienes uno,
  puedes hacer todos los pasos anteriores igual y usar la IP del servidor
  directamente (sin HTTPS) mientras tanto.
- Una clave de API de Groq gratuita (se explica cómo sacarla en el
  [README.md, sección 6.2](../README.md)).

## 1. Elegir el servidor: qué distribución instalar

**Recomendación: Ubuntu Server 24.04 LTS ("Noble Numbat").** No es una
recomendación genérica -- es exactamente el sistema operativo que corre
hoy en producción el despliegue real de este proyecto, verificado por
SSH. Razones concretas:

- **LTS**: recibe parches de seguridad oficiales hasta 2029 -- no vas a
  tener que migrar de sistema operativo a mitad de un semestre.
- **Trae Python 3.12 de fábrica** (`python3 --version` → `Python
  3.12.3`), sin necesidad de repositorios de terceros ni compilar Python
  a mano.
- Con esta combinación (Ubuntu 24.04 + Python 3.12), **ninguna
  dependencia del proyecto necesita compilador** -- `faiss-cpu`, PyTorch
  (que trae `sentence-transformers` por debajo) y `bcrypt` tienen
  paquetes ya compilados ("wheels") disponibles para esta combinación
  exacta de sistema operativo y versión de Python. Es el mismo criterio
  que el README ya documenta para Windows (por qué se eligió FAISS en vez
  de ChromaDB), confirmado también para Linux.

> **Nota sobre la versión de Python**: vas a ver que otros documentos de
> este proyecto mencionan versiones distintas (el README pide "3.11 o
> superior", `stack-tecnologico.md` menciona "3.12"). Para Linux, usa
> **3.12** -- es la que ya está probada funcionando en producción.

Si tu proveedor de VPS no ofrece Ubuntu 24.04 exactamente, cualquier
versión 22.04 o más reciente funciona igual de bien (con Python 3.10/3.11
del sistema, o instalando 3.12 aparte); lo único que cambia son los
nombres exactos de los paquetes en el paso 4.

**Tamaño mínimo recomendado: 2 vCPU / 4 GB de RAM.** El modelo de
embeddings y el modelo de re-ranking se cargan completos en memoria RAM
(~1.2 GB medidos en producción real) -- con menos de 4 GB el sistema
operativo queda muy justo de margen.

## 2. Primer acceso por SSH y actualización del sistema

```bash
ssh tu_usuario@la_ip_de_tu_servidor
sudo apt update && sudo apt upgrade -y
```

## 3. Crear un usuario para correr la aplicación (opcional, recomendado)

Si vas a usar el mismo usuario con el que te conectaste por SSH, puedes
saltarte este paso. Si prefieres (buena práctica) que la aplicación corra
con un usuario dedicado en vez de tu usuario personal o root:

```bash
sudo adduser administrator
sudo usermod -aG sudo administrator
su - administrator
```

El resto de esta guía asume que estás operando como ese usuario (o el
tuyo propio) -- **nunca como root directamente**.

## 4. Instalar las dependencias del sistema

Un solo comando instala todo lo que hace falta a nivel de sistema
operativo:

```bash
sudo apt install -y python3 python3-venv python3-pip git nginx certbot python3-certbot-nginx sqlite3
```

**No hace falta instalar `build-essential` ni ningún compilador de C/C++**
-- aunque el proyecto usa PyTorch por debajo (vía `sentence-transformers`),
todas las dependencias pesadas ya vienen precompiladas para esta
combinación de sistema operativo y Python, igual que se explicó en el
paso 1.

## 5. Clonar el repositorio

```bash
sudo mkdir -p /opt/chatbot-facultad
sudo chown $USER:$USER /opt/chatbot-facultad
git clone https://github.com/DaniWapp/chatbot.git /opt/chatbot-facultad
cd /opt/chatbot-facultad
```

`/opt/chatbot-facultad` es la misma ruta que usa el despliegue real de
producción -- puedes usar otra si prefieres, pero recuerda ajustarla en
los pasos 12 y 13 más adelante.

## 6. Crear el entorno virtual e instalar las dependencias de Python

```bash
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
```

> La primera instalación puede tardar varios minutos porque descarga
> PyTorch (usado internamente por Sentence Transformers) -- es normal,
> no se quedó pegado.

## 7. Configurar las variables de entorno (`.env`)

```bash
cp .env.example .env
nano .env
```

El archivo trae valores por defecto pensados para desarrollo local. Para
un servidor real, revisa especialmente estas:

| Variable | Qué poner | Por qué |
|---|---|---|
| `GROQ_API_KEY` | Tu clave real de Groq | **Obligatoria** -- sin ella el chatbot no puede generar respuestas. |
| `ALLOWED_ORIGINS` | `https://tudominio.com` (tu dominio real) | El valor por defecto (`http://localhost:8000`) bloquea el chat por CORS en cuanto lo abras desde tu dominio real. |

Todas las demás variables (tamaños de chunk, umbrales de similitud,
límites de Groq, etc.) tienen un valor por defecto razonable -- no hace
falta tocarlas para una primera instalación. `BACKEND_HOST`/
`BACKEND_PORT` de este archivo son para cuando corres uvicorn directo
(paso 10); en producción, el puerto real lo fija el propio comando dentro
del servicio systemd (paso 12), no esta variable.

## 8. Construir el índice vectorial con los documentos de ejemplo

```bash
venv/bin/python scripts/ingest.py
```

Esto no depende de nada externo a GitHub: el repositorio ya incluye 3
documentos de ejemplo (marcados `_EJEMPLO`) que se descargaron solos con
el `git clone` del paso 5. El comando los lee, los divide en fragmentos,
genera sus vectores (embeddings) localmente y construye la base vectorial
FAISS en `vector_db/` -- justo lo necesario para probar que todo el
pipeline funciona de punta a punta antes de tener documentos reales.

> La primera corrida necesita salida a internet: descarga (una sola vez)
> el modelo de embeddings y el modelo de re-ranking desde internet. Si tu
> servidor tiene un firewall de salida restrictivo, asegúrate de permitir
> tráfico HTTPS saliente al menos para esta primera ejecución.

## 9. Cómo se agregarán los documentos reales (más adelante, no ahora)

A diferencia de los documentos de ejemplo, **los documentos reales de tu
institución NO se suben por SSH, `scp` ni `rsync`**. Una vez el servidor
esté completamente arriba (después del paso 14), se agregan **desde el
navegador**, entrando al panel de administración en
`https://tudominio.com/root` → pestaña **Documentos** → **Subir**. Subir
un documento ahí ya dispara automáticamente su indexación -- no hace
falta volver a entrar por SSH para eso. Ver
[manual-usuario.md](manual-usuario.md) para el detalle de esa pantalla.

Este paso queda aquí solo como referencia de qué va a pasar más adelante;
sigue con el paso 10 usando todavía los documentos de ejemplo.

## 10. Probar manualmente antes de automatizar nada

Antes de configurar systemd, arranca el servidor a mano para confirmar
que todo funciona y ver cualquier error directo en la terminal:

```bash
venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Desde otra terminal (o otra sesión SSH al mismo servidor):

```bash
curl http://127.0.0.1:8000/api/health
```

Deberías ver algo como `{"status":"ok","groq_configured":true,...}`. Si
`groq_configured` sale en `false`, revisa que `GROQ_API_KEY` haya quedado
bien guardada en el paso 7. Cuando confirmes que responde, detén el
proceso con `Ctrl+C` -- lo vamos a dejar corriendo de otra forma (systemd)
en el paso 12.

## 11. Crear la cuenta root

Sin esto no hay forma de entrar al panel de administración la primera
vez -- no existe registro ni alta automática de cuentas:

```bash
venv/bin/python scripts/create_root.py --username admin --display-name "Tu Nombre"
```

Te va a pedir una contraseña por consola (no queda visible ni se guarda
en el historial de la terminal). Guárdala bien -- la vas a necesitar para
entrar a `/root`.

## 12. Crear el servicio systemd

Esto hace que el chatbot arranque solo si el servidor se reinicia, y se
vuelva a levantar solo si el proceso llega a fallar -- sin esto, tendrías
que dejar una terminal SSH abierta para siempre.

```bash
sudo nano /etc/systemd/system/chatbot-facultad.service
```

Contenido (el mismo patrón que ya corre en producción -- ajusta `User` y
las rutas si usaste otro usuario o ubicación):

```ini
[Unit]
Description=Asistente Institucional RAG
After=network.target

[Service]
Type=simple
User=administrator
WorkingDirectory=/opt/chatbot-facultad
ExecStart=/opt/chatbot-facultad/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Nota el `--host 127.0.0.1` (en vez de `0.0.0.0` como en el paso 10): a
partir de aquí, el backend **solo** escucha conexiones locales del propio
servidor -- nginx (paso 13) es quien va a exponerlo a internet. Nunca
expongas el puerto 8010 directamente.

Activar el servicio:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now chatbot-facultad
sudo systemctl status chatbot-facultad
```

Deberías ver `Active: active (running)`. Si no, revisa los logs con
`journalctl -u chatbot-facultad -e` para ver el error exacto.

## 13. Configurar nginx como proxy reverso

Nginx recibe las conexiones reales de internet (puerto 80/443) y las
reenvía al backend interno (`127.0.0.1:8010`):

```bash
sudo nano /etc/nginx/sites-available/tudominio.com
```

Contenido (reemplaza `tudominio.com` por tu dominio real):

```nginx
server {
    listen 80;
    client_max_body_size 30M;
    server_name tudominio.com;

    location / {
        proxy_pass http://127.0.0.1:8010;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Dos detalles que no son opcionales:

- `proxy_set_header Upgrade`/`Connection "upgrade"` -- sin esto, el panel
  de atención en tiempo real (WebSocket) no funciona.
- Los `timeout` en 300s -- las respuestas del chat se transmiten en
  streaming y pueden tardar varios segundos; con el timeout por defecto
  de nginx (60s) se cortarían a mitad de respuesta.
- `client_max_body_size 30M` -- debe ser igual o mayor que
  `MAX_FILE_SIZE_MB` de tu `.env` (25 MB por defecto), o la subida de
  documentos grandes desde el panel fallará.

Activar el sitio:

```bash
sudo ln -s /etc/nginx/sites-available/tudominio.com /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

`nginx -t` valida la sintaxis antes de aplicar el cambio -- si marca
error, no sigas al siguiente paso hasta corregirlo.

## 14. Activar HTTPS con certbot

Con tu dominio ya apuntando a la IP del servidor:

```bash
sudo certbot --nginx -d tudominio.com
```

Certbot modifica automáticamente el archivo de nginx del paso 13:
agrega el bloque HTTPS (puerto 443) con el certificado, y configura la
redirección automática de `http://` a `https://`. Confirma que la
renovación automática quedó activa (los certificados de Let's Encrypt
duran 90 días):

```bash
systemctl status certbot.timer
```

## 15. Configurar el firewall (ufw)

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

Verifica que **no** aparezca ninguna regla para el puerto 8010 (ni 8000)
-- ese puerto debe seguir siendo accesible solo desde el propio servidor
(`127.0.0.1`), nunca desde internet directamente.

## 16. Verificación final

Con todo ya configurado:

```bash
curl https://tudominio.com/api/health
```

Y desde un navegador:

- Chat de estudiantes: `https://tudominio.com`
- Panel de atención: `https://tudominio.com/panel`
- Panel de administración root: `https://tudominio.com/root` (entra con
  la cuenta del paso 11)

Haz una pregunta de prueba real en el chat (por ejemplo, sobre el
contenido de uno de los documentos de ejemplo) y confirma que responde
citando la fuente. Para ver qué está pasando del lado del servidor en
tiempo real:

```bash
journalctl -u chatbot-facultad -f
```

## 17. Limpiar documentos y datos de ejemplo antes de salir a producción

Una vez confirmado que todo el pipeline funciona (pasos 8 a 16), deja el
servidor listo para datos reales. **Esto conserva siempre la cuenta root
creada en el paso 11** -- no la vuelve a pedir ni la borra.

**1. Borrar los documentos de ejemplo:**

```bash
rm documents/*_EJEMPLO.*
venv/bin/python scripts/ingest.py
```

Al volver a correr `ingest.py`, reconstruye `vector_db/` sin los
documentos de ejemplo (que ya no están en `documents/`) -- el índice
queda vacío hasta que subas documentos reales desde el panel (paso 9).

**2. Borrar los registros de prueba** que haya dejado la pregunta de
prueba del paso 16 (conversaciones, métricas, caché de respuestas -- no
las cuentas de administrador):

```bash
sudo systemctl stop chatbot-facultad
sqlite3 /opt/chatbot-facultad/history.db "
DELETE FROM turns;
DELETE FROM session_meta;
DELETE FROM admin_messages;
DELETE FROM chat_metrics;
DELETE FROM groq_calls;
DELETE FROM answer_cache;
DELETE FROM answer_feedback;
DELETE FROM faq_candidates;
"
sudo systemctl start chatbot-facultad
```

Esto vacía **únicamente** las tablas de conversación y métricas de uso.
**No toca** la tabla `admins` (tu cuenta root sigue intacta), ni
`dependencias`, `institution_settings`, `hostility_keywords`,
`widget_allowed_origins`, `document_dependencias`, `document_hashes` ni
`admin_sessions` -- es decir, ninguna cuenta, configuración institucional
ni sesión de administrador activa se pierde. Ver
[diagrama-de-clases.md](diagrama-de-clases.md) para el detalle completo
de las 16 tablas de `history.db`.

## 18. Mantenimiento: cómo actualizar el código más adelante

Cuando haya cambios nuevos en el repositorio:

```bash
cd /opt/chatbot-facultad
git pull origin master
sudo systemctl restart chatbot-facultad   # solo si cambió código Python
```

Si el cambio fue solo de frontend (HTML/CSS/JS) o documentación, no hace
falta reiniciar el servicio -- el propio backend lee esos archivos del
disco en cada petición (no los mantiene cacheados en memoria), así que
`git pull` solo ya alcanza para que el cambio se vea en el navegador.

Los respaldos de `history.db` se generan solos, periódicamente, en la
carpeta configurada en `HISTORY_BACKUP_DIR` (por defecto `backups/`,
dentro de `/opt/chatbot-facultad`) -- no requieren ninguna acción manual.

Para agregar documentos nuevos, usa siempre el panel (paso 9) -- es la
vía normal, dispara la reindexación sola y no depende de SSH.
`scripts/ingest.py` queda disponible como alternativa avanzada por SSH
únicamente si algún día necesitas reconstruir el índice completo desde
cero.

## 19. Qué leer después

- [manual-usuario.md](manual-usuario.md) -- cómo usar el sistema ya
  instalado (estudiante, asesor, root).
- [estructura-del-proyecto.md](estructura-del-proyecto.md) -- para qué
  sirve cada carpeta y archivo del repositorio.
- [stack-tecnologico.md](stack-tecnologico.md) -- de qué está hecho el
  proyecto, para exponerlo o para que lo revise un equipo de TI.
