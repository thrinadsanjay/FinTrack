// Navbar behaviors: notifications panel and profile menu.

(function navbarInteractions() {
  const toggles = document.querySelectorAll("[data-notif-toggle]");
  const panel = document.querySelector("[data-notif-panel]");
  const readAllBtn = document.querySelector("[data-notif-read-all]");
  const countBadges = document.querySelectorAll(".notif-count");
  const profileToggles = document.querySelectorAll("[data-profile-toggle]");
  const profileMenu = document.querySelector("[data-profile-menu]");
  const seenKey = "ft_seen_notif_ids_v1";
  const maxSeenIds = 400;
  const flyoutDurationMs = 7000;
  const flyoutFadeMs = 520;
  if (!panel || toggles.length === 0) return;

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
    const res = await fetch("/notifications/read", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
  });

  updateUnreadState();
  handleFreshNotifications();
  placeFlyoutHost();
})();
