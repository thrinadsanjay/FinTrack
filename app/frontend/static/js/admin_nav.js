(() => {
  const main = document.querySelector("[data-admin-main]");
  if (!main) return;

  const navLinks = Array.from(document.querySelectorAll("[data-admin-nav]"));
  const views = Array.from(document.querySelectorAll("[data-admin-view]"));
  const allowedViews = new Set(views.map((view) => view.dataset.adminView));
  const defaultView = "overview";

  function setView(viewName, pushHash = false) {
    const target = allowedViews.has(viewName) ? viewName : defaultView;

    navLinks.forEach((link) => {
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

    if (pushHash) {
      window.history.pushState(null, "", `#${target}`);
    }
  }

  navLinks.forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      setView(link.dataset.adminNav, true);
    });
  });

  window.addEventListener("hashchange", () => {
    const hashView = window.location.hash.replace("#", "");
    setView(hashView || defaultView, false);
  });

  const initialView = window.location.hash.replace("#", "") || defaultView;
  setView(initialView, false);
})();
