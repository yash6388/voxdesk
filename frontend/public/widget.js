/*!
 * VoxDesk chat widget — adds a floating chat bubble to any website.
 *
 *   <script src="https://YOUR-VOXDESK/widget.js" data-business="your-business-slug" async></script>
 *
 * Options (data-* attributes): data-business (required), data-label, data-color.
 * The chat runs in an iframe served by VoxDesk, so it can't read or change the host page.
 */
(function () {
  "use strict";
  if (window.__voxdeskWidget) return; // never load twice
  window.__voxdeskWidget = true;

  var script =
    document.currentScript || document.querySelector('script[src*="widget.js"][data-business]');
  if (!script) return;
  var slug = script.getAttribute("data-business");
  if (!slug) return console.warn("[VoxDesk] widget.js needs a data-business attribute");

  var origin = new URL(script.src, location.href).origin;
  var label = script.getAttribute("data-label") || "Chat with us";
  var color = script.getAttribute("data-color") || "#4f46e5";
  var chatUrl = origin + "/c/" + encodeURIComponent(slug) + "?embed=1";

  var css =
    ".vxd-btn{position:fixed;right:20px;bottom:20px;z-index:2147483646;display:flex;align-items:center;gap:8px;" +
    "border:0;border-radius:999px;padding:12px 18px;color:#fff;font:600 14px/1 system-ui,sans-serif;cursor:pointer;" +
    "box-shadow:0 10px 30px rgba(0,0,0,.18);transition:transform .15s ease}" +
    ".vxd-btn:hover{transform:translateY(-2px)}.vxd-btn svg{width:20px;height:20px}" +
    ".vxd-panel{position:fixed;right:20px;bottom:84px;z-index:2147483647;width:380px;height:600px;max-height:calc(100vh - 110px);" +
    "border:0;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.25);background:#fff;opacity:0;transform:translateY(12px);" +
    "pointer-events:none;transition:opacity .18s ease,transform .18s ease}" +
    ".vxd-panel.vxd-open{opacity:1;transform:none;pointer-events:auto}" +
    "@media (max-width:480px){.vxd-panel{right:0;bottom:0;width:100vw;height:100vh;max-height:none;border-radius:0}}";
  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  var chatIcon =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
  var closeIcon =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';

  var button = document.createElement("button");
  button.className = "vxd-btn";
  button.style.background = color;
  button.setAttribute("aria-expanded", "false");
  button.innerHTML = chatIcon + "<span>" + label.replace(/</g, "&lt;") + "</span>";

  var frame = null; // created on first open so the host page loads no chat until needed
  var open = false;

  function setOpen(next) {
    open = next;
    if (open && !frame) {
      frame = document.createElement("iframe");
      frame.className = "vxd-panel";
      frame.src = chatUrl;
      frame.title = label;
      frame.allow = "microphone; clipboard-write";
      document.body.appendChild(frame);
      frame.getBoundingClientRect(); // allow the opening transition to run
    }
    if (frame) frame.classList.toggle("vxd-open", open);
    button.innerHTML = open
      ? closeIcon + "<span>Close</span>"
      : chatIcon + "<span>" + label.replace(/</g, "&lt;") + "</span>";
    button.setAttribute("aria-expanded", String(open));
  }

  button.addEventListener("click", function () {
    setOpen(!open);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && open) setOpen(false);
  });
  // The chat page's own close button asks us to close (only trusted from our origin).
  window.addEventListener("message", function (e) {
    if (e.origin === origin && e.data === "voxdesk:close") setOpen(false);
  });

  function mount() {
    document.body.appendChild(button);
  }
  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
})();
