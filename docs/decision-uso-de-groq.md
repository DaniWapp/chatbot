# Por qué se eligió Groq como proveedor del LLM

Este documento explica la decisión detrás de usar **Groq** (GroqCloud) como
proveedor del modelo de lenguaje del chatbot, en vez de otras alternativas.
El razonamiento resumido también vive en el [README.md](../README.md),
sección 5 ("Tecnologías utilizadas"); este archivo lo desarrolla con más
detalle para que quede como referencia independiente (por ejemplo, para
sustentar la decisión en una presentación o informe).

## 1. Aclaración importante: Groq ≠ Grok

Antes de cualquier otra cosa, una confusión muy común: **Groq** (la empresa
detrás de este proyecto) **no tiene relación con "Grok"**, el chatbot de
xAI (la empresa de Elon Musk). Son dos compañías completamente distintas:

- **Groq** es una empresa de **hardware**, fundada por ex-ingenieros de
  Google (equipo original de la TPU), enfocada en fabricar chips
  especializados para inferencia de modelos de lenguaje.
- **Grok** es el asistente conversacional de **xAI**, que compite
  directamente con ChatGPT, Claude, Gemini, etc.

El nombre parecido es coincidencia (o al menos, no hay relación
corporativa entre ambos) y ha generado confusión en la comunidad; vale la
pena dejarlo explícito porque es la primera pregunta que suele surgir.

## 2. Qué es realmente Groq y por qué puede ofrecer un nivel gratuito

Groq diseñó un chip propio llamado **LPU** (*Language Processing Unit*),
especializado en generar tokens de modelos de lenguaje mucho más rápido que
las GPUs tradicionales (Nvidia, etc.), que fueron diseñadas originalmente
para gráficos y entrenamiento, no para inferencia conversacional en tiempo
real. Sobre ese hardware corren su servicio en la nube, **GroqCloud**, con
una API compatible con el estilo de OpenAI.

El nivel gratuito de GroqCloud no es una promoción temporal ni caridad,
sino una estrategia de adopción típica de empresas de hardware/infraestructura:

- Es una vitrina de la velocidad de su chip: atender consultas de bajo
  volumen en hardware que ya está construido tiene un costo marginal bajo
  para Groq, a cambio de que desarrolladores prueben la plataforma, la
  recomienden, y eventualmente algunos se conviertan en clientes de pago.
- El negocio real de Groq está en clientes de **alto volumen**, que pagan
  por planes superiores o contratan su infraestructura directamente.
- El nivel gratuito **no es ilimitado**: tiene límites de velocidad
  (peticiones por minuto, tokens por minuto/día). Estas condiciones pueden
  cambiar con el tiempo — antes de asumir que se mantendrán, conviene
  verificar los límites vigentes en
  [console.groq.com/docs/rate-limits](https://console.groq.com/docs/rate-limits).

## 3. Por qué Groq y no otras alternativas

| Alternativa | Por qué no se usó (en el contexto de este proyecto) |
|---|---|
| **OpenAI API (GPT-4, GPT-4o-mini, etc.)** | Requiere tarjeta de crédito y pago por uso desde el primer token; no tiene un nivel gratuito utilizable para un proyecto académico de prueba. |
| **Modelo local (Ollama, llama.cpp, etc.)** | Requeriría hardware con GPU decente (o CPU muy rápida) para respuestas en tiempo razonable, y complica la instalación para cualquiera que quiera correr el proyecto en un equipo modesto — contradice el objetivo de que sea fácil de instalar y probar. |
| **Otras nubes con nivel gratuito (Gemini, Cohere, etc.)** | Groq se eligió puntualmente por la combinación de velocidad (~1000 tokens/segundo, respuestas que aparecen casi instantáneas en el streaming) y un nivel gratuito generoso para tráfico bajo, ideal para una demo académica donde varias personas pueden probar el chat en vivo sin sentir demoras. |

La velocidad en particular importa para la experiencia del chatbot: al
usar streaming (Server-Sent Events, ver `POST /api/chat/stream`), la
respuesta aparece palabra por palabra casi de inmediato — algo que se nota
mucho más con un proveedor rápido como Groq que con proveedores más lentos.

## 4. Qué modelo específico se usa, y por qué

El proyecto usa `openai/gpt-oss-20b` (configurable vía `GROQ_MODEL` en
`.env`). Es un modelo **open-weight** de OpenAI (a pesar del nombre del
proveedor "Groq", el modelo en sí lo publicó OpenAI) que Groq sirve sobre
su propio hardware. Se eligió porque, al momento de construir el proyecto:

- Es un modelo activo de producción (no experimental/beta).
- Tiene una ventana de contexto amplia (131K tokens).
- Está disponible en el nivel gratuito de GroqCloud.
- Es muy rápido (~1000 tokens/segundo) gracias al hardware LPU.

**Nota importante:** el catálogo de modelos de Groq cambia con el tiempo
(los modelos Llama que antes eran el estándar recomendado ya fueron
retirados de su catálogo). Antes de fijar este modelo se consultó la lista
real de modelos disponibles vía la API (`client.models.list()`), no solo la
documentación web — y se recomienda hacer lo mismo si en el futuro hay que
volver a elegir un modelo, en vez de confiar en que el nombre seguirá
disponible indefinidamente. Ver los modelos vigentes en
[console.groq.com/docs/models](https://console.groq.com/docs/models).

## 5. Riesgos y limitaciones a tener en cuenta

- **Dependencia de un tercero**: si Groq tiene una caída de servicio o
  retira el modelo usado, el chatbot deja de poder generar respuestas
  (los embeddings y la búsqueda semántica sí son 100% locales y no se ven
  afectados).
- **Límites de tasa**: un uso académico de bajo tráfico cabe cómodamente
  en el nivel gratuito, pero un uso en producción con muchos usuarios
  simultáneos probablemente superaría esos límites y necesitaría pasar a
  un plan pago de Groq.
- **Cambios de catálogo**: como ya pasó una vez con los modelos Llama, Groq
  puede retirar o reemplazar `openai/gpt-oss-20b` en el futuro; el código
  ya está preparado para cambiar de modelo solo editando `GROQ_MODEL` en
  `.env`, sin tocar el resto del pipeline.
