(() => {
  const testBtn = document.querySelector("[data-smtp-test]");
  const pushTestBtn = document.querySelector("[data-push-test]");
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
  const telegramDeliveryWidget = document.querySelector("[data-telegram-delivery-widget]");
  const telegramDeliveryTotal = document.querySelector("[data-telegram-delivery-total]");
  const telegramDeliverySent = document.querySelector("[data-telegram-delivery-sent]");
  const telegramDeliveryFailed = document.querySelector("[data-telegram-delivery-failed]");
  const telegramDeliveryCooldown = document.querySelector("[data-telegram-delivery-cooldown]");
  const telegramDeliveryChecked = document.querySelector("[data-telegram-delivery-checked]");
  const telegramDeliveryFailures = document.querySelector("[data-telegram-delivery-failures]");
  const pushProviderInput = document.querySelector("[data-push-provider]");
  const pushFirebasePanel = document.querySelector('[data-push-method="firebase"]');
  const pushWebpushPanel = document.querySelector('[data-push-method="webpush"]');
  if (
    !testBtn &&
    !telegramBroadcastBtn &&
    !telegramWebhookSetBtn &&
    !telegramWebhookInfoBtn &&
    !telegramWebhookDeleteBtn &&
    !telegramPollRunOnceBtn &&
    !telegramPollStatusBtn &&
    !telegramDeliveryWidget &&
    !pushTestBtn
  ) return;

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
  const settingsForm = document.querySelector(".settings-form");
  const settingsPanels = Array.from(document.querySelectorAll("[data-settings-panel]"));
  const settingsEditingBanner = document.querySelector("[data-settings-editing-banner]");
  const settingsEditingLabel = document.querySelector("[data-settings-editing-label]");
  let activePanelKey = null;
  const panelSnapshot = new Map();

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

  function startLoading(btn, loadingLabel = "Loading") {
    if (!btn) return;
    const defaultHtml = btn.dataset.defaultHtml || btn.innerHTML;
    btn.dataset.defaultHtml = defaultHtml;
    btn.disabled = true;
    btn.classList.add("is-loading");
    btn.dataset.loadingLabel = loadingLabel;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
  }

  function stopLoading(btn, fallbackHtml = "") {
    if (!btn) return;
    btn.classList.remove("is-loading");
    btn.disabled = false;
    btn.innerHTML = btn.dataset.defaultHtml || fallbackHtml;
  }


  function applyPushProviderVisibility() {
    if (!pushProviderInput) return;
    const raw = String(pushProviderInput.value || "").trim().toLowerCase();
    const provider = raw === "firebase" ? "firebase" : "webpush";
    if (pushProviderInput.value !== provider) {
      pushProviderInput.value = provider;
    }

    const isFirebase = provider === "firebase";
    if (pushFirebasePanel) {
      pushFirebasePanel.hidden = !isFirebase;
      if (!isFirebase) {
        pushFirebasePanel.querySelectorAll("details").forEach((d) => {
          if (d instanceof HTMLDetailsElement) d.open = false;
        });
      }
    }
    if (pushWebpushPanel) {
      pushWebpushPanel.hidden = isFirebase;
    }
  }

  function getPanelKey(panel) {
    return String(panel?.getAttribute("data-settings-panel") || "").trim();
  }
  function getPanelTitle(panel) {
    const heading = panel?.querySelector(".settings-group-head h3");
    return String(heading?.textContent || getPanelKey(panel) || "Settings").trim();
  }

  function getPanelBannerKind(key) {
    if (key === "application") return "app";
    if (["smtp", "telegram", "push_notifications"].includes(key)) return "communication";
    if (key === "authentication") return "security";
    if (["database", "backup"].includes(key)) return "infrastructure";
    return "default";
  }

  function updateEditingBanner() {
    if (!settingsEditingBanner || !settingsEditingLabel) return;
    settingsEditingBanner.classList.remove(
      "is-app",
      "is-communication",
      "is-security",
      "is-infrastructure",
      "is-default"
    );
    if (!activePanelKey) {
      settingsEditingBanner.hidden = true;
      settingsEditingLabel.textContent = "-";
      return;
    }
    const activePanel = settingsPanels.find((p) => getPanelKey(p) === activePanelKey);
    settingsEditingLabel.textContent = getPanelTitle(activePanel);
    settingsEditingBanner.classList.add(`is-${getPanelBannerKind(activePanelKey)}`);
    settingsEditingBanner.hidden = false;
  }


  function getPanelControls(panel) {
    return Array.from(panel.querySelectorAll("input, select, textarea")).filter((el) => {
      if (!(el instanceof HTMLElement)) return false;
      if (el.closest(".settings-actions")) return false;
      if (el.getAttribute("name") === "csrf_token") return false;
      if (el.getAttribute("type") === "hidden") return false;
      if (el.getAttribute("data-panel-action-control") === "true") return false;
      return true;
    });
  }

  function setPanelControlsEditable(panel, editable) {
    getPanelControls(panel).forEach((el) => {
      if (el instanceof HTMLInputElement || el instanceof HTMLSelectElement || el instanceof HTMLTextAreaElement) {
        el.disabled = !editable;
      }
    });
  }

  function snapshotPanel(panel) {
    const state = getPanelControls(panel).map((el) => {
      const isCheck = el instanceof HTMLInputElement && ["checkbox", "radio"].includes((el.type || "").toLowerCase());
      return {
        name: el.getAttribute("name") || "",
        type: (el instanceof HTMLInputElement) ? el.type : (el instanceof HTMLSelectElement ? "select" : "textarea"),
        value: isCheck ? String(el.checked) : String(el.value ?? ""),
      };
    });
    panelSnapshot.set(getPanelKey(panel), state);
  }

  function restorePanel(panel) {
    const key = getPanelKey(panel);
    const state = panelSnapshot.get(key) || [];
    state.forEach((item) => {
      const el = panel.querySelector(`[name="${item.name}"]`);
      if (!(el instanceof HTMLElement)) return;
      if (el instanceof HTMLInputElement && ["checkbox", "radio"].includes((el.type || "").toLowerCase())) {
        el.checked = item.value === "true";
      } else if (el instanceof HTMLInputElement || el instanceof HTMLSelectElement || el instanceof HTMLTextAreaElement) {
        el.value = item.value;
      }
    });
  }

  function setPanelButtons(panel, editing) {
    const editBtn = panel.querySelector("[data-panel-edit]");
    const saveBtn = panel.querySelector("[data-panel-save]");
    const cancelBtn = panel.querySelector("[data-panel-cancel]");
    if (editBtn instanceof HTMLElement) editBtn.hidden = editing;
    if (saveBtn instanceof HTMLElement) saveBtn.hidden = !editing;
    if (cancelBtn instanceof HTMLElement) cancelBtn.hidden = !editing;
  }

  function setPanelMode(panel, editing) {
    setPanelControlsEditable(panel, editing);
    setPanelButtons(panel, editing);
    panel.classList.toggle("is-editing", editing);
    if (editing) {
      activePanelKey = getPanelKey(panel);
    } else if (activePanelKey === getPanelKey(panel)) {
      activePanelKey = null;
    }
    updateEditingBanner();
  }

  function initPanelEditing() {
    if (!settingsForm || !settingsPanels.length) return;

    settingsPanels.forEach((panel) => {
      setPanelMode(panel, false);

      const editBtn = panel.querySelector("[data-panel-edit]");
      const cancelBtn = panel.querySelector("[data-panel-cancel]");
      const saveBtn = panel.querySelector("[data-panel-save]");

      editBtn?.addEventListener("click", () => {
        settingsPanels.forEach((other) => {
          if (other === panel) return;
          if (other.classList.contains("is-editing")) {
            restorePanel(other);
          }
          setPanelMode(other, false);
        });
        snapshotPanel(panel);
        setPanelMode(panel, true);
      });

      cancelBtn?.addEventListener("click", () => {
        restorePanel(panel);
        setPanelMode(panel, false);
        applyPushProviderVisibility();
      });

      saveBtn?.addEventListener("click", () => {
        settingsPanels.forEach((other) => {
          if (other !== panel) {
            setPanelMode(other, false);
          }
        });
        setPanelMode(panel, true);
      });
    });
  }

  function fmtDate(value) {
    if (!value) return "-";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleString();
  }


  function renderDeliveryHealth(delivery) {
    if (!telegramDeliveryWidget) return;
    if (telegramDeliveryTotal) telegramDeliveryTotal.textContent = String(delivery?.total ?? 0);
    if (telegramDeliverySent) telegramDeliverySent.textContent = String(delivery?.sent ?? 0);
    if (telegramDeliveryFailed) telegramDeliveryFailed.textContent = String(delivery?.failed ?? 0);
    if (telegramDeliveryCooldown) telegramDeliveryCooldown.textContent = String(delivery?.cooldown ?? 0);
    if (telegramDeliveryChecked) telegramDeliveryChecked.textContent = fmtDate(delivery?.checked_at);

    if (!telegramDeliveryFailures) return;
    const failures = Array.isArray(delivery?.recent_failures) ? delivery.recent_failures : [];
    if (!failures.length) {
      telegramDeliveryFailures.innerHTML = '<li class="muted">No recent failures.</li>';
      return;
    }

    telegramDeliveryFailures.innerHTML = failures
      .map((item) => {
        const title = String(item?.title || "Notification");
        const key = String(item?.key || "-");
        const when = fmtDate(item?.updated_at || item?.last_attempt_at);
        const error = String(item?.telegram_error || "delivery_failed");
        return `<li><strong>${title}</strong><span class="muted">${key} • ${when} • ${error}</span></li>`;
      })
      .join("");
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

    startLoading(testBtn, "Sending SMTP test");
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
      stopLoading(testBtn, '<i class="fa-solid fa-vial"></i>');
    }
  }

  if (testBtn) {
    testBtn.addEventListener("click", runTest);
  }

  async function runPushTest() {
    const custom = window.prompt("Optional message for push test:", "This is a test push from FinTracker Admin.");
    if (custom == null) return;
    const message = custom.trim() || "This is a test push from FinTracker Admin.";

    startLoading(pushTestBtn, "Sending push test");
    try {
      const res = await fetch("/admin/settings/push/test", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({
          title: "FinTracker Test Notification",
          message,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || "Push test failed.");
      }
      const result = data.result || {};
      notify(`Push test sent: ${result.sent || 0} delivered${result.failed ? `, ${result.failed} failed` : ""}.`, "success");
    } catch (err) {
      notify(err?.message || "Push test failed.", "error");
    } finally {
      stopLoading(pushTestBtn, '<i class="fa-solid fa-bell"></i>');
    }
  }

  if (pushTestBtn) {
    pushTestBtn.addEventListener("click", runPushTest);
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

    startLoading(telegramBroadcastBtn, "Sending broadcast");
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
      stopLoading(telegramBroadcastBtn, '<i class="fa-solid fa-paper-plane"></i>');
    }
  }

  if (telegramBroadcastBtn) {
    telegramBroadcastBtn.addEventListener("click", runTelegramBroadcast);
  }

  async function runSetWebhook() {
    if (!telegramWebhookSetBtn) return;
    startLoading(telegramWebhookSetBtn, "Setting webhook");
    try {
      await callTelegramAdmin("/admin/settings/telegram/webhook/set");
      notify("Webhook configured successfully.", "success");
    } catch (err) {
      notify(err?.message || "Failed to set webhook.", "error");
    } finally {
      stopLoading(telegramWebhookSetBtn, '<i class="fa-solid fa-plug-circle-check"></i>');
    }
  }

  async function runWebhookInfo() {
    if (!telegramWebhookInfoBtn) return;
    startLoading(telegramWebhookInfoBtn, "Checking webhook");
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
      stopLoading(telegramWebhookInfoBtn, '<i class="fa-solid fa-circle-info"></i>');
    }
  }

  async function runDeleteWebhook() {
    if (!telegramWebhookDeleteBtn) return;
    const confirmed = window.confirm("Delete Telegram webhook now?");
    if (!confirmed) return;
    startLoading(telegramWebhookDeleteBtn, "Deleting webhook");
    try {
      await callTelegramAdmin("/admin/settings/telegram/webhook/delete", { drop_pending_updates: false });
      notify("Webhook deleted successfully.", "success");
    } catch (err) {
      notify(err?.message || "Failed to delete webhook.", "error");
    } finally {
      stopLoading(telegramWebhookDeleteBtn, '<i class="fa-solid fa-link-slash"></i>');
    }
  }

  telegramWebhookSetBtn?.addEventListener("click", runSetWebhook);
  telegramWebhookInfoBtn?.addEventListener("click", runWebhookInfo);
  telegramWebhookDeleteBtn?.addEventListener("click", runDeleteWebhook);

  async function runPollStatus() {
    if (!telegramPollStatusBtn) return;
    startLoading(telegramPollStatusBtn, "Checking poll status");
    try {
      const data = await callTelegramAdmin("/admin/settings/telegram/poll/status");
      const poll = data.poll || {};
      renderPollHealth(poll);
      const msg = `last_update_id=${poll.last_update_id ?? "-"}, processed_updates=${poll.processed_updates ?? 0}, processed_messages=${poll.processed_messages ?? 0}, last_error=${poll.last_error || "none"}`;
      notify(msg, poll.last_error ? "error" : "info");
    } catch (err) {
      notify(err?.message || "Failed to fetch poll status.", "error");
    } finally {
      stopLoading(telegramPollStatusBtn, '<i class="fa-solid fa-heart-pulse"></i>');
    }
  }

  async function runPollOnce() {
    if (!telegramPollRunOnceBtn) return;
    startLoading(telegramPollRunOnceBtn, "Running poll");
    try {
      const data = await callTelegramAdmin("/admin/settings/telegram/poll/run-once");
      const poll = data.poll || {};
      renderPollHealth(poll);
      const msg = `Poll complete: updates=${poll.processed_updates ?? 0}, messages=${poll.processed_messages ?? 0}${poll.last_error ? `, error=${poll.last_error}` : ""}`;
      notify(msg, poll.last_error ? "error" : "success");
    } catch (err) {
      notify(err?.message || "Failed to run poll once.", "error");
    } finally {
      stopLoading(telegramPollRunOnceBtn, '<i class="fa-solid fa-play"></i>');
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


  async function refreshDeliveryHealthSilently() {
    if (!telegramDeliveryWidget) return;
    try {
      const data = await callTelegramAdmin("/admin/settings/telegram/delivery/status");
      renderDeliveryHealth(data.delivery || {});
    } catch (_err) {
      renderDeliveryHealth({});
    }
  }
  initPanelEditing();
  pushProviderInput?.addEventListener("change", applyPushProviderVisibility);
  applyPushProviderVisibility();

  if (telegramPollWidget || telegramDeliveryWidget) {
    if (telegramPollWidget) {
      refreshPollHealthSilently();
    }
    if (telegramDeliveryWidget) {
      refreshDeliveryHealthSilently();
    }

    livePollTimer = window.setInterval(() => {
      if (telegramPollWidget) refreshPollHealthSilently();
      if (telegramDeliveryWidget) refreshDeliveryHealthSilently();
    }, 10000);

    window.addEventListener("beforeunload", () => {
      if (livePollTimer) {
        window.clearInterval(livePollTimer);
        livePollTimer = null;
      }
    });
  }
})();
