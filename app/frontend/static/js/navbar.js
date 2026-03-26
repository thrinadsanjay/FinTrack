// Navbar behaviors: notifications panel and profile menu.

(function navbarInteractions() {
  const toggles = document.querySelectorAll("[data-notif-toggle]");
  const panel = document.querySelector("[data-notif-panel]");
  const readAllBtn = document.querySelector("[data-notif-read-all]");
  const countBadges = document.querySelectorAll(".notif-count");
  const profileToggles = document.querySelectorAll("[data-profile-toggle]");
  const profileMenu = document.querySelector("[data-profile-menu]");
  const telegramOpenLinks = document.querySelectorAll("[data-telegram-open]");
  const telegramModal = document.querySelector("[data-telegram-modal]");
  const telegramCloseBtn = document.querySelector("[data-telegram-close]");
  const telegramMobileInput = document.querySelector("[data-telegram-mobile]");
  const telegramOtpInput = document.querySelector("[data-telegram-otp]");
  const telegramSendBtn = document.querySelector("[data-telegram-send-otp]");
  const telegramVerifyBtn = document.querySelector("[data-telegram-verify-otp]");
  const telegramOtpWrap = document.querySelector("[data-telegram-otp-wrap]");
  const telegramVerifyWrap = document.querySelector("[data-telegram-verify-wrap]");
  const telegramBotName = document.querySelector("[data-telegram-bot-name]");
  const telegramStartHelp = document.querySelector("[data-telegram-start-help]");
  const telegramOpenBotLink = document.querySelector("[data-telegram-open-bot]");
  const telegramChangeModal = document.querySelector("[data-telegram-change-modal]");
  const telegramChangeUser = document.querySelector("[data-telegram-change-user]");
  const telegramChangeUserRow = document.querySelector("[data-telegram-change-user-row]");
  const telegramChangeMobile = document.querySelector("[data-telegram-change-mobile]");
  const telegramChangeYes = document.querySelector("[data-telegram-change-yes]");
  const telegramChangeDeregister = document.querySelector("[data-telegram-change-deregister]");
  const telegramChangeNo = document.querySelector("[data-telegram-change-no]");
  let telegramChangePendingOpen = false;
  const seenKey = "ft_seen_notif_ids_v1";
  const maxSeenIds = 400;
  const flyoutDurationMs = 7000;
  const flyoutFadeMs = 520;
  if (!panel || toggles.length === 0) return;

  if (telegramOtpWrap) telegramOtpWrap.classList.add("hidden");
  if (telegramVerifyWrap) telegramVerifyWrap.classList.add("hidden");
  if (telegramOtpInput) telegramOtpInput.value = "";
  if (telegramSendBtn) telegramSendBtn.textContent = "Register";

  const flyoutHost = document.createElement("div");
  flyoutHost.className = "notif-flyout-host";
  flyoutHost.setAttribute("aria-live", "polite");
  flyoutHost.setAttribute("aria-atomic", "false");
  document.body.appendChild(flyoutHost);

  let audioContext = null;

  function getAudioContext() {
    if (!("AudioContext" in window || "webkitAudioContext" in window)) return null;
    if (!audioContext) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      audioContext = new Ctx();
    }
    return audioContext;
  }

  function primeAudioContext() {
    const ctx = getAudioContext();
    if (!ctx || ctx.state === "running") return;
    ctx.resume().catch(() => {});
  }

  function playNotificationSound() {
    const ctx = getAudioContext();
    if (!ctx || ctx.state !== "running") return;

    const t0 = ctx.currentTime;
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.0001, t0);
    gain.gain.exponentialRampToValueAtTime(0.08, t0 + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.34);
    gain.connect(ctx.destination);

    const toneA = ctx.createOscillator();
    toneA.type = "sine";
    toneA.frequency.setValueAtTime(880, t0);
    toneA.connect(gain);
    toneA.start(t0);
    toneA.stop(t0 + 0.16);

    const toneB = ctx.createOscillator();
    toneB.type = "triangle";
    toneB.frequency.setValueAtTime(1320, t0 + 0.12);
    toneB.connect(gain);
    toneB.start(t0 + 0.12);
    toneB.stop(t0 + 0.34);
  }

  function getVisibleBellButton() {
    const buttons = Array.from(toggles);
    const visible = buttons.find((btn) => {
      const rect = btn.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    });
    return visible || buttons[0] || null;
  }

  function placeFlyoutHost() {
    const bell = getVisibleBellButton();
    if (!bell) return;
    const rect = bell.getBoundingClientRect();
    const width = Math.min(320, Math.max(240, window.innerWidth - 16));
    const left = Math.min(
      Math.max(8, rect.right - width),
      Math.max(8, window.innerWidth - width - 8)
    );
    flyoutHost.style.width = `${width}px`;
    flyoutHost.style.left = `${Math.round(left)}px`;
    flyoutHost.style.top = `${Math.round(rect.bottom + 8)}px`;
  }

  function getTypeFromItem(item) {
    const className = Array.from(item.classList).find(
      (name) => name.startsWith("notif-") && name !== "notif-item" && name !== "notif-unread"
    );
    return className ? className.replace("notif-", "") : "info";
  }

  function addFlyoutItem({ title, message, type, timeText }) {
    const item = document.createElement("div");
    item.className = `notif-flyout-item notif-flyout-${type}`;

    const dot = document.createElement("span");
    dot.className = "notif-flyout-dot";

    const body = document.createElement("div");
    body.className = "notif-flyout-body";

    const titleEl = document.createElement("div");
    titleEl.className = "notif-flyout-title";
    titleEl.textContent = title || "Notification";

    const messageEl = document.createElement("div");
    messageEl.className = "notif-flyout-message";
    messageEl.textContent = message || "";

    const timeEl = document.createElement("div");
    timeEl.className = "notif-flyout-time";
    timeEl.textContent = timeText || "";

    body.appendChild(titleEl);
    body.appendChild(messageEl);
    if (timeText) body.appendChild(timeEl);
    item.appendChild(dot);
    item.appendChild(body);
    flyoutHost.appendChild(item);

    requestAnimationFrame(() => item.classList.add("show"));
    setTimeout(() => item.classList.add("hide"), flyoutDurationMs - flyoutFadeMs);
    setTimeout(() => item.remove(), flyoutDurationMs + 120);
  }

  function readSeenIds() {
    try {
      const raw = localStorage.getItem(seenKey);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return null;
      return new Set(parsed.map((v) => String(v)));
    } catch (error) {
      return null;
    }
  }

  function writeSeenIds(ids) {
    try {
      const values = Array.from(ids).slice(0, maxSeenIds);
      localStorage.setItem(seenKey, JSON.stringify(values));
    } catch (error) {
      // Ignore storage failures.
    }
  }

  function handleFreshNotifications() {
    const notifItems = Array.from(panel.querySelectorAll("[data-notif-id]"));
    if (!notifItems.length) return;

    const currentIds = notifItems.map((item) => String(item.dataset.notifId || "")).filter(Boolean);
    if (!currentIds.length) return;

    const seenIds = readSeenIds();
    if (!seenIds) {
      writeSeenIds(new Set(currentIds));
      return;
    }

    const freshItems = notifItems.filter((item) => !seenIds.has(String(item.dataset.notifId || "")));
    if (!freshItems.length) {
      writeSeenIds(new Set([...currentIds, ...seenIds]));
      return;
    }

    placeFlyoutHost();
    playNotificationSound();

    freshItems.slice(0, 3).forEach((item, index) => {
      const title = (item.querySelector(".notif-title")?.textContent || "").trim();
      const message = (item.querySelector(".notif-message")?.textContent || "").trim();
      const timeText = (item.querySelector(".notif-time")?.textContent || "").trim();
      const type = getTypeFromItem(item);
      setTimeout(() => {
        placeFlyoutHost();
        addFlyoutItem({ title, message, type, timeText });
      }, index * 420);
    });

    writeSeenIds(new Set([...currentIds, ...seenIds]));
  }

  function closePanel() {
    panel.classList.remove("open");
    toggles.forEach((t) => t.setAttribute("aria-expanded", "false"));
  }

  function closeProfile() {
    if (!profileMenu) return;
    profileMenu.classList.remove("open");
    profileToggles.forEach((t) => t.setAttribute("aria-expanded", "false"));
  }

  function openTelegramModal({ botUsername = "" } = {}) {
    if (!telegramModal) return;
    if (telegramBotName) {
      const normalized = String(botUsername || "").trim().replace(/^@+/, "");
      telegramBotName.textContent = normalized ? `@${normalized}` : "@your_bot_name";
    }
    if (telegramStartHelp) {
      telegramStartHelp.classList.add("hidden");
    }
    if (telegramOpenBotLink) {
      telegramOpenBotLink.setAttribute("href", "#");
    }
    if (telegramSendBtn) {
      telegramSendBtn.textContent = "Register";
    }
    if (telegramOtpWrap) telegramOtpWrap.classList.add("hidden");
    if (telegramVerifyWrap) telegramVerifyWrap.classList.add("hidden");
    if (telegramOtpInput) telegramOtpInput.value = "";
    telegramModal.classList.remove("hidden");
    window.FTPhoneInput?.syncVisibleFromHidden?.(telegramModal);
    const telegramLocalInput = telegramModal.querySelector("[data-phone-local]");
    if (telegramLocalInput) telegramLocalInput.focus();
  }

  function closeTelegramModal() {
    if (!telegramModal) return;
    telegramModal.classList.add("hidden");
    if (telegramOtpInput) telegramOtpInput.value = "";
    if (telegramOtpWrap) telegramOtpWrap.classList.add("hidden");
    if (telegramVerifyWrap) telegramVerifyWrap.classList.add("hidden");
    if (telegramSendBtn) telegramSendBtn.textContent = "Register";
  }

  function openTelegramChangeModal({ username, mobile }) {
    if (!telegramChangeModal) return;
    if (telegramChangeUser && telegramChangeUserRow) {
      if (username) {
        telegramChangeUser.textContent = `@${username}`;
        telegramChangeUserRow.style.display = "";
      } else {
        telegramChangeUser.textContent = "";
        telegramChangeUserRow.style.display = "none";
      }
    }
    if (telegramChangeMobile) {
      telegramChangeMobile.textContent = mobile || "-";
    }
    telegramChangeModal.classList.remove("hidden");
  }

  function closeTelegramChangeModal() {
    if (!telegramChangeModal) return;
    telegramChangeModal.classList.add("hidden");
  }

  function notify(message, kind) {
    if (typeof window.ftNotify === "function") {
      window.ftNotify(message, kind || "info");
      return;
    }
    window.alert(message);
  }

  function setLoading(btn, loading, label) {
    if (!btn) return;
    if (loading) {
      btn.dataset.prevLabel = btn.textContent || label || "";
      btn.textContent = label || btn.textContent;
      btn.classList.add("is-loading");
      btn.disabled = true;
      return;
    }
    btn.classList.remove("is-loading");
    btn.disabled = false;
    btn.textContent = btn.dataset.prevLabel || btn.textContent;
  }

  function setTelegramRegistrationState({ registered, mobile = "", username = "" }) {
    telegramOpenLinks.forEach((link) => {
      link.dataset.telegramRegistered = registered ? "true" : "false";
      link.dataset.telegramMobile = mobile;
      link.dataset.telegramUsername = username;
      link.classList.remove("registered", "unregistered");
      link.classList.add(registered ? "registered" : "unregistered");
    });
  }

  function setPanelHeight() {
    const count = parseInt(panel.dataset.count || "0", 10);
    const base = 140;
    const perItem = 72;
    const max = Math.floor(window.innerHeight * 0.5);
    const target = Math.min(Math.max(base, base + count * perItem), max);
    panel.style.setProperty("--notif-max", `${target}px`);
  }

  function updateUnreadState() {
    const unreadItems = panel.querySelectorAll('[data-notif-read="false"]');
    const unreadCount = unreadItems.length;

    if (readAllBtn) {
      readAllBtn.style.display = unreadCount > 0 ? "inline-block" : "none";
    }

    countBadges.forEach((badge) => {
      if (unreadCount > 0) {
        badge.textContent = String(unreadCount);
      } else {
        badge.remove();
      }
    });
  }

  async function markRead(payload) {
    const csrf = document
      .querySelector('meta[name="csrf-token"]')
      ?.getAttribute("content");
    const res = await fetch("/notifications/read", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf || "",
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      throw new Error("Failed to mark notification as read");
    }
  }

  toggles.forEach((toggle) => {
    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      closeProfile();
      setPanelHeight();
      const isOpen = panel.classList.toggle("open");
      toggles.forEach((t) => t.setAttribute("aria-expanded", String(isOpen)));
    });
  });

  profileToggles.forEach((toggle) => {
    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      closePanel();
      if (!profileMenu) return;
      const isOpen = profileMenu.classList.toggle("open");
      profileToggles.forEach((t) => t.setAttribute("aria-expanded", String(isOpen)));
    });
  });

  if (readAllBtn) {
    readAllBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      try {
        await markRead({ all: true });
        panel.querySelectorAll("[data-notif-id]").forEach((item) => {
          item.dataset.notifRead = "true";
          item.classList.remove("notif-unread");
        });
        panel.querySelectorAll("[data-notif-mark]").forEach((btn) => btn.remove());
        updateUnreadState();
      } catch (err) {
        console.error(err);
      }
    });
  }

  telegramOpenLinks.forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      closeProfile();
      const isEnabled = String(link.dataset.telegramEnabled || "").toLowerCase() === "true";
      if (!isEnabled) {
        notify("Telegram integration is currently disabled by admin.", "info");
        return;
      }
      const botUsername = String(link.dataset.telegramBotUsername || "").trim();
      const isRegistered = String(link.dataset.telegramRegistered || "").toLowerCase() === "true";
      if (isRegistered) {
        const username = String(link.dataset.telegramUsername || "").trim();
        const mobile = String(link.dataset.telegramMobile || "-").trim() || "-";
        telegramChangePendingOpen = true;
        openTelegramChangeModal({ username, mobile });
        return;
      }
      openTelegramModal({ botUsername });
    });
  });

  if (telegramChangeYes) {
    telegramChangeYes.addEventListener("click", () => {
      closeTelegramChangeModal();
      if (telegramChangePendingOpen) {
        const enabledLink = Array.from(telegramOpenLinks).find(
          (link) => String(link.dataset.telegramEnabled || "").toLowerCase() === "true"
        );
        const botUsername = String(enabledLink?.dataset.telegramBotUsername || "").trim();
        telegramChangePendingOpen = false;
        openTelegramModal({ botUsername });
      }
    });
  }

  if (telegramChangeNo) {
    telegramChangeNo.addEventListener("click", () => {
      telegramChangePendingOpen = false;
      closeTelegramChangeModal();
      closeTelegramModal();
    });
  }

  if (telegramChangeDeregister) {
    telegramChangeDeregister.addEventListener("click", async () => {
      if (telegramOtpInput) telegramOtpInput.value = "";
      if (telegramOtpWrap) telegramOtpWrap.classList.add("hidden");
      if (telegramVerifyWrap) telegramVerifyWrap.classList.add("hidden");
      const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
      setLoading(telegramChangeDeregister, true, "Removing...");
      try {
        const res = await fetch("/profile/telegram/deregister", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
          },
          body: JSON.stringify({}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.detail || "Failed to deregister Telegram.");
        }
        setTelegramRegistrationState({ registered: false });
        notify("Telegram deregistered successfully.", "success");
        telegramChangePendingOpen = false;
        closeTelegramChangeModal();
        closeTelegramModal();
      } catch (error) {
        notify(error?.message || "Failed to deregister Telegram.", "error");
      } finally {
        setLoading(telegramChangeDeregister, false);
      }
    });
  }

  if (telegramChangeModal) {
    telegramChangeModal.addEventListener("click", (e) => {
      if (e.target === telegramChangeModal) {
        telegramChangePendingOpen = false;
        closeTelegramChangeModal();
      }
    });
  }

  if (telegramCloseBtn) {
    telegramCloseBtn.addEventListener("click", () => closeTelegramModal());
  }

  if (telegramModal) {
    telegramModal.addEventListener("click", (e) => {
      if (e.target === telegramModal) closeTelegramModal();
    });
  }

  if (telegramSendBtn) {
    telegramSendBtn.addEventListener("click", async () => {
      window.FTPhoneInput?.syncHiddenValue?.(telegramModal);
      const mobile = (telegramMobileInput?.value || "").trim();
      const countryCode = (telegramModal?.querySelector("[data-phone-code]")?.value || "").trim();
      const mobileLocal = (telegramModal?.querySelector("[data-phone-local]")?.value || "").trim();
      if (!mobile && !mobileLocal) {
        notify("Mobile number is required.", "error");
        telegramModal?.querySelector("[data-phone-local]")?.focus();
        return;
      }
      if (telegramOtpInput) telegramOtpInput.value = "";
      if (telegramOtpWrap) telegramOtpWrap.classList.add("hidden");
      if (telegramVerifyWrap) telegramVerifyWrap.classList.add("hidden");
      const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
      setLoading(telegramSendBtn, true, "Processing...");
      try {
        const res = await fetch("/profile/telegram/send-otp", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
          },
          body: JSON.stringify({
            mobile,
            country_code: countryCode,
            mobile_local: mobileLocal,
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!(res.ok || res.status === 202)) {
          throw new Error(data.detail || "Failed to send OTP.");
        }
        if (data.status === "awaiting_register") {
          if (telegramStartHelp) {
            telegramStartHelp.classList.remove("hidden");
          }
          if (telegramOpenBotLink && data.bot_url) {
            telegramOpenBotLink.setAttribute("href", String(data.bot_url));
          }
          if (telegramOtpWrap) telegramOtpWrap.classList.add("hidden");
          if (telegramVerifyWrap) telegramVerifyWrap.classList.add("hidden");
          if (telegramOtpInput) telegramOtpInput.value = "";
          if (telegramSendBtn) telegramSendBtn.textContent = "Send OTP";
          notify(
            data.detail ||
              "Send /register in Telegram bot, then click Send OTP.",
            "info"
          );
        } else {
          if (telegramStartHelp) {
            telegramStartHelp.classList.add("hidden");
          }
          if (telegramOtpWrap) telegramOtpWrap.classList.remove("hidden");
          if (telegramVerifyWrap) telegramVerifyWrap.classList.remove("hidden");
          if (telegramOtpInput) telegramOtpInput.value = "";
          notify("OTP sent to your Telegram successfully.", "success");
          telegramOtpInput?.focus();
        }
      } catch (error) {
        notify(error?.message || "Failed to send OTP.", "error");
      } finally {
        setLoading(telegramSendBtn, false);
      }
    });
  }

  if (telegramVerifyBtn) {
    telegramVerifyBtn.addEventListener("click", async () => {
      window.FTPhoneInput?.syncHiddenValue?.(telegramModal);
      const otp = (telegramOtpInput?.value || "").trim();
      if (!otp) {
        notify("OTP is required.", "error");
        telegramOtpInput?.focus();
        return;
      }
      const countryCode = (telegramModal?.querySelector("[data-phone-code]")?.value || "").trim();
      const mobileLocal = (telegramModal?.querySelector("[data-phone-local]")?.value || "").trim();
      const mobile = (telegramMobileInput?.value || "").trim();
      const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
      setLoading(telegramVerifyBtn, true, "Verifying...");
      try {
        const res = await fetch("/profile/telegram/verify-otp", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
          },
          body: JSON.stringify({ otp, mobile, country_code: countryCode, mobile_local: mobileLocal }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.detail || "OTP verification failed.");
        }
        setTelegramRegistrationState({
          registered: true,
          mobile: data.telegram_mobile || (telegramMobileInput?.value || "").trim(),
          username: data.telegram_username || "",
        });
        notify("Telegram registered successfully.", "success");
        closeTelegramModal();
      } catch (error) {
        notify(error?.message || "OTP verification failed.", "error");
      } finally {
        setLoading(telegramVerifyBtn, false);
      }
    });
  }

  window.addEventListener("resize", () => {
    setPanelHeight();
    placeFlyoutHost();
  });
  document.addEventListener("pointerdown", primeAudioContext, { once: true, passive: true });
  document.addEventListener("keydown", primeAudioContext, { once: true });
  document.addEventListener("click", () => {
    closePanel();
    closeProfile();
  });
  panel.addEventListener("click", async (e) => {
    e.stopPropagation();
    const markBtn = e.target.closest("[data-notif-mark]");
    if (!markBtn) return;

    const item = markBtn.closest("[data-notif-id]");
    if (!item || item.dataset.notifRead === "true") return;

    const notifId = item.dataset.notifId;
    if (!notifId) return;
    try {
      await markRead({ ids: [notifId] });
      item.dataset.notifRead = "true";
      item.classList.remove("notif-unread");
      markBtn.remove();
      updateUnreadState();
    } catch (err) {
      console.error(err);
    }

    return;
  });

  panel.addEventListener("click", async (e) => {
    const item = e.target.closest("[data-notif-id]");
    if (!item || e.target.closest("[data-notif-mark]")) return;
    const key = String(item.dataset.notifKey || "");
    if (!key.startsWith("support_reply:")) return;

    const notifId = item.dataset.notifId;
    if (notifId && item.dataset.notifRead !== "true") {
      try {
        await markRead({ ids: [notifId] });
        item.dataset.notifRead = "true";
        item.classList.remove("notif-unread");
        const markButton = item.querySelector("[data-notif-mark]");
        if (markButton) markButton.remove();
        updateUnreadState();
      } catch (err) {
        console.error(err);
      }
    }

    window.location.href = "/help-support#support-chat";
  });

  updateUnreadState();
  handleFreshNotifications();
  placeFlyoutHost();
})();
