(() => {
  const testBtn = document.querySelector("[data-smtp-test]");
  const telegramBroadcastBtn = document.querySelector("[data-telegram-broadcast]");
  const telegramBroadcastInput = document.querySelector("[data-telegram-broadcast-message]");
  const telegramWebhookSetBtn = document.querySelector("[data-telegram-webhook-set]");
  const telegramWebhookInfoBtn = document.querySelector("[data-telegram-webhook-info]");
  const telegramWebhookDeleteBtn = document.querySelector("[data-telegram-webhook-delete]");
  const telegramPollRunOnceBtn = document.querySelector("[data-telegram-poll-run-once]");
  const telegramPollStatusBtn = document.querySelector("[data-telegram-poll-status]");
  const telegramPollWidget = document.querySelector("[data-telegram-poll-widget]");
  const telegramPollHealthStatus = document.querySelector("[data-telegram-poll-health-status]");
  const telegramPollHealthTime = document.querySelector("[data-telegram-poll-health-time]");
  const telegramPollHealthUpdate = document.querySelector("[data-telegram-poll-health-update]");
  const telegramPollHealthProcessed = document.querySelector("[data-telegram-poll-health-processed]");
  const telegramPollHealthConfig = document.querySelector("[data-telegram-poll-health-config]");
  const telegramPollHealthWebhook = document.querySelector("[data-telegram-poll-health-webhook]");
  const telegramPollHealthError = document.querySelector("[data-telegram-poll-health-error]");
  if (
    !testBtn &&
    !telegramBroadcastBtn &&
    !telegramWebhookSetBtn &&
    !telegramWebhookInfoBtn &&
    !telegramWebhookDeleteBtn &&
    !telegramPollRunOnceBtn &&
    !telegramPollStatusBtn
  ) return;

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";

  function val(name) {
    const el = document.querySelector(`[name="${name}"]`);
    return (el?.value || "").trim();
  }

  function checked(name) {
    const el = document.querySelector(`[name="${name}"]`);
    return Boolean(el?.checked);
  }

  function isValidEmail(email) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(email || "").trim());
  }

  function notify(message, kind) {
    if (typeof window.ftNotify === "function") {
      window.ftNotify(message, kind || "info");
      return;
    }
    window.alert(message);
  }

  function fmtDate(value) {
    if (!value) return "-";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleString();
  }

  function renderPollHealth(poll, requestError = "") {
    if (!telegramPollWidget) return;
    const lastError = requestError || poll?.last_error || "";
    const status = requestError ? "Error" : (lastError ? "Degraded" : "Healthy");
    if (telegramPollHealthStatus) telegramPollHealthStatus.textContent = status;
    if (telegramPollHealthTime) telegramPollHealthTime.textContent = fmtDate(poll?.last_poll_at);
    if (telegramPollHealthUpdate) telegramPollHealthUpdate.textContent = String(poll?.last_update_id ?? "-");
    if (telegramPollHealthProcessed) {
      telegramPollHealthProcessed.textContent = `${poll?.processed_updates ?? 0} updates / ${poll?.processed_messages ?? 0} messages`;
    }
    if (telegramPollHealthConfig) {
      const enabled = poll?.config_enabled ? "enabled" : "disabled";
      const polling = poll?.config_polling_enabled ? "polling:on" : "polling:off";
      const token = poll?.config_has_token ? "token:ok" : "token:missing";
      telegramPollHealthConfig.textContent = `${enabled}, ${polling}, ${token}`;
    }
    if (telegramPollHealthWebhook) {
      const url = String(poll?.webhook_url || "").trim();
      telegramPollHealthWebhook.textContent = url || "none";
    }
    if (telegramPollHealthError) {
      if (lastError) {
        telegramPollHealthError.hidden = false;
        telegramPollHealthError.textContent = lastError;
      } else {
        telegramPollHealthError.hidden = true;
        telegramPollHealthError.textContent = "";
      }
    }
  }

  async function callTelegramAdmin(path, extra = {}) {
    const payload = {
      ...extra,
      telegram: {
        enabled: checked("telegram_enabled"),
        bot_token: val("telegram_bot_token"),
        webhook_url: val("telegram_webhook_url"),
      },
    };
    const res = await fetch(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || "Request failed.");
    }
    return data;
  }

  async function runTest() {
    const toEmail = window.prompt("Enter receiver email id for SMTP test:");
    if (toEmail == null) return;
    const receiver = toEmail.trim();
    if (!receiver) {
      if (typeof window.ftNotify === "function") window.ftNotify("Receiver email is required.", "error");
      else window.alert("Receiver email is required.");
      return;
    }
    if (!isValidEmail(receiver)) {
      if (typeof window.ftNotify === "function") window.ftNotify("Please enter a valid receiver email.", "error");
      else window.alert("Please enter a valid receiver email.");
      return;
    }

    const payload = {
      to_email: receiver,
      smtp: {
        enabled: checked("smtp_enabled"),
        host: val("smtp_host"),
        port: val("smtp_port"),
        username: val("smtp_username"),
        password: val("smtp_password"),
        from_email: val("smtp_from_email"),
        tls: checked("smtp_tls"),
      },
    };

    testBtn.disabled = true;
    testBtn.classList.add("is-loading");
    const label = testBtn.textContent;
    testBtn.textContent = "Sending...";
    try {
      const res = await fetch("/admin/settings/smtp/test", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || "Failed to send SMTP test email.");
      }
      notify("Test email sent successfully.", "success");
    } catch (err) {
      notify(err?.message || "SMTP test failed.", "error");
    } finally {
      testBtn.classList.remove("is-loading");
      testBtn.disabled = false;
      testBtn.textContent = label || "Test SMTP";
    }
  }

  if (testBtn) {
    testBtn.addEventListener("click", runTest);
  }

  async function runTelegramBroadcast() {
    const text = (telegramBroadcastInput?.value || "").trim();
    if (!text) {
      notify("Enter a broadcast message first.", "error");
      telegramBroadcastInput?.focus();
      return;
    }

    const payload = {
      message: text,
      telegram: {
        enabled: checked("telegram_enabled"),
        bot_token: val("telegram_bot_token"),
      },
    };

    telegramBroadcastBtn.disabled = true;
    telegramBroadcastBtn.classList.add("is-loading");
    const label = telegramBroadcastBtn.textContent;
    telegramBroadcastBtn.textContent = "Sending...";
    try {
      const res = await fetch("/admin/settings/telegram/broadcast", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || "Failed to send Telegram broadcast.");
      }
      const summary = `Broadcast sent: ${data.sent || 0}/${data.total || 0} users${
        data.failed ? ` (${data.failed} failed)` : ""
      }.`;
      notify(summary, "success");
      if (telegramBroadcastInput) {
        telegramBroadcastInput.value = "";
      }
    } catch (err) {
      notify(err?.message || "Telegram broadcast failed.", "error");
    } finally {
      telegramBroadcastBtn.classList.remove("is-loading");
      telegramBroadcastBtn.disabled = false;
      telegramBroadcastBtn.textContent = label || "Broadcast Message";
    }
  }

  if (telegramBroadcastBtn) {
    telegramBroadcastBtn.addEventListener("click", runTelegramBroadcast);
  }

  async function runSetWebhook() {
    if (!telegramWebhookSetBtn) return;
    telegramWebhookSetBtn.disabled = true;
    telegramWebhookSetBtn.classList.add("is-loading");
    const label = telegramWebhookSetBtn.textContent;
    telegramWebhookSetBtn.textContent = "Setting...";
    try {
      await callTelegramAdmin("/admin/settings/telegram/webhook/set");
      notify("Webhook configured successfully.", "success");
    } catch (err) {
      notify(err?.message || "Failed to set webhook.", "error");
    } finally {
      telegramWebhookSetBtn.classList.remove("is-loading");
      telegramWebhookSetBtn.disabled = false;
      telegramWebhookSetBtn.textContent = label || "Set Webhook";
    }
  }

  async function runWebhookInfo() {
    if (!telegramWebhookInfoBtn) return;
    telegramWebhookInfoBtn.disabled = true;
    telegramWebhookInfoBtn.classList.add("is-loading");
    const label = telegramWebhookInfoBtn.textContent;
    telegramWebhookInfoBtn.textContent = "Checking...";
    try {
      const data = await callTelegramAdmin("/admin/settings/telegram/webhook/info");
      const info = data.webhook || {};
      const msg = `URL: ${info.url || "-"} | Pending: ${info.pending_update_count ?? 0}${
        info.last_error_message ? ` | Last error: ${info.last_error_message}` : ""
      }`;
      notify(msg, "info");
    } catch (err) {
      notify(err?.message || "Failed to check webhook.", "error");
    } finally {
      telegramWebhookInfoBtn.classList.remove("is-loading");
      telegramWebhookInfoBtn.disabled = false;
      telegramWebhookInfoBtn.textContent = label || "Check Webhook";
    }
  }

  async function runDeleteWebhook() {
    if (!telegramWebhookDeleteBtn) return;
    const confirmed = window.confirm("Delete Telegram webhook now?");
    if (!confirmed) return;
    telegramWebhookDeleteBtn.disabled = true;
    telegramWebhookDeleteBtn.classList.add("is-loading");
    const label = telegramWebhookDeleteBtn.textContent;
    telegramWebhookDeleteBtn.textContent = "Deleting...";
    try {
      await callTelegramAdmin("/admin/settings/telegram/webhook/delete", { drop_pending_updates: false });
      notify("Webhook deleted successfully.", "success");
    } catch (err) {
      notify(err?.message || "Failed to delete webhook.", "error");
    } finally {
      telegramWebhookDeleteBtn.classList.remove("is-loading");
      telegramWebhookDeleteBtn.disabled = false;
      telegramWebhookDeleteBtn.textContent = label || "Delete Webhook";
    }
  }

  telegramWebhookSetBtn?.addEventListener("click", runSetWebhook);
  telegramWebhookInfoBtn?.addEventListener("click", runWebhookInfo);
  telegramWebhookDeleteBtn?.addEventListener("click", runDeleteWebhook);

  async function runPollStatus() {
    if (!telegramPollStatusBtn) return;
    telegramPollStatusBtn.disabled = true;
    telegramPollStatusBtn.classList.add("is-loading");
    const label = telegramPollStatusBtn.textContent;
    telegramPollStatusBtn.textContent = "Checking...";
    try {
      const data = await callTelegramAdmin("/admin/settings/telegram/poll/status");
      const poll = data.poll || {};
      renderPollHealth(poll);
      const msg = `last_update_id=${poll.last_update_id ?? "-"}, processed_updates=${poll.processed_updates ?? 0}, processed_messages=${poll.processed_messages ?? 0}, last_error=${poll.last_error || "none"}`;
      notify(msg, poll.last_error ? "error" : "info");
    } catch (err) {
      notify(err?.message || "Failed to fetch poll status.", "error");
    } finally {
      telegramPollStatusBtn.classList.remove("is-loading");
      telegramPollStatusBtn.disabled = false;
      telegramPollStatusBtn.textContent = label || "Check Poll Status";
    }
  }

  async function runPollOnce() {
    if (!telegramPollRunOnceBtn) return;
    telegramPollRunOnceBtn.disabled = true;
    telegramPollRunOnceBtn.classList.add("is-loading");
    const label = telegramPollRunOnceBtn.textContent;
    telegramPollRunOnceBtn.textContent = "Running...";
    try {
      const data = await callTelegramAdmin("/admin/settings/telegram/poll/run-once");
      const poll = data.poll || {};
      renderPollHealth(poll);
      const msg = `Poll complete: updates=${poll.processed_updates ?? 0}, messages=${poll.processed_messages ?? 0}${poll.last_error ? `, error=${poll.last_error}` : ""}`;
      notify(msg, poll.last_error ? "error" : "success");
    } catch (err) {
      notify(err?.message || "Failed to run poll once.", "error");
    } finally {
      telegramPollRunOnceBtn.classList.remove("is-loading");
      telegramPollRunOnceBtn.disabled = false;
      telegramPollRunOnceBtn.textContent = label || "Run Poll Now";
    }
  }

  telegramPollStatusBtn?.addEventListener("click", runPollStatus);
  telegramPollRunOnceBtn?.addEventListener("click", runPollOnce);

  let livePollTimer = null;
  async function refreshPollHealthSilently() {
    if (!telegramPollWidget) return;
    try {
      const data = await callTelegramAdmin("/admin/settings/telegram/poll/status");
      renderPollHealth(data.poll || {});
    } catch (err) {
      renderPollHealth({}, err?.message || "Failed to refresh poll health.");
    }
  }

  if (telegramPollWidget) {
    refreshPollHealthSilently();
    livePollTimer = window.setInterval(refreshPollHealthSilently, 10000);
    window.addEventListener("beforeunload", () => {
      if (livePollTimer) {
        window.clearInterval(livePollTimer);
        livePollTimer = null;
      }
    });
  }
})();
