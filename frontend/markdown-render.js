// Renderizado seguro de markdown (usado por script.js y panel.js) -- las
// respuestas del bot vienen de tablas/listas en los documentos fuente, y se
// ven mucho más ordenadas como markdown real (tablas con bordes, negritas,
// listas) que como texto plano con pipes ("| Tema | Info |").
//
// marked.parse() nunca debe recibir el resultado directo a innerHTML sin
// pasar por DOMPurify: aunque hoy el texto viene del LLM (no directamente
// del estudiante), el LLM incluye el mensaje del estudiante en su prompt, así
// que en teoría podría reflejar HTML/markdown malicioso en la respuesta --
// DOMPurify.sanitize() es la última línea de defensa contra eso.
marked.setOptions({ gfm: true, breaks: true });

function renderMarkdownHtml(text) {
  const rawHtml = marked.parse(text || "");
  return DOMPurify.sanitize(rawHtml);
}
