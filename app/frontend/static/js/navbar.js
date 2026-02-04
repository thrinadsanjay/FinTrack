// Navbar behaviors: notifications panel and profile menu.

(function navbarInteractions() {
  const toggles = document.querySelectorAll("[data-notif-toggle]");
  const panel = document.querySelector("[data-notif-panel]");
  const readAllBtn = document.querySelector("[data-notif-read-all]");
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
        await fetch("/notifications/read", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ all: true }),
        });
        closePanel();
        window.location.reload();
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
    const item = e.target.closest("[data-notif-id]");
    if (!item) return;
    const notifId = item.dataset.notifId;
    if (!notifId) return;
    try {
      await fetch("/notifications/read", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: [notifId] }),
      });
      window.location.reload();
    } catch (err) {
      console.error(err);
    }
  });
})();
