(function () {
  var root = document.querySelector("[data-tx-board]");
  if (!root) return;

  var openPanel = null;
  var openToggle = null;
  var ignoreDocClick = false;
  var infoAnchor = null;
  var infoHideTimer = null;
  var editDialog = document.querySelector("[data-tx-edit-dialog]");
  var emiDialog = document.querySelector("[data-tx-emi-dialog]");

  var infoPop = document.createElement("div");
  infoPop.className = "txb-info-pop";
  infoPop.hidden = true;
  infoPop.setAttribute("role", "tooltip");
  document.body.appendChild(infoPop);

  function clearInfoHideTimer() {
    if (infoHideTimer) {
      clearTimeout(infoHideTimer);
      infoHideTimer = null;
    }
  }

  function closeInfo() {
    clearInfoHideTimer();
    infoPop.hidden = true;
    infoPop.textContent = "";
    infoAnchor = null;
  }

  function scheduleCloseInfo() {
    clearInfoHideTimer();
    infoHideTimer = setTimeout(function () {
      closeInfo();
    }, 140);
  }

  function closeMenu() {
    if (!openPanel) return;
    openPanel.hidden = true;
    openPanel.classList.remove("is-open");
    if (openToggle) openToggle.setAttribute("aria-expanded", "false");
    openPanel = null;
    openToggle = null;
  }

  function placeBeside(el, anchor) {
    var rect = anchor.getBoundingClientRect();
    var gap = 8;
    var pad = 8;
    // Force layout so width/height are real before placement
    el.style.visibility = "hidden";
    el.hidden = false;
    var width = Math.min(el.offsetWidth || 240, window.innerWidth - pad * 2);
    var height = el.offsetHeight || 120;

    var left = rect.right + gap;
    if (left + width > window.innerWidth - pad) {
      left = rect.left - width - gap;
    }
    left = Math.min(Math.max(pad, left), window.innerWidth - width - pad);

    var top = rect.top + rect.height / 2 - height / 2;
    top = Math.min(Math.max(pad, top), window.innerHeight - height - pad);

    el.style.top = Math.round(top) + "px";
    el.style.left = Math.round(left) + "px";
    el.style.visibility = "";
  }

  function placeFixed(el, anchor, preferUp) {
    var rect = anchor.getBoundingClientRect();
    var width = Math.min(el.offsetWidth || 200, window.innerWidth - 16);
    var height = el.offsetHeight || 160;
    var left = Math.min(Math.max(8, rect.right - width), window.innerWidth - width - 8);
    var top = preferUp ? rect.top - height - 6 : rect.bottom + 6;
    if (!preferUp && top + height > window.innerHeight - 8) {
      top = Math.max(8, rect.top - height - 6);
    }
    if (preferUp && top < 8) {
      top = Math.min(window.innerHeight - height - 8, rect.bottom + 6);
    }
    el.style.top = Math.round(top) + "px";
    el.style.left = Math.round(left) + "px";
  }

  function openMenu(toggle) {
    var menu = toggle.closest(".txb-menu");
    var panel = menu && menu.querySelector("[data-tx-menu-panel]");
    if (!panel) return;
    if (openPanel === panel) {
      closeMenu();
      return;
    }
    closeMenu();
    closeInfo();
    if (panel.parentElement !== document.body) document.body.appendChild(panel);
    panel.hidden = false;
    panel.classList.add("is-open");
    placeFixed(panel, toggle, false);
    toggle.setAttribute("aria-expanded", "true");
    openPanel = panel;
    openToggle = toggle;
    ignoreDocClick = true;
    setTimeout(function () {
      ignoreDocClick = false;
    }, 0);
  }

  function openInfo(btn) {
    if (!btn) return;
    clearInfoHideTimer();
    closeMenu();
    var text = btn.getAttribute("data-info") || "";
    if (!text) return;
    infoAnchor = btn;
    infoPop.textContent = text;
    placeBeside(infoPop, btn);
  }

  function openEditFromBtn(editBtn) {
    if (!editDialog || !editBtn) return;
    closeMenu();
    closeInfo();
    editDialog.querySelector("[data-edit-id]").value = editBtn.getAttribute("data-id") || "";
    editDialog.querySelector("[data-edit-account]").value = editBtn.getAttribute("data-account-id") || "";
    editDialog.querySelector("[data-edit-amount]").value = editBtn.getAttribute("data-amount") || "";
    editDialog.querySelector("[data-edit-description]").value = editBtn.getAttribute("data-description") || "";
    editDialog.querySelector("[data-edit-category]").value = editBtn.getAttribute("data-category-code") || "";
    editDialog.querySelector("[data-edit-subcategory]").value = editBtn.getAttribute("data-subcategory-code") || "";
    editDialog.showModal();
  }

  root.addEventListener("pointerover", function (event) {
    var infoBtn = event.target.closest("[data-tx-info]");
    if (!infoBtn || !root.contains(infoBtn)) return;
    openInfo(infoBtn);
  });

  root.addEventListener("pointerout", function (event) {
    var infoBtn = event.target.closest("[data-tx-info]");
    if (!infoBtn) return;
    var related = event.relatedTarget;
    if (related && (infoBtn.contains(related) || infoPop.contains(related))) return;
    scheduleCloseInfo();
  });

  infoPop.addEventListener("pointerenter", function () {
    clearInfoHideTimer();
  });

  infoPop.addEventListener("pointerleave", function () {
    scheduleCloseInfo();
  });

  root.addEventListener("focusin", function (event) {
    var infoBtn = event.target.closest("[data-tx-info]");
    if (infoBtn) openInfo(infoBtn);
  });

  root.addEventListener("focusout", function (event) {
    var infoBtn = event.target.closest("[data-tx-info]");
    if (!infoBtn) return;
    var related = event.relatedTarget;
    if (related && (infoBtn.contains(related) || infoPop.contains(related))) return;
    scheduleCloseInfo();
  });

  root.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-tx-menu-toggle]");
    if (toggle) {
      event.preventDefault();
      event.stopPropagation();
      openMenu(toggle);
      return;
    }

    var infoBtn = event.target.closest("[data-tx-info]");
    if (infoBtn) {
      event.preventDefault();
      event.stopPropagation();
      openInfo(infoBtn);
      return;
    }

    var editBtn = event.target.closest("[data-tx-edit]");
    if (editBtn) {
      event.preventDefault();
      event.stopPropagation();
      openEditFromBtn(editBtn);
      return;
    }

    var emiBtn = event.target.closest("[data-tx-emi]");
    if (emiBtn && emiDialog) {
      event.preventDefault();
      event.stopPropagation();
      closeMenu();
      closeInfo();
      emiDialog.querySelector("[data-emi-id]").value = emiBtn.getAttribute("data-id") || "";
      emiDialog.querySelector("[data-emi-title]").value = emiBtn.getAttribute("data-description") || "EMI";
      var hint = emiDialog.querySelector("[data-emi-hint]");
      if (hint) {
        hint.textContent =
          "Convert ₹ " + (emiBtn.getAttribute("data-amount") || "") + " into an EMI plan on this credit card spend.";
      }
      emiDialog.showModal();
      return;
    }

    // Card click opens edit when available
    var card = event.target.closest("[data-tx-card]");
    if (card && !event.target.closest(".txb-card__side, form, a, button")) {
      var edit = card.querySelector("[data-tx-edit]");
      if (edit) openEditFromBtn(edit);
    }
  });

  document.addEventListener("click", function (event) {
    if (ignoreDocClick) return;

    var editBtn = event.target.closest("[data-tx-edit]");
    if (editBtn && editBtn.closest("[data-tx-menu-panel]")) {
      event.preventDefault();
      openEditFromBtn(editBtn);
      return;
    }

    var emiBtn = event.target.closest("[data-tx-emi]");
    if (emiBtn && emiDialog && emiBtn.closest("[data-tx-menu-panel]")) {
      event.preventDefault();
      closeMenu();
      closeInfo();
      emiDialog.querySelector("[data-emi-id]").value = emiBtn.getAttribute("data-id") || "";
      emiDialog.querySelector("[data-emi-title]").value = emiBtn.getAttribute("data-description") || "EMI";
      var hint = emiDialog.querySelector("[data-emi-hint]");
      if (hint) {
        hint.textContent =
          "Convert ₹ " + (emiBtn.getAttribute("data-amount") || "") + " into an EMI plan on this credit card spend.";
      }
      emiDialog.showModal();
      return;
    }

    if (event.target.closest("[data-tx-menu-toggle], [data-tx-menu-panel], [data-tx-info], .txb-info-pop")) {
      return;
    }
    closeMenu();
    closeInfo();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeMenu();
      closeInfo();
    }
  });

  window.addEventListener(
    "scroll",
    function () {
      if (openPanel && openToggle) placeFixed(openPanel, openToggle, false);
      if (!infoPop.hidden && infoAnchor) placeBeside(infoPop, infoAnchor);
    },
    { capture: true, passive: true }
  );

  window.addEventListener("resize", function () {
    closeMenu();
    closeInfo();
  });

  document.querySelectorAll("[data-dialog-close]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var dialog = btn.closest("dialog");
      if (dialog) dialog.close();
    });
  });

  var drawer = document.querySelector("[data-add-drawer]");
  var tabs = root.querySelectorAll("[data-tx-tab]");

  function openAddDrawer() {
    if (!drawer) return;
    closeTxaMenus();
    drawer.hidden = false;
    document.body.style.overflow = "hidden";
  }

  function closeAddDrawer() {
    if (!drawer) return;
    drawer.hidden = true;
    document.body.style.overflow = "";
    if (window.history && window.history.replaceState && /[?&]add=1/.test(location.search)) {
      var next = new URL(location.href);
      next.searchParams.delete("add");
      window.history.replaceState({}, "", next.pathname + next.search);
    }
  }

  function filterType(type) {
    tabs.forEach(function (tab) {
      var active = tab.getAttribute("data-tx-tab") === type;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
    root.querySelectorAll("[data-tx-row]").forEach(function (row) {
      row.hidden = type !== "all" && row.getAttribute("data-type") !== type;
    });
    root.querySelectorAll("[data-tx-group]").forEach(function (head) {
      var key = head.getAttribute("data-tx-group");
      var visible = root.querySelector('[data-tx-row][data-group="' + key + '"]:not([hidden])');
      head.hidden = !visible;
    });
  }

  root.querySelectorAll("button[data-open-add]").forEach(function (btn) {
    btn.addEventListener("click", openAddDrawer);
  });
  document.querySelectorAll("[data-close-add]").forEach(function (btn) {
    btn.addEventListener("click", closeAddDrawer);
  });
  if (drawer) {
    drawer.addEventListener("click", function (event) {
      if (event.target === drawer) closeAddDrawer();
    });
  }
  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      filterType(tab.getAttribute("data-tx-tab"));
    });
  });

  function parkTxaMenu(panel) {
    if (!panel) return;
    panel.classList.remove("is-floating");
    var home = document.querySelector('[data-menu-home="' + panel.getAttribute("data-menu-id") + '"]');
    if (home && panel.parentElement !== home) home.appendChild(panel);
  }

  function closeTxaMenus(except) {
    root.querySelectorAll(".txa-menu[open]").forEach(function (menu) {
      if (menu !== except) menu.removeAttribute("open");
    });
    document.querySelectorAll(".txa-menu__panel.is-floating").forEach(function (panel) {
      var home = document.querySelector('[data-menu-home="' + panel.getAttribute("data-menu-id") + '"]');
      if (home && home !== except) parkTxaMenu(panel);
    });
  }

  root.querySelectorAll(".txa-menu").forEach(function (menu, index) {
    var panel = menu.querySelector(".txa-menu__panel");
    if (!panel) return;
    var id = "txa-menu-" + index;
    panel.setAttribute("data-menu-id", id);
    menu.setAttribute("data-menu-home", id);
    menu.addEventListener("toggle", function () {
      if (!menu.open) {
        parkTxaMenu(panel);
        return;
      }
      closeTxaMenus(menu);
      document.body.appendChild(panel);
      panel.classList.add("is-floating");
      placeFixed(panel, menu.querySelector("summary") || menu, false);
    });
  });

  window.addEventListener("scroll", function () { closeTxaMenus(); }, true);
  window.addEventListener("resize", function () { closeTxaMenus(); });

  document.addEventListener("click", function (event) {
    var viewBtn = event.target.closest("[data-view-tx]");
    if (viewBtn) {
      event.preventDefault();
      closeTxaMenus();
      var dialog = document.querySelector('[data-view-dialog="' + viewBtn.getAttribute("data-view-tx") + '"]');
      if (dialog && dialog.showModal) dialog.showModal();
      return;
    }
    if (event.target.closest("[data-close-dialog]")) {
      var dialog = event.target.closest("dialog");
      if (dialog) dialog.close();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && drawer && !drawer.hidden) closeAddDrawer();
  });

  if (root.getAttribute("data-open-add-on-load") === "1") openAddDrawer();
})();
