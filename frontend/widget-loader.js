(function () {
  "use strict";

  // El origen del backend es el mismo desde donde se sirvió este script --
  // así el snippet funciona en cualquier sitio anfitrión sin hardcodear el
  // dominio (ver docs/widget-embebible.md).
  var currentScript = document.currentScript;
  var widgetOrigin = new URL(currentScript.src).origin;

  var PANEL_WIDTH = 380;
  var PANEL_HEIGHT = 600;

  var style = document.createElement("style");
  style.textContent = [
    ".cbw-bubble {",
    "  position: fixed; bottom: 20px; right: 20px; z-index: 2147483000;",
    "  width: 60px; height: 60px; border-radius: 50%; border: none;",
    "  background: #5b21b6; color: #fff; cursor: pointer;",
    "  box-shadow: 0 6px 18px rgba(0,0,0,0.25);",
    "  display: flex; align-items: center; justify-content: center;",
    "}",
    ".cbw-bubble svg { width: 28px; height: 28px; }",
    ".cbw-panel {",
    "  position: fixed; bottom: 92px; right: 20px; z-index: 2147483000;",
    "  width: " + PANEL_WIDTH + "px; height: " + PANEL_HEIGHT + "px;",
    "  max-height: calc(100vh - 112px);",
    "  border-radius: 16px; overflow: hidden; box-shadow: 0 12px 32px rgba(0,0,0,0.3);",
    "  display: none;",
    "}",
    ".cbw-panel.cbw-open { display: block; }",
    ".cbw-panel iframe { width: 100%; height: 100%; border: none; }",
    "@media (max-width: 480px) {",
    "  .cbw-panel {",
    "    top: 0; left: 0; right: 0; bottom: 0; width: 100%; height: 100%;",
    "    max-height: none; border-radius: 0;",
    "  }",
    "}",
  ].join("\n");
  document.head.appendChild(style);

  var bubble = document.createElement("button");
  bubble.type = "button";
  bubble.className = "cbw-bubble";
  bubble.setAttribute("aria-label", "Abrir el asistente virtual");
  bubble.innerHTML =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path>' +
    "</svg>";

  var panel = document.createElement("div");
  panel.className = "cbw-panel";

  var iframeCreated = false;

  bubble.addEventListener("click", function () {
    if (!iframeCreated) {
      var iframe = document.createElement("iframe");
      iframe.src = widgetOrigin + "/widget";
      iframe.title = "Asistente virtual";
      panel.appendChild(iframe);
      iframeCreated = true;
    }
    panel.classList.toggle("cbw-open");
  });

  document.body.appendChild(panel);
  document.body.appendChild(bubble);
})();
