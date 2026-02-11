// Navbar behaviors: notifications panel and profile menu.

(function navbarInteractions() {
  const toggles = document.querySelectorAll("[data-notif-toggle]");
  const panel = document.querySelector("[data-notif-panel]");
  const readAllBtn = document.querySelector("[data-notif-read-all]");
  const countBadges = document.querySelectorAll(".notif-count");
  const profileToggles = document.querySelectorAll("[data-profile-toggle]");
  const profileMenu = document.querySelector("[data-profile-menu]");
  if (!panel || toggles.length === 0) return;

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

  window.addEventListener("resize", setPanelHeight);
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
})();
