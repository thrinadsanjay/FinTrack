(function () {
  var root = document.querySelector("[data-tx-all]");
  if (!root) return;

  var openPanel = null;
  var openToggle = null;
  var ignoreDocClick = false;
  var editDialog = document.querySelector("[data-tx-edit-dialog]");
  var emiDialog = document.querySelector("[data-tx-emi-dialog]");

  var infoPop = document.createElement("div");
  infoPop.className = "txl-info-pop";
  infoPop.hidden = true;
  infoPop.setAttribute("role", "tooltip");
  document.body.appendChild(infoPop);

  function closeInfo() {
    infoPop.hidden = true;
    infoPop.textContent = "";
  }

  function closeMenu() {
    if (!openPanel) return;
    openPanel.hidden = true;
    openPanel.classList.remove("is-open");
    if (openToggle) openToggle.setAttribute("aria-expanded", "false");
    openPanel = null;
    openToggle = null;
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
    var menu = toggle.closest(".txl-menu");
    var panel = menu && menu.querySelector("[data-tx-menu-panel]");
    if (!panel) return;

    if (openPanel === panel) {
      closeMenu();
      return;
    }

    closeMenu();
    closeInfo();

    // Move panel to body so table overflow cannot clip it
    if (panel.parentElement !== document.body) {
      document.body.appendChild(panel);
    }

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
    closeMenu();
    var text = btn.getAttribute("data-info") || "";
    if (!text) return;
    infoPop.textContent = text;
    infoPop.hidden = false;
    placeFixed(infoPop, btn, true);
    ignoreDocClick = true;
    setTimeout(function () {
      ignoreDocClick = false;
    }, 0);
  }

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
      if (!infoPop.hidden && infoPop.dataset.anchor === infoBtn.getAttribute("data-info")) {
        closeInfo();
      } else {
        infoPop.dataset.anchor = infoBtn.getAttribute("data-info") || "";
        openInfo(infoBtn);
      }
      return;
    }

    var editBtn = event.target.closest("[data-tx-edit]");
    if (editBtn && editDialog) {
      event.preventDefault();
      closeMenu();
      editDialog.querySelector("[data-edit-id]").value = editBtn.getAttribute("data-id") || "";
      editDialog.querySelector("[data-edit-account]").value = editBtn.getAttribute("data-account-id") || "";
      editDialog.querySelector("[data-edit-amount]").value = editBtn.getAttribute("data-amount") || "";
      editDialog.querySelector("[data-edit-description]").value = editBtn.getAttribute("data-description") || "";
      editDialog.querySelector("[data-edit-category]").value = editBtn.getAttribute("data-category-code") || "";
      editDialog.querySelector("[data-edit-subcategory]").value = editBtn.getAttribute("data-subcategory-code") || "";
      editDialog.showModal();
      return;
    }

    var emiBtn = event.target.closest("[data-tx-emi]");
    if (emiBtn && emiDialog) {
      event.preventDefault();
      closeMenu();
      emiDialog.querySelector("[data-emi-id]").value = emiBtn.getAttribute("data-id") || "";
      emiDialog.querySelector("[data-emi-title]").value = emiBtn.getAttribute("data-description") || "EMI";
      var hint = emiDialog.querySelector("[data-emi-hint]");
      if (hint) {
        hint.textContent =
          "Convert ₹ " + (emiBtn.getAttribute("data-amount") || "") + " into an EMI plan on this credit card spend.";
      }
      emiDialog.showModal();
    }
  });

  // Menu items may live on document.body after open, so listen there too
  document.addEventListener("click", function (event) {
    if (ignoreDocClick) return;

    var editBtn = event.target.closest("[data-tx-edit]");
    if (editBtn && editDialog && editBtn.closest("[data-tx-menu-panel]")) {
      event.preventDefault();
      closeMenu();
      editDialog.querySelector("[data-edit-id]").value = editBtn.getAttribute("data-id") || "";
      editDialog.querySelector("[data-edit-account]").value = editBtn.getAttribute("data-account-id") || "";
      editDialog.querySelector("[data-edit-amount]").value = editBtn.getAttribute("data-amount") || "";
      editDialog.querySelector("[data-edit-description]").value = editBtn.getAttribute("data-description") || "";
      editDialog.querySelector("[data-edit-category]").value = editBtn.getAttribute("data-category-code") || "";
      editDialog.querySelector("[data-edit-subcategory]").value = editBtn.getAttribute("data-subcategory-code") || "";
      editDialog.showModal();
      return;
    }

    var emiBtn = event.target.closest("[data-tx-emi]");
    if (emiBtn && emiDialog && emiBtn.closest("[data-tx-menu-panel]")) {
      event.preventDefault();
      closeMenu();
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

    if (event.target.closest("[data-tx-menu-toggle], [data-tx-menu-panel], [data-tx-info], .txl-info-pop")) {
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
      if (!infoPop.hidden) closeInfo();
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
})();
