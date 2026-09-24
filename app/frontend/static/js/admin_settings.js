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
  const backupRunBtns = Array.from(document.querySelectorAll("[data-backup-run]"));
  const backupRunBtn = backupRunBtns[0] || null;
  const backupStatusBtn = document.querySelector("[data-backup-status]");
  const backupLocalRefreshBtn = document.querySelector("[data-backup-local-refresh]");
  const backupStatusWidget = document.querySelector("[data-backup-status-widget]");
  const backupLastStatus = document.querySelector("[data-backup-last-status]");
  const backupLastTime = document.querySelector("[data-backup-last-time]");
  const backupLastSize = document.querySelector("[data-backup-last-size]");
  const backupLastCollections = document.querySelector("[data-backup-last-collections]");
  const backupLastDocuments = document.querySelector("[data-backup-last-documents]");
  const backupLastUploads = document.querySelector("[data-backup-last-uploads]");
  const backupConfigDestination = document.querySelector("[data-backup-config-destination]");
  const backupConfigSchedule = document.querySelector("[data-backup-config-schedule]");
  const backupConfigNextRun = document.querySelector("[data-backup-next-run]");
  const backupConfigRetention = document.querySelector("[data-backup-config-retention]");
  const backupLastError = document.querySelector("[data-backup-last-error]");
  const backupHistoryList = document.querySelector("[data-backup-history-list]");
  const backupLocalList = document.querySelector("[data-backup-local-list]");
  if (
    !testBtn &&
    !telegramBroadcastBtn &&
    !telegramWebhookSetBtn &&
    !telegramWebhookInfoBtn &&
    !telegramWebhookDeleteBtn &&
    !telegramPollRunOnceBtn &&
    !telegramPollStatusBtn &&
    !telegramDeliveryWidget &&
    !pushTestBtn &&
    !backupRunBtns.length &&
    !backupStatusWidget &&
    !backupLocalList
  ) return;

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
  const settingsForm = document.querySelector(".settings-form");
  const settingsPanels = Array.from(document.querySelectorAll("[data-settings-panel]"));
  const autosaveToggles = Array.from(document.querySelectorAll("[data-autosave-toggle=\"true\"]"));
  const MODAL_PANEL_KEYS = new Set(["application", "database", "runtime", "backup", "smtp", "telegram", "push_notifications", "authentication"]);
  const settingsPages = {
    application: ["application", "database", "runtime", "backup"],
    messaging: ["smtp", "telegram", "push_notifications", "telegram_ops", "authentication"],
  };
  let activePanelKey = null;
  const panelSnapshot = new Map();
  const backupPanel = settingsPanels.find((panel) => getPanelKey(panel) === "backup") || null;
  const backupSaveBtn = document.querySelector('[data-settings-dialog="backup"] [data-panel-save]') || null;
  let currentBackupStatusPayload = null;
  let backupValidationTimer = null;
  let backupValidationRequest = 0;

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

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
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

  async function inlineNotice(btn, message, kind = "success", duration = 2200) {
    if (window.ftInlineFeedback?.showFor && btn) {
      await window.ftInlineFeedback.showFor(btn, message, kind, duration);
      return;
    }
    notify(message, kind);
  }

  function applyPushProviderVisibility() {
    return;
  }

  function getPanelKey(panel) {
    return String(panel?.getAttribute("data-settings-panel") || "").trim();
  }

  function getPanelDialog(panel) {
    const key = getPanelKey(panel);
    const dialog = document.querySelector(`[data-settings-dialog="${key}"]`);
    return dialog instanceof HTMLDialogElement ? dialog : null;
  }

  function getPanelFormRoot(panel) {
    return getPanelDialog(panel) || panel;
  }

  function isModalPanel(panel) {
    return MODAL_PANEL_KEYS.has(getPanelKey(panel));
  }
  function getPanelTitle(panel) {
    const heading = panel?.querySelector(".settings-card__identity h3, .settings-block__head h3, .settings-group-head h3");
    return String(heading?.textContent || getPanelKey(panel) || "Settings").trim();
  }

  function getPanelControls(panel) {
    const root = getPanelFormRoot(panel);
    return Array.from(root.querySelectorAll("input, select, textarea")).filter((el) => {
      if (!(el instanceof HTMLElement)) return false;
      if (el.closest(".settings-dialog__foot")) return false;
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
    const root = getPanelFormRoot(panel);
    state.forEach((item) => {
      const el = root.querySelector(`[name="${item.name}"]`);
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
    const editingChip = panel.querySelector("[data-panel-editing-label]");
    if (editBtn instanceof HTMLElement) editBtn.hidden = editing;
    if (saveBtn instanceof HTMLElement) saveBtn.hidden = !editing;
    if (cancelBtn instanceof HTMLElement) cancelBtn.hidden = !editing;
    if (editingChip instanceof HTMLElement) editingChip.hidden = !editing;
  }

  function setPanelMode(panel, editing) {
    if (isModalPanel(panel)) {
      panel.classList.remove("is-editing");
      return;
    }
    setPanelControlsEditable(panel, editing);
    setPanelButtons(panel, editing);
    panel.classList.toggle("is-editing", editing);
    if (editing) {
      activePanelKey = getPanelKey(panel);
    } else if (activePanelKey === getPanelKey(panel)) {
      activePanelKey = null;
    }
  }

  function getSectionSubmitter(panel) {
    if (!(panel instanceof HTMLElement)) return null;
    const sectionValue = getPanelKey(panel);
    if (!sectionValue) return null;
    const root = getPanelFormRoot(panel);
    const runtimeBtn = root.querySelector('button[type="submit"][name="settings_section"][value="runtime"]');
    if (runtimeBtn instanceof HTMLButtonElement) return runtimeBtn;
    const saveBtn = root.querySelector(`[data-panel-save][name="settings_section"][value="${sectionValue}"]`);
    if (saveBtn instanceof HTMLButtonElement) return saveBtn;
    return null;
  }

  function temporarilyEnablePanelInputs(panel) {
    const disabledFields = Array.from(panel.querySelectorAll("input:disabled, select:disabled, textarea:disabled")).filter((el) => {
      if (!(el instanceof HTMLElement)) return false;
      const name = (el.getAttribute("name") || "").trim();
      if (!name) return false;
      if (name === "csrf_token") return false;
      return true;
    });

    disabledFields.forEach((el) => {
      if (el instanceof HTMLInputElement || el instanceof HTMLSelectElement || el instanceof HTMLTextAreaElement) {
        el.disabled = false;
      }
    });

    return () => {
      disabledFields.forEach((el) => {
        if (el instanceof HTMLInputElement || el instanceof HTMLSelectElement || el instanceof HTMLTextAreaElement) {
          el.disabled = true;
        }
      });
    };
  }

  function initToggleAutosave() {
    if (!settingsForm || !autosaveToggles.length) return;

    autosaveToggles.forEach((toggle) => {
      if (!(toggle instanceof HTMLInputElement)) return;
      toggle.addEventListener("change", () => {
        const panel = toggle.closest("[data-settings-panel]");
        if (!(panel instanceof HTMLElement)) return;
        if (toggle.dataset.autosaveBusy === "1") return;

        const submitter = getSectionSubmitter(panel);
        if (!(submitter instanceof HTMLButtonElement)) return;

        const label = String(toggle.dataset.autosaveLabel || getPanelTitle(panel) || "Setting").trim();
        const stateText = toggle.checked ? "enabled" : "disabled";
        const inlineMessage = `${label} ${stateText}`;

        const restoreInputs = temporarilyEnablePanelInputs(panel);
        const prevMessage = String(submitter.getAttribute("data-inline-success-message") || "Settings saved");

        toggle.dataset.autosaveBusy = "1";
        submitter.setAttribute("data-inline-success-message", inlineMessage);

        settingsForm.requestSubmit(submitter);

        window.setTimeout(() => {
          restoreInputs();
          submitter.setAttribute("data-inline-success-message", prevMessage);
          delete toggle.dataset.autosaveBusy;
        }, 500);
      });
    });
  }

  function initSettingsDialogs() {
    document.querySelectorAll("[data-settings-dialog]").forEach((dialogEl) => {
      if (!(dialogEl instanceof HTMLDialogElement)) return;
      const key = String(dialogEl.getAttribute("data-settings-dialog") || "").trim();
      const panel = settingsPanels.find((item) => getPanelKey(item) === key) || null;

      dialogEl.querySelectorAll("[data-dialog-close]").forEach((btn) => {
        btn.addEventListener("click", () => {
          if (panel) restorePanel(panel);
          dialogEl.close();
        });
      });

      dialogEl.addEventListener("click", (event) => {
        if (event.target === dialogEl) {
          if (panel) restorePanel(panel);
          dialogEl.close();
        }
      });

      dialogEl.querySelector('button[type="submit"][data-panel-save]')?.addEventListener("click", async (event) => {
        if (key === "backup") {
          event.preventDefault();
          const valid = await validateBackupSettings();
          if (!valid) return;
          dialogEl.close();
          if (settingsForm && event.currentTarget instanceof HTMLButtonElement) {
            settingsForm.requestSubmit(event.currentTarget);
          }
          return;
        }
        dialogEl.close();
      });
    });

    const maintenanceField = document.querySelector('[data-settings-dialog="runtime"] [name="maintenance_message"]');
    const maintenanceCount = document.querySelector("[data-maintenance-count]");
    if (maintenanceField instanceof HTMLTextAreaElement && maintenanceCount instanceof HTMLElement) {
      const syncCount = () => {
        maintenanceCount.textContent = `${(maintenanceField.value || "").length} / 200`;
      };
      maintenanceField.addEventListener("input", syncCount);
    }

    const backupDialog = document.querySelector('[data-settings-dialog="backup"]');
    if (backupDialog instanceof HTMLElement) {
      backupDialog.querySelectorAll('[name="backup_enabled"], [name="backup_provider"], [name="backup_schedule_time"], [name="backup_retention_days"], [name="backup_destination"], [name="application_timezone"]').forEach((el) => {
        el.addEventListener("input", scheduleBackupValidation);
        el.addEventListener("change", scheduleBackupValidation);
      });
    }
  }

  function initSettingsPageSwitch() {
    document.querySelectorAll("[data-settings-page]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const page = String(btn.getAttribute("data-settings-page") || "application").trim();
        applySettingsPage(page);
      });
    });
  }

  function initRevealAndCopy() {
    document.querySelectorAll("[data-secret-toggle]").forEach((btn) => {
      if (!(btn instanceof HTMLButtonElement)) return;
      btn.addEventListener("click", () => {
        const valueEl = btn.parentElement?.querySelector("[data-secret-value]");
        if (!(valueEl instanceof HTMLElement)) return;
        const hidden = btn.getAttribute("data-secret-hidden") || "••••••••";
        const shown = btn.getAttribute("data-secret-shown") || hidden;
        const revealing = valueEl.textContent === hidden;
        valueEl.textContent = revealing ? shown : hidden;
        const icon = btn.querySelector("i");
        if (icon) icon.className = revealing ? "fa-solid fa-eye-slash" : "fa-solid fa-eye";
        btn.setAttribute("aria-label", revealing ? "Hide value" : "Show value");
      });
    });

    document.querySelectorAll("[data-copy-text]").forEach((btn) => {
      if (!(btn instanceof HTMLButtonElement)) return;
      btn.addEventListener("click", async () => {
        const text = btn.getAttribute("data-copy-text") || "";
        if (!text) return;
        try {
          await navigator.clipboard.writeText(text);
          await inlineNotice(btn, "Copied", "success", 1200);
        } catch (_err) {
          notify("Could not copy to clipboard.", "error");
        }
      });
    });
  }

  function initPanelEditing() {
    if (!settingsForm || !settingsPanels.length) return;

    settingsPanels.forEach((panel) => {
      if (isModalPanel(panel)) {
        setPanelMode(panel, false);
        const editBtn = panel.querySelector("[data-panel-edit]");
        editBtn?.addEventListener("click", () => {
          const dialog = getPanelDialog(panel);
          if (!dialog) return;
          snapshotPanel(panel);
          dialog.showModal();
          if (getPanelKey(panel) === "backup") {
            validateBackupSettings({ silent: true });
          }
        });
        return;
      }

      if (getPanelKey(panel) === "telegram_ops") return;

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

  function fmtBytes(value) {
    const size = Number(value || 0);
    if (!size) return "-";
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
    return `${(size / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }

  function normalizePanelKey(sectionKey) {
    const raw = String(sectionKey || "").trim();
    if (!raw) return "";
    if (raw === "push") return "push_notifications";
    if (raw === "messaging") return "smtp";
    return raw;
  }

  function resolveSettingsPage(sectionKey) {
    const raw = String(sectionKey || "").trim();
    if (!raw) return "application";
    if (raw === "backup") return "application";
    if (["smtp", "telegram", "push_notifications", "push", "messaging", "telegram_ops", "authentication"].includes(raw)) return "messaging";
    if (settingsPages[raw]) return raw;
    const normalized = normalizePanelKey(raw);
    if (normalized === "push_notifications" || normalized === "telegram" || normalized === "smtp" || normalized === "authentication") return "messaging";
    if (settingsPages[normalized]) return normalized;
    return "application";
  }

  function resolveFocusPanel(sectionKey) {
    const raw = String(sectionKey || "").trim();
    if (!raw) return "application";
    if (["backup", "database", "runtime", "application"].includes(raw)) return raw;
    if (raw === "messaging") return "smtp";
    if (raw === "telegram_ops") return "telegram_ops";
    if (raw === "authentication") return "authentication";
    const normalized = normalizePanelKey(raw);
    if (["smtp", "telegram", "push_notifications"].includes(normalized)) return normalized;
    return normalized || "application";
  }

  function setActiveSettingsSubnav(sectionKey) {
    const pageKey = resolveSettingsPage(sectionKey);
    document.querySelectorAll("[data-admin-settings-link], [data-settings-page]").forEach((link) => {
      const key = link.getAttribute("data-settings-page") || link.getAttribute("data-admin-settings-link");
      const isActive = key === pageKey;
      link.classList.toggle("active", isActive);
      link.classList.toggle("is-active", isActive);
      if (link.getAttribute("role") === "tab") {
        link.setAttribute("aria-selected", isActive ? "true" : "false");
      }
      if (isActive) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  function applySettingsPage(sectionKey) {
    const pageKey = resolveSettingsPage(sectionKey);
    const visibleKeys = settingsPages[pageKey] || settingsPages.application;
    const scroll = document.querySelector(".settings-scroll");
    const generalShell = document.querySelector('[data-settings-layout="general"]');
    const messagingShell = document.querySelector('[data-settings-layout="messaging"]');
    const isGeneral = pageKey === "application";
    const isMessaging = pageKey === "messaging";

    scroll?.classList.toggle("is-general-page", isGeneral);
    scroll?.classList.toggle("is-messaging-page", isMessaging);
    const heroCopy = document.querySelector("[data-settings-hero-copy]");
    if (heroCopy instanceof HTMLElement) {
      const copyByPage = {
        application: "Manage your platform configuration and preferences.",
        messaging: "Manage messaging, notifications, and sign-in.",
      };
      heroCopy.textContent = copyByPage[pageKey] || copyByPage.application;
    }
    if (generalShell instanceof HTMLElement) {
      generalShell.hidden = !isGeneral;
    }
    if (messagingShell instanceof HTMLElement) {
      messagingShell.hidden = !isMessaging;
    }

    document.querySelectorAll("[data-settings-section-head]").forEach((head) => {
      if (!(head instanceof HTMLElement)) return;
      head.hidden = head.getAttribute("data-settings-section-head") !== pageKey;
    });

    settingsPanels.forEach((panel) => {
      const key = getPanelKey(panel);
      if (key === "telegram_ops" && panel.closest('[data-settings-panel="telegram"]')) {
        panel.hidden = false;
        return;
      }
      panel.hidden = !visibleKeys.includes(key);
    });
    setActiveSettingsSubnav(sectionKey);
    return pageKey;
  }

  function focusSectionPanel(sectionKey) {
    applySettingsPage(sectionKey);
    const focusKey = resolveFocusPanel(sectionKey);
    const panel = settingsPanels.find((item) => getPanelKey(item) === focusKey) ||
      settingsPanels.find((item) => !item.hidden);
    if (!panel) return;
    panel.classList.add("is-targeted");
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    window.setTimeout(() => panel.classList.remove("is-targeted"), 1600);
  }

  function focusRequestedSection() {
    const params = new URLSearchParams(window.location.search);
    const sectionKey = params.get("section") || window.sessionStorage.getItem("ftAdminSettingsTarget") || "application";
    window.sessionStorage.removeItem("ftAdminSettingsTarget");
    focusSectionPanel(sectionKey);
  }

  function renderBackupStatus(payload, requestError = "") {
    if (!backupStatusWidget) return;
    const config = payload?.config || {};
    const run = payload?.last_run || {};
    currentBackupStatusPayload = { config, last_run: run };

    const metricLast = document.querySelector("[data-backup-metric-last]");
    const metricLastSub = document.querySelector("[data-backup-metric-last-sub]");
    const metricNext = document.querySelector("[data-backup-metric-next]");
    const metricNextSub = document.querySelector("[data-backup-metric-next-sub]");
    const metricStatus = document.querySelector("[data-backup-metric-status]");
    const metricRetention = document.querySelector("[data-backup-metric-retention]");
    const enabledBadge = document.querySelector("[data-backup-enabled-badge]");

    if (backupLastStatus) backupLastStatus.textContent = run.status || "Not run";
    if (backupLastTime) backupLastTime.textContent = fmtDate(run.completed_at || run.started_at);
    if (backupLastSize) backupLastSize.textContent = fmtBytes(run.archive_size_bytes);
    if (backupLastCollections) backupLastCollections.textContent = String(run.collections ?? "-");
    if (backupLastDocuments) backupLastDocuments.textContent = String(run.documents ?? "-");
    if (backupLastUploads) backupLastUploads.textContent = run.archive_name ? (run.includes_uploads ? "Yes" : "No") : "-";
    if (backupConfigSchedule) {
      const enabled = config.enabled ? "enabled" : "manual";
      backupConfigSchedule.textContent = `${enabled} • ${config.schedule_display || (config.schedule_time ? `${config.schedule_time} ${config.timezone || ""}`.trim() : "Manual only")}`;
    }
    if (backupConfigNextRun) backupConfigNextRun.textContent = fmtDate(config.next_run);
    if (metricLast) metricLast.textContent = run.completed_at || run.started_at ? fmtDate(run.completed_at || run.started_at) : "Not run yet";
    if (metricLastSub) metricLastSub.textContent = run.completed_at || run.started_at ? fmtDate(run.completed_at || run.started_at) : "—";
    if (metricNext) metricNext.textContent = config.next_run ? fmtDate(config.next_run) : "Not scheduled";
    if (metricNextSub) metricNextSub.textContent = config.next_run ? fmtDate(config.next_run) : "Enable scheduling";
    if (metricStatus) metricStatus.textContent = run.status || "Not run";
    if (metricRetention) {
      const days = config.retention_days ?? val("backup_retention_days");
      metricRetention.textContent = days ? `${days} days` : "— days";
    }
    if (enabledBadge) {
      enabledBadge.textContent = config.enabled ? "Backup Enabled" : "Backup Disabled";
      enabledBadge.classList.toggle("is-on", Boolean(config.enabled));
      enabledBadge.classList.toggle("is-off", !config.enabled);
    }
    if (backupLastError) {
      const message = requestError || config.validation_error || run.error || run.last_restore_error || "";
      backupLastError.hidden = !message;
      backupLastError.textContent = message;
    }
  }

  function renderBackupHistory(history) {
    if (!backupHistoryList) return;
    const rows = Array.isArray(history) ? history : [];
    if (!rows.length) {
      backupHistoryList.innerHTML = '<li class="muted">No backups yet.</li>';
      return;
    }
    backupHistoryList.innerHTML = rows.map((item) => {
      const name = escapeHtml(String(item.archive_name || item.status || "backup"));
      const when = escapeHtml(fmtDate(item.completed_at || item.started_at));
      const size = escapeHtml(fmtBytes(item.archive_size_bytes));
      const details = escapeHtml(`${item.collections || 0} collections • ${item.documents || 0} docs • ${size}`);
      const status = escapeHtml(String(item.status || "unknown"));
      const restoreMeta = item.last_restored_at
        ? ` • restored ${escapeHtml(fmtDate(item.last_restored_at))}`
        : (item.last_restore_status === "failed" && item.last_restore_error
          ? ` • restore failed: ${escapeHtml(item.last_restore_error)}`
          : "");
      const canRestore = ["completed", "expired"].includes(String(item.status || "").toLowerCase()) && item.id;
      const restoreBtn = canRestore
        ? `<button type="button" class="btn-action btn-icon backup-history-restore" data-backup-restore-id="${escapeHtml(item.id)}" data-default-html="<i class='fa-solid fa-clock-rotate-left'></i>" title="Restore this backup" aria-label="Restore this backup"><i class="fa-solid fa-clock-rotate-left"></i></button>`
        : "";
      const deleteBtn = item.id
        ? `<button type="button" class="btn-action warn btn-icon backup-history-delete" data-backup-delete-id="${escapeHtml(item.id)}" data-default-html="<i class='fa-solid fa-trash'></i>" title="Delete this backup" aria-label="Delete this backup"><i class="fa-solid fa-trash"></i></button>`
        : "";
      return `<li><div><strong>${name}</strong><span class="muted">${when} • ${status} • ${details}${restoreMeta}</span></div><div class="backup-history-actions">${restoreBtn}${deleteBtn}</div></li>`;
    }).join("");
  }

  function renderLocalBackups(localBackups) {
    if (!backupLocalList) return;
    const rows = Array.isArray(localBackups) ? localBackups : [];
    if (!rows.length) {
      backupLocalList.innerHTML = '<li class="muted">No local backups found.</li>';
      return;
    }
    backupLocalList.innerHTML = rows.map((item) => {
      const name = escapeHtml(String(item.archive_name || "backup"));
      const when = escapeHtml(fmtDate(item.created_at));
      const size = escapeHtml(fmtBytes(item.archive_size_bytes));
      const source = escapeHtml(String(item.source || "filesystem"));
      const verify = item.verified ? "verified" : `unverified: ${escapeHtml(item.validation_error || "manifest missing")}`;
      const uploads = item.includes_uploads ? "uploads:yes" : "uploads:no";
      const details = escapeHtml(`${item.collections || 0} collections • ${item.documents || 0} docs • ${size}`);
      const meta = `${when} • ${source} • ${uploads} • ${verify}`;
      const verifyBtn = `<button type="button" class="btn-action btn-icon backup-history-verify" data-backup-verify-file="${name}" data-default-html="<i class='fa-solid fa-circle-check'></i>" title="Verify this file" aria-label="Verify this file"><i class="fa-solid fa-circle-check"></i></button>`;
      const restoreBtn = `<button type="button" class="btn-action btn-icon backup-history-restore" data-backup-restore-file="${name}" data-default-html="<i class='fa-solid fa-life-ring'></i>" title="Restore this file" aria-label="Restore this file"><i class="fa-solid fa-life-ring"></i></button>`;
      const deleteBtn = `<button type="button" class="btn-action warn btn-icon backup-history-delete" data-backup-delete-file="${name}" data-default-html="<i class='fa-solid fa-trash'></i>" title="Delete this file" aria-label="Delete this file"><i class="fa-solid fa-trash"></i></button>`;
      return `<li><div><strong>${name}</strong><span class="muted">${meta} • ${details}</span></div><div class="backup-history-actions">${verifyBtn}${restoreBtn}${deleteBtn}</div></li>`;
    }).join("");
  }

  async function postBackupAdmin(path, body = null) {
    const headers = {
      "X-CSRF-Token": csrfToken,
    };
    if (body !== null) {
      headers["Content-Type"] = "application/json";
    }
    const res = await fetch(path, {
      method: "POST",
      headers,
      body: body !== null ? JSON.stringify(body) : null,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || "Backup request failed.");
    }
    return data;
  }

  async function refreshBackupStatusSilently() {
    if (!backupStatusWidget && !backupLocalList) return;
    try {
      const requests = [
        postBackupAdmin("/admin/settings/backup/status"),
        postBackupAdmin("/admin/settings/backup/history"),
        postBackupAdmin("/admin/settings/backup/local-history", getBackupPayloadFromForm()),
      ];
      const [statusData, historyData, localData] = await Promise.all(requests);
      renderBackupStatus(statusData.backup || {});
      renderBackupHistory(historyData.history || []);
      renderLocalBackups(localData.local_backups || []);
    } catch (err) {
      renderBackupStatus({}, err?.message || "Failed to load backup status.");
    }
  }

  async function refreshLocalBackupsSilently() {
    if (!backupLocalList) return;
    try {
      const data = await postBackupAdmin("/admin/settings/backup/local-history", getBackupPayloadFromForm());
      renderLocalBackups(data.local_backups || []);
    } catch (_err) {
      renderLocalBackups([]);
    }
  }

  async function runBackupNow(event) {
    const btn = event?.currentTarget instanceof HTMLElement ? event.currentTarget : backupRunBtn;
    if (!btn) return;
    startLoading(btn, "Running backup");
    try {
      const data = await postBackupAdmin("/admin/settings/backup/run");
      renderBackupStatus({ config: (await postBackupAdmin("/admin/settings/backup/status")).backup?.config || {}, last_run: data.backup || {} });
      renderBackupHistory(data.history || []);
      await refreshLocalBackupsSilently();
      await inlineNotice(btn, "Backup complete");
    } catch (err) {
      notify(err?.message || "Backup failed.", "error");
      await refreshBackupStatusSilently();
    } finally {
      stopLoading(btn, btn.dataset.defaultHtml || '<i class="fa-solid fa-box-archive"></i>');
    }
  }

  async function runBackupStatus() {
    if (!backupStatusBtn) return;
    startLoading(backupStatusBtn, "Refreshing backup status");
    try {
      await refreshBackupStatusSilently();
      await inlineNotice(backupStatusBtn, "Status updated", "info", 1500);
    } catch (err) {
      notify(err?.message || "Failed to refresh backup status.", "error");
    } finally {
      stopLoading(backupStatusBtn, backupStatusBtn.dataset.defaultHtml || '<i class="fa-solid fa-rotate" aria-hidden="true"></i> Refresh');
    }
  }

  function getBackupPayloadFromForm() {
    return {
      application: {
        timezone: val("application_timezone"),
      },
      backup: {
        enabled: checked("backup_enabled"),
        provider: val("backup_provider"),
        schedule_time: val("backup_schedule_time"),
        retention_days: val("backup_retention_days"),
        destination: val("backup_destination"),
      },
    };
  }

  async function validateBackupSettings({ silent = false } = {}) {
    if (!backupPanel) return true;
    const requestId = ++backupValidationRequest;
    try {
      const data = await postBackupAdmin("/admin/settings/backup/validate", getBackupPayloadFromForm());
      if (requestId !== backupValidationRequest) return true;
      renderBackupStatus({
        config: data.config || {},
        last_run: currentBackupStatusPayload?.last_run || {},
      });
      return true;
    } catch (err) {
      if (requestId !== backupValidationRequest) return false;
      const detail = err?.message || "Backup settings are invalid.";
      const existingConfig = currentBackupStatusPayload?.config || {};
      const lastRun = currentBackupStatusPayload?.last_run || {};
      renderBackupStatus({
        config: { ...existingConfig, ...getBackupPayloadFromForm().backup, validation_error: detail, next_run: null },
        last_run: lastRun,
      });
      if (!silent) {
        notify(detail, "error");
      }
      return false;
    }
  }

  function scheduleBackupValidation() {
    if (!backupPanel) return;
    const dialog = getPanelDialog(backupPanel);
    if (!(dialog instanceof HTMLDialogElement) || !dialog.open) return;
    if (backupValidationTimer) {
      window.clearTimeout(backupValidationTimer);
    }
    backupValidationTimer = window.setTimeout(() => {
      validateBackupSettings({ silent: true });
    }, 250);
  }

  async function runBackupRestore(btn, backupId) {
    if (!btn || !backupId) return;
    const confirmed = window.confirm("Restore this backup now? A safety backup will be created first.");
    if (!confirmed) return;
    startLoading(btn, "Restoring backup");
    try {
      const data = await postBackupAdmin("/admin/settings/backup/restore", {
        backup_id: backupId,
        create_safety_backup: true,
      });
      renderBackupStatus(data.backup || {});
      renderBackupHistory(data.history || []);
      renderLocalBackups(data.local_backups || []);
      await inlineNotice(btn, "Restore complete");
    } catch (err) {
      notify(err?.message || "Backup restore failed.", "error");
      await refreshBackupStatusSilently();
    } finally {
      stopLoading(btn, '<i class="fa-solid fa-clock-rotate-left"></i>');
    }
  }


  async function runLocalBackupRefresh() {
    if (!backupLocalRefreshBtn) return;
    startLoading(backupLocalRefreshBtn, "Refreshing local backups");
    try {
      await refreshLocalBackupsSilently();
      await inlineNotice(backupLocalRefreshBtn, "Local backups updated", "info", 1500);
    } catch (err) {
      notify(err?.message || "Failed to refresh local backups.", "error");
    } finally {
      stopLoading(backupLocalRefreshBtn, '<i class="fa-solid fa-folder-tree"></i>');
    }
  }

  async function runBackupRestoreFile(btn, archiveName) {
    if (!btn || !archiveName) return;
    const confirmed = window.confirm("Restore this local backup file now? A safety backup will be created first.");
    if (!confirmed) return;
    startLoading(btn, "Restoring file");
    try {
      const data = await postBackupAdmin("/admin/settings/backup/restore-file", {
        archive_name: archiveName,
        create_safety_backup: true,
      });
      renderBackupStatus(data.backup || {});
      renderBackupHistory(data.history || []);
      renderLocalBackups(data.local_backups || []);
      await inlineNotice(btn, "Restore complete");
    } catch (err) {
      notify(err?.message || "Backup restore failed.", "error");
      await refreshBackupStatusSilently();
    } finally {
      stopLoading(btn, '<i class="fa-solid fa-life-ring"></i>');
    }
  }


  async function runBackupVerifyFile(btn, archiveName) {
    if (!btn || !archiveName) return;
    startLoading(btn, "Verifying file");
    try {
      const data = await postBackupAdmin("/admin/settings/backup/verify-file", {
        archive_name: archiveName,
        ...getBackupPayloadFromForm(),
      });
      renderLocalBackups(data.local_backups || []);
      await inlineNotice(btn, "Backup verified", "info", 1500);
    } catch (err) {
      notify(err?.message || "Backup verification failed.", "error");
      await refreshLocalBackupsSilently();
    } finally {
      stopLoading(btn, '<i class="fa-solid fa-circle-check"></i>');
    }
  }


  async function runBackupDelete(btn, backupId) {
    if (!btn || !backupId) return;
    const confirmed = window.confirm("Delete this backup history entry and its archive file if it still exists?");
    if (!confirmed) return;
    startLoading(btn, "Deleting backup");
    try {
      const data = await postBackupAdmin("/admin/settings/backup/delete", { backup_id: backupId });
      renderBackupStatus(data.backup || {});
      renderBackupHistory(data.history || []);
      renderLocalBackups(data.local_backups || []);
      await inlineNotice(btn, "Backup deleted", "info", 1500);
    } catch (err) {
      notify(err?.message || "Backup delete failed.", "error");
      await refreshBackupStatusSilently();
    } finally {
      stopLoading(btn, '<i class="fa-solid fa-trash"></i>');
    }
  }

  async function runBackupDeleteFile(btn, archiveName) {
    if (!btn || !archiveName) return;
    const confirmed = window.confirm("Delete this backup file and any linked history entry?");
    if (!confirmed) return;
    startLoading(btn, "Deleting file");
    try {
      const data = await postBackupAdmin("/admin/settings/backup/delete-file", {
        archive_name: archiveName,
        ...getBackupPayloadFromForm(),
      });
      renderBackupStatus(data.backup || {});
      renderBackupHistory(data.history || []);
      renderLocalBackups(data.local_backups || []);
      await inlineNotice(btn, "Backup deleted", "info", 1500);
    } catch (err) {
      notify(err?.message || "Backup delete failed.", "error");
      await refreshBackupStatusSilently();
    } finally {
      stopLoading(btn, '<i class="fa-solid fa-trash"></i>');
    }
  }


  function setHealthBadge(el, status) {
    if (!(el instanceof HTMLElement)) return;
    const normalized = String(status || "Unknown");
    el.textContent = normalized;
    el.classList.remove("is-ok", "is-warn", "is-bad", "is-unknown");
    if (/healthy|ok|enabled/i.test(normalized)) el.classList.add("is-ok");
    else if (/degrad|warn/i.test(normalized)) el.classList.add("is-warn");
    else if (/error|fail|bad/i.test(normalized)) el.classList.add("is-bad");
    else el.classList.add("is-unknown");
  }

  function renderDeliveryHealth(delivery) {
    if (!telegramDeliveryWidget) return;
    if (telegramDeliveryTotal) telegramDeliveryTotal.textContent = String(delivery?.total ?? 0);
    if (telegramDeliverySent) telegramDeliverySent.textContent = String(delivery?.sent ?? 0);
    if (telegramDeliveryFailed) {
      telegramDeliveryFailed.textContent = String(delivery?.failed ?? 0);
      telegramDeliveryFailed.closest("article")?.classList.toggle("is-hot", Number(delivery?.failed ?? 0) > 0);
    }
    if (telegramDeliveryCooldown) telegramDeliveryCooldown.textContent = String(delivery?.cooldown ?? 0);
    if (telegramDeliveryChecked) telegramDeliveryChecked.textContent = fmtDate(delivery?.checked_at);
    const failedCount = Number(delivery?.failed ?? 0);
    const deliveryBadge = document.querySelector("[data-telegram-delivery-health-badge]");
    setHealthBadge(deliveryBadge, failedCount > 0 ? "Attention" : (delivery?.checked_at ? "Healthy" : "Unknown"));

    if (!telegramDeliveryFailures) return;
    const failures = Array.isArray(delivery?.recent_failures) ? delivery.recent_failures : [];
    if (!failures.length) {
      telegramDeliveryFailures.innerHTML = '<li class="muted">No recent failures.</li>';
      return;
    }

    telegramDeliveryFailures.innerHTML = failures.slice(0, 3)
      .map((item) => {
        const title = escapeHtml(String(item?.title || "Notification"));
        const error = escapeHtml(String(item?.telegram_error || "delivery_failed"));
        const when = escapeHtml(fmtDate(item?.updated_at || item?.last_attempt_at));
        const tone = /fail|error/i.test(String(item?.telegram_error || "")) ? "is-bad" : "is-warn";
        return `<li class="settings-fail-row"><span class="settings-state__dot ${tone}" aria-hidden="true"></span><div><strong>${title}</strong><span class="muted">${error}</span></div><time>${when}</time></li>`;
      })
      .join("");
  }
  function renderPollHealth(poll, requestError = "") {
    if (!telegramPollWidget) return;
    const lastError = requestError || poll?.last_error || "";
    const status = requestError ? "Error" : (lastError ? "Degraded" : "Healthy");
    if (telegramPollHealthStatus) telegramPollHealthStatus.textContent = status;
    setHealthBadge(document.querySelector("[data-telegram-poll-health-badge]"), status);
    if (telegramPollHealthTime) telegramPollHealthTime.textContent = fmtDate(poll?.last_poll_at);
    if (telegramPollHealthUpdate) telegramPollHealthUpdate.textContent = String(poll?.last_update_id ?? "-");
    if (telegramPollHealthProcessed) {
      telegramPollHealthProcessed.textContent = `${poll?.processed_updates ?? 0} Updates / ${poll?.processed_messages ?? 0} Messages`;
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
      await inlineNotice(testBtn, "Test sent");
    } catch (err) {
      notify(err?.message || "SMTP test failed.", "error");
    } finally {
      stopLoading(testBtn, testBtn.dataset.defaultHtml || '<i class="fa-solid fa-play" aria-hidden="true"></i> Test');
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
      if (typeof window.ftEnsurePushSubscription === "function") {
        const bootstrap = await window.ftEnsurePushSubscription();
        if (bootstrap && bootstrap.ok === false) {
          const reason = String(bootstrap.reason || "");
          if (reason.startsWith("notification_permission_")) {
            throw new Error("Notification permission is not granted in this browser. Allow notifications and retry.");
          }
          if (reason === "push_disabled_or_unconfigured") {
            throw new Error("Push is disabled or not fully configured.");
          }
          if (reason === "bootstrap_error") {
            throw new Error(`Push registration failed: ${bootstrap.error || "unknown error"}`);
          }
        }
      }

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
      await inlineNotice(pushTestBtn, `Sent ${result.sent || 0}${result.failed ? `, ${result.failed} failed` : ""}`);
    } catch (err) {
      notify(err?.message || "Push test failed.", "error");
    } finally {
      stopLoading(pushTestBtn, pushTestBtn.dataset.defaultHtml || '<i class="fa-solid fa-play" aria-hidden="true"></i> Test');
    }
  }

  if (pushTestBtn) {
    pushTestBtn.addEventListener("click", runPushTest);
  }


  async function runTelegramBroadcast() {
    const defaultMessage = telegramBroadcastInput?.getAttribute("data-default-message") || "FinTracker Telegram test.";
    const text = (telegramBroadcastInput?.value || "").trim() || defaultMessage;
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
      await inlineNotice(telegramBroadcastBtn, summary);
      if (telegramBroadcastInput) {
        telegramBroadcastInput.value = defaultMessage;
      }
    } catch (err) {
      notify(err?.message || "Telegram broadcast failed.", "error");
    } finally {
      stopLoading(telegramBroadcastBtn, telegramBroadcastBtn.dataset.defaultHtml || '<i class="fa-solid fa-paper-plane" aria-hidden="true"></i> Send Test');
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
      await inlineNotice(telegramWebhookSetBtn, "Webhook saved");
    } catch (err) {
      notify(err?.message || "Failed to set webhook.", "error");
    } finally {
      stopLoading(telegramWebhookSetBtn, telegramWebhookSetBtn.dataset.defaultHtml || '<i class="fa-solid fa-plug-circle-check" aria-hidden="true"></i> Set Webhook');
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
      await inlineNotice(telegramWebhookInfoBtn, "Webhook checked", "info");
    } catch (err) {
      notify(err?.message || "Failed to check webhook.", "error");
    } finally {
      stopLoading(telegramWebhookInfoBtn, telegramWebhookInfoBtn.dataset.defaultHtml || '<i class="fa-solid fa-circle-info" aria-hidden="true"></i> Check Status');
    }
  }

  async function runDeleteWebhook() {
    if (!telegramWebhookDeleteBtn) return;
    const confirmed = window.confirm("Delete Telegram webhook now?");
    if (!confirmed) return;
    startLoading(telegramWebhookDeleteBtn, "Deleting webhook");
    try {
      await callTelegramAdmin("/admin/settings/telegram/webhook/delete", { drop_pending_updates: false });
      await inlineNotice(telegramWebhookDeleteBtn, "Webhook deleted");
    } catch (err) {
      notify(err?.message || "Failed to delete webhook.", "error");
    } finally {
      stopLoading(telegramWebhookDeleteBtn, telegramWebhookDeleteBtn.dataset.defaultHtml || '<i class="fa-solid fa-link-slash" aria-hidden="true"></i> Delete Webhook');
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
      await inlineNotice(telegramPollStatusBtn, poll.last_error ? "Poll error" : "Status updated", poll.last_error ? "error" : "info");
    } catch (err) {
      notify(err?.message || "Failed to fetch poll status.", "error");
    } finally {
      stopLoading(telegramPollStatusBtn, telegramPollStatusBtn.dataset.defaultHtml || '<i class="fa-solid fa-rotate" aria-hidden="true"></i> Refresh');
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
      await inlineNotice(telegramPollRunOnceBtn, poll.last_error ? "Poll error" : "Poll complete", poll.last_error ? "error" : "success");
    } catch (err) {
      notify(err?.message || "Failed to run poll once.", "error");
    } finally {
      stopLoading(telegramPollRunOnceBtn, telegramPollRunOnceBtn.dataset.defaultHtml || '<i class="fa-solid fa-play" aria-hidden="true"></i> Poll');
    }
  }

  telegramPollStatusBtn?.addEventListener("click", runPollStatus);
  telegramPollRunOnceBtn?.addEventListener("click", runPollOnce);
  backupRunBtns.forEach((btn) => btn.addEventListener("click", runBackupNow));
  backupStatusBtn?.addEventListener("click", runBackupStatus);
  backupHistoryList?.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const deleteBtn = target ? target.closest("[data-backup-delete-id]") : null;
    if (deleteBtn instanceof HTMLButtonElement) {
      event.preventDefault();
      runBackupDelete(deleteBtn, deleteBtn.getAttribute("data-backup-delete-id") || "");
      return;
    }
    const btn = target ? target.closest("[data-backup-restore-id]") : null;
    if (!(btn instanceof HTMLButtonElement)) return;
    event.preventDefault();
    runBackupRestore(btn, btn.getAttribute("data-backup-restore-id") || "");
  });
  backupLocalList?.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const verifyBtn = target ? target.closest("[data-backup-verify-file]") : null;
    if (verifyBtn instanceof HTMLButtonElement) {
      event.preventDefault();
      runBackupVerifyFile(verifyBtn, verifyBtn.getAttribute("data-backup-verify-file") || "");
      return;
    }
    const deleteBtn = target ? target.closest("[data-backup-delete-file]") : null;
    if (deleteBtn instanceof HTMLButtonElement) {
      event.preventDefault();
      runBackupDeleteFile(deleteBtn, deleteBtn.getAttribute("data-backup-delete-file") || "");
      return;
    }
    const btn = target ? target.closest("[data-backup-restore-file]") : null;
    if (!(btn instanceof HTMLButtonElement)) return;
    event.preventDefault();
    runBackupRestoreFile(btn, btn.getAttribute("data-backup-restore-file") || "");
  });

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
  window.addEventListener("admin:settings-target", (event) => {
    const panel = String(event?.detail?.panel || "").trim();
    if (!panel) return;
    focusSectionPanel(panel);
  });

  document.querySelector("[data-backup-scroll-history]")?.addEventListener("click", () => {
    document.getElementById("admin-backup-history")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  initSettingsDialogs();
  initSettingsPageSwitch();
  initRevealAndCopy();
  initPanelEditing();
  initToggleAutosave();
  applyPushProviderVisibility();
  focusRequestedSection();

  if (telegramPollWidget || telegramDeliveryWidget || backupStatusWidget) {
    if (telegramPollWidget) {
      refreshPollHealthSilently();
    }
    if (telegramDeliveryWidget) {
      refreshDeliveryHealthSilently();
    }
    if (backupStatusWidget) {
      refreshBackupStatusSilently();
    }

    livePollTimer = window.setInterval(() => {
      if (telegramPollWidget) refreshPollHealthSilently();
      if (telegramDeliveryWidget) refreshDeliveryHealthSilently();
      if (backupStatusWidget) refreshBackupStatusSilently();
    }, 10000);

    window.addEventListener("beforeunload", () => {
      if (livePollTimer) {
        window.clearInterval(livePollTimer);
        livePollTimer = null;
      }
    });
  }
})();
