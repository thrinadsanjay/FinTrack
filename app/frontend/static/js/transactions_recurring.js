(function () {
  var root = document.querySelector("[data-recurring-page]");
  if (!root) return;

  var drawer = document.querySelector("[data-add-drawer]");

  function openAddDrawer() {
    if (!drawer) return;
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

  document.querySelectorAll("[data-open-add]").forEach(function (btn) {
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
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && drawer && !drawer.hidden) closeAddDrawer();
  });
  if (root.getAttribute("data-open-add-on-load") === "1") openAddDrawer();

  var dialog = document.querySelector("[data-recurring-edit-dialog]");
  if (!dialog) return;

  var idField = dialog.querySelector("[data-edit-id]");
  var amountField = dialog.querySelector("[data-edit-amount]");
  var descriptionField = dialog.querySelector("[data-edit-description]");
  var frequencyField = dialog.querySelector("[data-edit-frequency]");
  var endDateField = dialog.querySelector("[data-edit-end-date]");

  function closeDialog() {
    if (typeof dialog.close === "function") dialog.close();
  }

  function openDialog(data) {
    if (idField) idField.value = data.id || "";
    if (amountField) amountField.value = data.amount || "";
    if (descriptionField) descriptionField.value = data.description || "";
    if (frequencyField && data.frequency) frequencyField.value = data.frequency;
    if (endDateField) endDateField.value = data.endDate || "";
    if (typeof dialog.showModal === "function") dialog.showModal();
  }

  root.querySelectorAll("[data-recurring-edit]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      openDialog({
        id: btn.getAttribute("data-id"),
        amount: btn.getAttribute("data-amount"),
        description: btn.getAttribute("data-description"),
        frequency: btn.getAttribute("data-frequency"),
        endDate: btn.getAttribute("data-end-date"),
      });
    });
  });

  dialog.querySelectorAll("[data-dialog-close]").forEach(function (btn) {
    btn.addEventListener("click", closeDialog);
  });

  dialog.addEventListener("click", function (event) {
    if (event.target === dialog) closeDialog();
  });

  if (root.getAttribute("data-open-edit") === "1") {
    if (typeof dialog.showModal === "function") dialog.showModal();
  }
})();
