(() => {
  const main = document.querySelector("[data-admin-main]");
  if (!main) return;

  const shell = document.querySelector("[data-admin-shell]");
  const routeLinks = Array.from(document.querySelectorAll("[data-admin-nav]"));
  const primaryLinks = Array.from(
    document.querySelectorAll("[data-admin-nav][data-admin-nav-primary]")
  );
  const settingsLinks = Array.from(document.querySelectorAll("[data-admin-settings-link]"));
  const adminRoot = document.querySelector("[data-admin-nav-root]");
  const views = Array.from(document.querySelectorAll("[data-admin-view]"));
  const allowedViews = new Set(views.map((view) => view.dataset.adminView));
  const defaultView = "overview";
  const settingsTargetKey = "ftAdminSettingsTarget";

  function normalizeSettingsTarget(value) {
    const raw = String(value || "").trim();
    if (!raw) return "";
    if (raw === "backup" || raw === "database" || raw === "runtime") return "application";
    if (raw === "telegram" || raw === "smtp" || raw === "push" || raw === "push_notifications" || raw === "authentication") return "messaging";
    return raw;
  }

  function setActiveSettingsLink(panelKey) {
    const normalized = normalizeSettingsTarget(panelKey);
    settingsLinks.forEach((link) => {
      const isActive = link.dataset.adminSettingsLink === normalized;
      link.classList.toggle("is-active", Boolean(isActive));
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

  function syncSidebarGroups(target) {
    if (adminRoot) {
      adminRoot.classList.add("is-open");
      const rootToggle = adminRoot.querySelector(":scope > [data-nav-group-toggle]");
      if (rootToggle) rootToggle.setAttribute("aria-expanded", "true");
    }
  }

  function setView(viewName, pushHash = false) {
    const target = allowedViews.has(viewName) ? viewName : defaultView;

    primaryLinks.forEach((link) => {
      const isActive = link.dataset.adminNav === target;
      link.classList.toggle("is-active", isActive);
      link.classList.toggle("active", isActive);
      if (isActive) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });

    views.forEach((view) => {
      const isActive = view.dataset.adminView === target;
      view.classList.toggle("active", isActive);
      view.hidden = !isActive;
    });

    if (shell) {
      shell.classList.toggle("is-settings-view", target === "settings");
    }

    syncSidebarGroups(target);

    if (target !== "settings") {
      settingsLinks.forEach((link) => {
        link.classList.remove("is-active", "active");
        link.removeAttribute("aria-current");
      });
    } else if (!settingsLinks.some((link) => link.classList.contains("is-active") || link.classList.contains("active"))) {
      setActiveSettingsLink("application");
    }

    if (pushHash) {
      window.history.pushState(null, "", `#${target}`);
    }
  }

  routeLinks.forEach((link) => {
    link.addEventListener("click", (event) => {
      // Only intercept when already on the admin page.
      event.preventDefault();
      const rawTarget = String(link.dataset.settingsTarget || "").trim();
      const settingsTarget = normalizeSettingsTarget(rawTarget);
      if (link.dataset.adminNav === "settings") {
        setPendingSettingsTarget(rawTarget || "application");
        setActiveSettingsLink(settingsTarget || "application");
      } else {
        setPendingSettingsTarget("");
      }
      setView(link.dataset.adminNav, true);
      if (link.dataset.adminNav === "settings") {
        window.dispatchEvent(
          new CustomEvent("admin:settings-target", {
            detail: { panel: rawTarget || "application" },
          })
        );
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
