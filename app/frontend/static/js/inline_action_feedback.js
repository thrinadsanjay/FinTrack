(() => {
  const DEFAULT_DELAY_MS = 2200;

  function ensureAnchor(button) {
    if (!(button instanceof HTMLElement)) return null;
    const existing = button.closest(".inline-action-anchor");
    if (existing) return existing;

    const anchor = document.createElement("span");
    anchor.className = "inline-action-anchor";
    button.parentNode?.insertBefore(anchor, button);
    anchor.appendChild(button);
    return anchor;
  }

  function ensureStatusEl(button) {
    const anchor = ensureAnchor(button);
    if (!anchor) return null;
    let status = anchor.querySelector(".inline-action-status");
    if (!status) {
      status = document.createElement("span");
      status.className = "inline-action-status";
      status.hidden = true;
      status.setAttribute("aria-live", "polite");
      anchor.appendChild(status);
    }
    return status;
  }

  function clearTimer(button) {
    if (!(button instanceof HTMLElement)) return;
    if (button._inlineFeedbackTimer) {
      window.clearTimeout(button._inlineFeedbackTimer);
      button._inlineFeedbackTimer = null;
    }
  }

  function showFor(button, message, kind = "success", duration = DEFAULT_DELAY_MS) {
    const status = ensureStatusEl(button);
    if (!status) return Promise.resolve();

    clearTimer(button);
    status.textContent = String(message || "").trim();
    status.className = `inline-action-status is-${kind}`;
    status.hidden = false;

    return new Promise((resolve) => {
      button._inlineFeedbackTimer = window.setTimeout(() => {
        status.hidden = true;
        status.textContent = "";
        button._inlineFeedbackTimer = null;
        resolve();
      }, Math.max(400, Number(duration) || DEFAULT_DELAY_MS));
    });
  }

  function replaceDocument(html) {
    document.open();
    document.write(html);
    document.close();
  }

  async function submitWithInlineFeedback(form, submitter, options = {}) {
    if (!(form instanceof HTMLFormElement) || !(submitter instanceof HTMLElement)) {
      return false;
    }
    if (form.dataset.inlineSubmitting === "true") return true;

    const message = options.message || submitter.dataset.inlineSuccessMessage || form.dataset.inlineSuccessMessage || "Settings saved";
    const delayMs = Number(options.delayMs || submitter.dataset.inlineSuccessDelay || form.dataset.inlineSuccessDelay || DEFAULT_DELAY_MS);
    const url = submitter.getAttribute("formaction") || form.getAttribute("action") || window.location.href;
    const method = String(submitter.getAttribute("formmethod") || form.getAttribute("method") || "GET").toUpperCase();
    const formData = new FormData(form);
    const submitterName = submitter.getAttribute("name");
    if (submitterName) {
      formData.set(submitterName, submitter.getAttribute("value") || "");
    }

    form.dataset.inlineSubmitting = "true";
    if (submitter instanceof HTMLButtonElement || submitter instanceof HTMLInputElement) {
      submitter.disabled = true;
    }

    try {
      const response = await fetch(url, {
        method,
        body: method == "GET" ? null : formData,
        credentials: "same-origin",
      });

      const contentType = String(response.headers.get("content-type") || "").toLowerCase();

      if (response.redirected) {
        await showFor(submitter, message, "success", delayMs);
        const redirectHash = submitter.dataset.inlineRedirectHash || form.dataset.inlineRedirectHash || "";
        const targetUrl = redirectHash && !response.url.includes("#")
          ? `${response.url}${redirectHash}`
          : response.url;
        window.location.assign(targetUrl);
        return true;
      }

      if (!response.ok) {
        if (contentType.includes("application/json")) {
          const payload = await response.json().catch(() => ({}));
          const detail = payload?.detail || payload?.message || "Request failed.";
          if (typeof window.ftNotify === "function") window.ftNotify(detail, "error");
          else window.alert(detail);
          return true;
        }
        const html = await response.text();
        replaceDocument(html);
        return true;
      }

      if (contentType.includes("text/html")) {
        const html = await response.text();
        replaceDocument(html);
        return true;
      }

      await showFor(submitter, message, "success", delayMs);
      if (options.onSuccessReload) {
        window.location.reload();
      }
      return true;
    } catch (error) {
      const fallback = error instanceof Error ? error.message : "Request failed.";
      if (typeof window.ftNotify === "function") window.ftNotify(fallback, "error");
      else window.alert(fallback);
      return true;
    } finally {
      form.dataset.inlineSubmitting = "false";
      if (submitter instanceof HTMLButtonElement || submitter instanceof HTMLInputElement) {
        submitter.disabled = false;
      }
    }
  }

  function bindForms(selector = "form[data-inline-success-form]") {
    document.querySelectorAll(selector).forEach((form) => {
      if (!(form instanceof HTMLFormElement) || form.dataset.inlineFeedbackBound === "true") return;
      form.dataset.inlineFeedbackBound = "true";
      form.addEventListener("submit", (event) => {
        const submitter = event.submitter;
        if (!(submitter instanceof HTMLElement)) return;
        if (submitter.dataset.inlineFeedback === "off") return;
        event.preventDefault();
        submitWithInlineFeedback(form, submitter);
      });
    });
  }

  window.ftInlineFeedback = {
    bindForms,
    showFor,
    submitWithInlineFeedback,
  };

  document.addEventListener("DOMContentLoaded", () => {
    bindForms();
  });
})();
