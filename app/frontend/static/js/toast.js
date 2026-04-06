/**
 * FinTracker Enhanced Toast Notification System (v2)
 * Provides stacked, dismissible toast notifications with progress bars.
 * Exposes window.ftToast for global use.
 * The legacy window.ftNotify remains available from app_shell.js.
 */
(function installToastV2() {
  "use strict";

  const DURATION = 4500; // ms before auto-dismiss
  const MAX_VISIBLE = 5;

  function getStack() {
    return document.getElementById("toastStack");
  }

  /**
   * Show a toast notification.
   * @param {string} message  - Main message text
   * @param {string} [type]   - 'success' | 'error' | 'warning' | 'info'
   * @param {string} [title]  - Optional bold title above the message
   * @param {number} [duration] - Override auto-dismiss duration (ms). 0 = never.
   */
  function showToast(message, type, title, duration) {
    const stack = getStack();
    if (!stack) {
      // Fallback to legacy system
      if (window.ftNotify) window.ftNotify(message, type === "error" ? "error" : type === "success" ? "success" : "info");
      return;
    }

    // Enforce max visible
    const existing = stack.querySelectorAll(".toast-v2");
    if (existing.length >= MAX_VISIBLE) {
      existing[0].remove();
    }

    const kind = ["success", "error", "warning", "info"].includes(type) ? type : "info";
    const icons = { success: "fa-check", error: "fa-xmark", warning: "fa-triangle-exclamation", info: "fa-circle-info" };

    const item = document.createElement("div");
    item.className = `toast-v2 toast-v2--${kind}`;
    item.setAttribute("role", "alert");
    item.setAttribute("aria-live", "polite");

    const autoDuration = (duration !== undefined && duration !== null) ? duration : DURATION;

    item.innerHTML = `
      <div class="toast-v2__dot"></div>
      <div class="toast-v2__body">
        ${title ? `<div class="toast-v2__title">${escapeHtml(title)}</div>` : ""}
        <div class="toast-v2__message">${escapeHtml(String(message || ""))}</div>
        ${autoDuration > 0 ? `<div class="toast-v2__progress" style="animation-duration:${autoDuration}ms"></div>` : ""}
      </div>
      <button type="button" class="toast-v2__close" aria-label="Dismiss">
        <i class="fa-solid fa-xmark" aria-hidden="true"></i>
      </button>
    `;

    // Dismiss on close button
    const closeBtn = item.querySelector(".toast-v2__close");
    if (closeBtn) {
      closeBtn.addEventListener("click", () => dismiss(item));
    }

    stack.appendChild(item);

    // Trigger enter animation
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        item.classList.add("show");
      });
    });

    // Auto-dismiss
    if (autoDuration > 0) {
      setTimeout(() => dismiss(item), autoDuration);
    }

    return item;
  }

  function dismiss(item) {
    if (!item || !item.parentNode) return;
    item.classList.remove("show");
    item.classList.add("hide");
    setTimeout(() => {
      if (item.parentNode) item.remove();
    }, 320);
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // Convenience methods
  const ftToast = {
    show: showToast,
    success: (msg, title, duration) => showToast(msg, "success", title, duration),
    error:   (msg, title, duration) => showToast(msg, "error",   title, duration),
    warning: (msg, title, duration) => showToast(msg, "warning", title, duration),
    info:    (msg, title, duration) => showToast(msg, "info",    title, duration),
  };

  window.ftToast = ftToast;

  // Also upgrade ftNotify to use the v2 system when toast-stack is available
  const _legacyNotify = window.ftNotify;
  window.ftNotify = function (message, kind) {
    const type = kind === "success" ? "success" : kind === "info" ? "info" : "error";
    showToast(message, type);
  };
  // Keep original as fallback
  window._ftNotifyLegacy = _legacyNotify;
})();
