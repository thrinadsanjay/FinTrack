(() => {
  const main = document.querySelector("[data-admin-main]");
  if (!main) return;

  const routeLinks = Array.from(document.querySelectorAll("[data-admin-nav]"));
  const sidebarViewLinks = Array.from(document.querySelectorAll(".admin-sidebar [data-admin-nav][data-admin-nav-primary]"));
  const settingsLinks = Array.from(document.querySelectorAll(".admin-sidebar [data-admin-settings-link]"));
  const sidebar = document.querySelector(".admin-sidebar");
  const views = Array.from(document.querySelectorAll("[data-admin-view]"));
  const allowedViews = new Set(views.map((view) => view.dataset.adminView));
  const defaultView = "overview";
  const settingsTargetKey = "ftAdminSettingsTarget";

  function normalizeSettingsTarget(value) {
    const raw = String(value || "").trim();
    if (!raw) return "";
    if (raw === "database") return "application";
    if (["smtp", "telegram"].includes(raw)) return "smtp";
    if (["push", "push_notifications"].includes(raw)) return "push_notifications";
    return raw;
  }

  function setActiveSettingsLink(panelKey) {
    const normalized = normalizeSettingsTarget(panelKey);
    settingsLinks.forEach((link) => {
      const isActive = link.dataset.adminSettingsLink === normalized;
      link.classList.toggle("active", Boolean(isActive));
      if (isActive) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  function setPendingSettingsTarget(value) {
    const normalized = normalizeSettingsTarget(value);
    if (!normalized) {
      window.sessionStorage.removeItem(settingsTargetKey);
      return;
    }
    window.sessionStorage.setItem(settingsTargetKey, normalized);
  }

  function setView(viewName, pushHash = false) {
    const target = allowedViews.has(viewName) ? viewName : defaultView;

    sidebarViewLinks.forEach((link) => {
      const isActive = link.dataset.adminNav === target;
      link.classList.toggle("active", isActive);
      if (isActive) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });

    views.forEach((view) => {
      const isActive = view.dataset.adminView === target;
      view.classList.toggle("active", isActive);
      view.hidden = !isActive;
    });

    if (sidebar) {
      sidebar.classList.toggle("is-settings-view", target === "settings");
    }
    if (target !== "settings") {
      settingsLinks.forEach((link) => {
        link.classList.remove("active");
        link.removeAttribute("aria-current");
      });
    } else if (!settingsLinks.some((link) => link.classList.contains("active"))) {
      setActiveSettingsLink("application");
    }

    if (pushHash) {
      window.history.pushState(null, "", `#${target}`);
    }
  }

  routeLinks.forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const settingsTarget = normalizeSettingsTarget(link.dataset.settingsTarget);
      if (link.dataset.adminNav === "settings" && settingsTarget) {
        setPendingSettingsTarget(settingsTarget);
        setActiveSettingsLink(settingsTarget);
      } else {
        setPendingSettingsTarget("");
      }
      setView(link.dataset.adminNav, true);
      if (link.dataset.adminNav === "settings") {
        window.dispatchEvent(new CustomEvent("admin:settings-target", { detail: { panel: settingsTarget } }));
      }
    });
  });

  window.addEventListener("hashchange", () => {
    const hashView = window.location.hash.replace("#", "");
    setView(hashView || defaultView, false);
  });

  const initialView = window.location.hash.replace("#", "") || defaultView;
  setView(initialView, false);
})();
