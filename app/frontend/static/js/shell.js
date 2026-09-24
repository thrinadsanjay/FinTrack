(function () {
  function csrf() {
    return window.FinTrack ? window.FinTrack.csrfToken() : "";
  }

  var COLLAPSE_KEY = "ft_nav_collapsed";
  var sidebar = document.querySelector("[data-sidebar]");
  var backdrop = document.querySelector("[data-sidebar-backdrop]");
  var toggleBtn = document.querySelector("[data-sidebar-toggle]");
  var tip = null;

  function isDesktop() {
    return window.matchMedia("(min-width: 900px)").matches;
  }

  function setCollapsed(collapsed) {
    document.documentElement.classList.toggle("ft-nav-collapsed", collapsed);
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch (_e) {}
    if (toggleBtn) {
      toggleBtn.setAttribute("aria-label", collapsed ? "Expand navigation" : "Collapse navigation");
      toggleBtn.setAttribute("title", collapsed ? "Expand navigation" : "Collapse navigation");
      toggleBtn.setAttribute("aria-pressed", collapsed ? "true" : "false");
    }
    if (!collapsed) hideNavTip();
  }

  function openDrawer() {
    if (!sidebar) return;
    sidebar.classList.add("is-open");
    if (backdrop) {
      backdrop.hidden = false;
      backdrop.classList.add("is-open");
    }
    document.body.style.overflow = "hidden";
  }

  function closeDrawer() {
    if (!sidebar) return;
    sidebar.classList.remove("is-open");
    if (backdrop) {
      backdrop.classList.remove("is-open");
      backdrop.hidden = true;
    }
    document.body.style.overflow = "";
  }

  try {
    setCollapsed(localStorage.getItem(COLLAPSE_KEY) === "1");
  } catch (_e) {
    setCollapsed(false);
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-sidebar-toggle]")) {
      event.preventDefault();
      if (!isDesktop()) return;
      setCollapsed(!document.documentElement.classList.contains("ft-nav-collapsed"));
      return;
    }

    if (event.target.closest("[data-sidebar-open]")) {
      event.preventDefault();
      openDrawer();
      return;
    }

    if (event.target.closest("[data-sidebar-close], [data-sidebar-backdrop]")) {
      event.preventDefault();
      closeDrawer();
      return;
    }

    var navLink = event.target.closest(".ft-sidebar .ft-nav__link, .ft-sidebar__brand");
    if (navLink && !isDesktop()) {
      if (navLink.matches("[data-nav-group-toggle]")) return;
      closeDrawer();
    }
  });

  window.addEventListener("resize", function () {
    if (isDesktop()) closeDrawer();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeDrawer();
  });

  function closeMenus(except) {
    document.querySelectorAll("[data-profile-menu], [data-notif-panel]").forEach(function (menu) {
      if (except && menu === except) return;
      menu.classList.remove("is-open");
      menu.hidden = true;
    });
    document.querySelectorAll("[data-profile-toggle], [data-notif-toggle]").forEach(function (btn) {
      btn.setAttribute("aria-expanded", "false");
    });
  }

  function toggleMenu(toggle, menu) {
    if (!toggle || !menu) return;
    var willOpen = !menu.classList.contains("is-open");
    closeMenus(willOpen ? menu : null);
    if (willOpen) {
      menu.hidden = false;
      menu.classList.add("is-open");
      toggle.setAttribute("aria-expanded", "true");
    }
  }

  document.addEventListener("click", function (event) {
    var profileToggle = event.target.closest("[data-profile-toggle]");
    if (profileToggle) {
      event.preventDefault();
      toggleMenu(profileToggle, document.querySelector("[data-profile-menu]"));
      return;
    }

    var notifToggle = event.target.closest("[data-notif-toggle]");
    if (notifToggle) {
      event.preventDefault();
      toggleMenu(notifToggle, document.querySelector("[data-notif-panel]"));
      return;
    }

    if (!event.target.closest("[data-profile-menu], [data-notif-panel], [data-profile-toggle], [data-notif-toggle]")) {
      closeMenus();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeMenus();
  });

  async function postNotifications(url, payload) {
    var res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf(),
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      var data = {};
      try {
        data = await res.json();
      } catch (_e) {}
      throw new Error(data.detail || "Failed to update notifications");
    }
  }

  function markItemRead(item) {
    if (!item) return;
    item.classList.remove("is-unread");
    item.setAttribute("data-notif-read", "true");
    var bubble = item.querySelector("[data-notif-mark]");
    if (bubble) bubble.hidden = true;
  }

  function removeItem(item) {
    if (item) item.remove();
  }

  function refreshBadge() {
    var unread = document.querySelectorAll('.ft-notif-item[data-notif-read="false"]').length;
    var visible = document.querySelectorAll(".ft-notif-item").length;
    var toggle = document.querySelector("[data-notif-toggle]");
    var badge = document.querySelector("[data-notif-count]");
    if (!badge && toggle) {
      badge = document.createElement("span");
      badge.className = "ft-notif-count";
      badge.setAttribute("data-notif-count", "");
      toggle.appendChild(badge);
    }
    if (badge) {
      badge.textContent = String(unread);
      badge.classList.toggle("is-zero", unread <= 0);
      badge.hidden = unread <= 0;
    }
    var subtitle = document.querySelector("[data-notif-unread-label]");
    if (subtitle) {
      subtitle.textContent = unread === 1 ? "1 unread" : unread + " unread";
      subtitle.hidden = unread <= 0;
    }
    var markAll = document.querySelector("[data-notif-read-all]");
    if (markAll) markAll.hidden = unread <= 0;
    var archiveAll = document.querySelector("[data-notif-archive-all]");
    if (archiveAll) archiveAll.hidden = visible <= 0;
    var list = document.querySelector("[data-notif-list]");
    var empty = document.querySelector("[data-notif-empty]");
    if (list) list.hidden = visible <= 0;
    if (empty) empty.hidden = visible > 0;
  }

  document.addEventListener("click", async function (event) {
    var markOne = event.target.closest("[data-notif-mark]");
    var markAll = event.target.closest("[data-notif-read-all]");
    var archiveOne = event.target.closest("[data-notif-archive]");
    var archiveAll = event.target.closest("[data-notif-archive-all]");
    if (!markOne && !markAll && !archiveOne && !archiveAll) return;
    event.preventDefault();
    try {
      if (markOne) {
        var item = markOne.closest("[data-notif-id]");
        var id = item ? item.getAttribute("data-notif-id") : "";
        if (!id) return;
        await postNotifications("/notifications/read", { ids: [id] });
        markItemRead(item);
        refreshBadge();
        return;
      }
      if (markAll) {
        await postNotifications("/notifications/read", { all: true });
        document.querySelectorAll(".ft-notif-item").forEach(markItemRead);
        refreshBadge();
        if (window.FinTrack) window.FinTrack.toast("All notifications marked as read", "success");
        return;
      }
      if (archiveOne) {
        var archiveItem = archiveOne.closest("[data-notif-id]");
        var archiveId = archiveItem ? archiveItem.getAttribute("data-notif-id") : "";
        if (!archiveId) return;
        await postNotifications("/notifications/archive", { ids: [archiveId] });
        removeItem(archiveItem);
        refreshBadge();
        return;
      }
      if (archiveAll) {
        await postNotifications("/notifications/archive", { all: true });
        document.querySelectorAll(".ft-notif-item").forEach(removeItem);
        refreshBadge();
        if (window.FinTrack) window.FinTrack.toast("All notifications archived", "success");
      }
    } catch (err) {
      if (window.FinTrack) window.FinTrack.toast(err.message || "Update failed", "error");
    }
  });

  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-nav-group-toggle]");
    if (!toggle) return;

    var group = toggle.closest("[data-nav-group]");
    if (!group) return;

    // Collapsed desktop rail: jump to the section instead of expanding inline.
    if (isDesktop() && document.documentElement.classList.contains("ft-nav-collapsed")) {
      var href = toggle.getAttribute("data-nav-href");
      if (href) {
        event.preventDefault();
        window.location.href = href;
      }
      return;
    }

    var onChevron = event.target.closest(".ft-nav__chevron");
    var hasRoute = Boolean(toggle.getAttribute("data-admin-nav"));

    // Label/icon click on a routed parent: ensure open and let admin_nav route.
    // Chevron click: expand/collapse only.
    if (hasRoute && !onChevron) {
      group.classList.add("is-open");
      toggle.setAttribute("aria-expanded", "true");
      var parentGroup = group.parentElement && group.parentElement.closest("[data-nav-group]");
      if (parentGroup) {
        parentGroup.classList.add("is-open");
        var parentToggle = parentGroup.querySelector(":scope > [data-nav-group-toggle]");
        if (parentToggle) parentToggle.setAttribute("aria-expanded", "true");
      }
      return;
    }

    var willOpen = !group.classList.contains("is-open");
    group.classList.toggle("is-open", willOpen);
    toggle.setAttribute("aria-expanded", willOpen ? "true" : "false");

    if (willOpen) {
      var ancestor = group.parentElement && group.parentElement.closest("[data-nav-group]");
      if (ancestor) {
        ancestor.classList.add("is-open");
        var ancestorToggle = ancestor.querySelector(":scope > [data-nav-group-toggle]");
        if (ancestorToggle) ancestorToggle.setAttribute("aria-expanded", "true");
      }
    }
  });

  tip = document.createElement("div");
  tip.className = "ft-nav-tip";
  tip.hidden = true;
  document.body.appendChild(tip);

  function hideNavTip() {
    if (tip) tip.hidden = true;
  }

  function showNavTip(link) {
    if (!isDesktop() || !document.documentElement.classList.contains("ft-nav-collapsed")) {
      hideNavTip();
      return;
    }
    var label = link.querySelector(".ft-nav__label");
    var name = (label && label.textContent.trim()) || link.getAttribute("data-nav-tip") || "";
    if (!name) return;
    var box = link.getBoundingClientRect();
    tip.textContent = name;
    tip.hidden = false;
    tip.style.top = Math.round(box.top + box.height / 2) + "px";
    tip.style.left = Math.round(box.right + 10) + "px";
  }

  if (sidebar) {
    sidebar.addEventListener("mouseover", function (event) {
      var link = event.target.closest(".ft-nav__link");
      if (link) showNavTip(link);
    });
    sidebar.addEventListener("mouseout", function (event) {
      var link = event.target.closest(".ft-nav__link");
      if (!link) return;
      if (event.relatedTarget && link.contains(event.relatedTarget)) return;
      hideNavTip();
    });
    sidebar.addEventListener("focusin", function (event) {
      var link = event.target.closest(".ft-nav__link");
      if (link) showNavTip(link);
    });
    sidebar.addEventListener("focusout", hideNavTip);
  }
})();
