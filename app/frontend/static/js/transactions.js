(function () {
  var form = document.querySelector("[data-tx-form]");
  if (!form) return;

  var typeSelect = form.querySelector("[data-tx-type-select]") || form.querySelector("#tx_type");
  var typeRadios = form.querySelectorAll("[data-tx-type]");
  var categorySelect = form.querySelector("#category_code");
  var subcategorySelect = form.querySelector("#subcategory_code");
  var transferOnly = form.querySelectorAll("[data-transfer-only]");
  var nonTransfer = form.querySelectorAll("[data-non-transfer]");
  var transferCatFields = form.querySelector("[data-transfer-category-fields]");
  var transferCategory = form.querySelector("[data-transfer-category]");
  var transferSubcategory = form.querySelector("[data-transfer-subcategory]");
  var recurringToggle = form.querySelector("[data-recurring-toggle]");
  var recurringPanel = form.querySelector("[data-recurring-panel]");
  var recurringFields = form.querySelectorAll("[data-recurring-field]");
  var intervalSuffix = form.querySelector("[data-interval-suffix]");
  var frequencySelect = form.querySelector("#frequency");
  var startDate = form.querySelector("#start_date");
  var pastToggle = form.querySelector("[data-past-toggle]");
  var pastPanel = form.querySelector("[data-past-panel]");
  var dateField = form.querySelector("[data-past-date]") || form.querySelector("#transaction_date");
  var categorySection = form.querySelector("[data-category-section]");
  var categoryHint = form.querySelector("[data-category-hint]");
  var TRANSFER_CATEGORY = "transfer";
  var TRANSFER_SUBCATEGORY = "transfer";

  function currentType() {
    var checked = form.querySelector("[data-tx-type]:checked");
    if (checked) return checked.value;
    return typeSelect ? typeSelect.value : "debit";
  }

  function syncTypeSelect() {
    if (!typeSelect) return;
    typeSelect.value = currentType();
  }

  function setCategoryHint(text) {
    if (categoryHint) categoryHint.textContent = text;
  }

  function clearSelect(select, placeholder) {
    if (!select) return;
    select.innerHTML = "";
    var opt = document.createElement("option");
    opt.value = "";
    opt.textContent = placeholder;
    select.appendChild(opt);
  }

  function fillSelect(select, items, placeholder) {
    clearSelect(select, placeholder);
    (items || []).forEach(function (item) {
      var code = item.code || item.id || item.value;
      var label = item.name || item.label || code;
      if (!code) return;
      var opt = document.createElement("option");
      opt.value = code;
      opt.textContent = label;
      select.appendChild(opt);
    });
  }

  function setTransferCategoryMode(enabled) {
    if (!transferCatFields || !transferCategory || !transferSubcategory) return;
    transferCategory.disabled = !enabled;
    transferSubcategory.disabled = !enabled;
    if (enabled) {
      transferCategory.value = TRANSFER_CATEGORY;
      transferSubcategory.value = TRANSFER_SUBCATEGORY;
    }
    if (categorySelect) categorySelect.disabled = enabled;
    if (subcategorySelect) subcategorySelect.disabled = enabled;
  }

  async function loadCategories() {
    var type = currentType();
    if (type === "transfer") {
      applySelfTransferDefaults();
      return;
    }

    setTransferCategoryMode(false);
    if (categorySection) categorySection.hidden = false;
    setCategoryHint("Showing " + (type === "credit" ? "income" : "expense") + " categories from the database.");
    clearSelect(categorySelect, "Loading…");
    clearSelect(subcategorySelect, "Select category first");

    try {
      var res = await fetch("/api/categories?type=" + encodeURIComponent(type));
      var data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to load categories");
      var items = Array.isArray(data) ? data : data.categories || [];
      fillSelect(categorySelect, items, "Select category");
      if (categorySelect) categorySelect.required = true;
      if (subcategorySelect) subcategorySelect.required = true;
    } catch (_err) {
      clearSelect(categorySelect, "Unable to load categories");
    }
  }

  async function loadSubcategories() {
    var type = currentType();
    if (type === "transfer") return;
    if (!categorySelect || !subcategorySelect) return;

    var code = categorySelect.value;
    if (!code) {
      clearSelect(subcategorySelect, "Select category first");
      return;
    }

    clearSelect(subcategorySelect, "Loading…");
    try {
      var res = await fetch(
        "/api/categories/" +
          encodeURIComponent(code) +
          "/subcategories?type=" +
          encodeURIComponent(type)
      );
      var data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to load subcategories");
      var items = Array.isArray(data) ? data : data.subcategories || [];
      fillSelect(subcategorySelect, items, "Select subcategory");
    } catch (_err) {
      clearSelect(subcategorySelect, "Unable to load");
    }
  }

  function applySelfTransferDefaults() {
    setCategoryHint("Self Transfer is applied automatically.");
    if (categorySection) categorySection.hidden = true;
    nonTransfer.forEach(function (el) {
      el.hidden = true;
    });
    if (categorySelect) categorySelect.required = false;
    if (subcategorySelect) subcategorySelect.required = false;
    setTransferCategoryMode(true);
  }

  function syncTypeUi() {
    var type = currentType();
    var isTransfer = type === "transfer";

    syncTypeSelect();

    transferOnly.forEach(function (el) {
      el.hidden = !isTransfer;
      var target = el.querySelector("#target_account_id");
      if (target) {
        target.disabled = !isTransfer;
        if (isTransfer) target.setAttribute("required", "required");
        else target.removeAttribute("required");
      }
    });

    nonTransfer.forEach(function (el) {
      el.hidden = isTransfer;
    });

    if (!isTransfer) {
      setTransferCategoryMode(false);
      if (categorySelect) categorySelect.required = true;
      if (subcategorySelect) subcategorySelect.required = true;
      loadCategories();
    } else {
      applySelfTransferDefaults();
    }
  }

  function syncIntervalSuffix() {
    if (!frequencySelect || !intervalSuffix) return;
    var map = {
      daily: "day(s)",
      weekly: "week(s)",
      biweekly: "biweek(s)",
      monthly: "month(s)",
      quarterly: "quarter(s)",
      halfyearly: "half-year(s)",
      yearly: "year(s)",
    };
    intervalSuffix.textContent = map[frequencySelect.value] || "period(s)";
  }

  function localIsoDate(date) {
    var month = String(date.getMonth() + 1).padStart(2, "0");
    var day = String(date.getDate()).padStart(2, "0");
    return date.getFullYear() + "-" + month + "-" + day;
  }

  function todayIso() {
    return localIsoDate(new Date());
  }

  function clampPastDate() {
    if (!dateField || !dateField.value) return;
    if (dateField.value > todayIso()) dateField.value = "";
  }

  function syncPast() {
    var on = !!(pastToggle && pastToggle.checked);
    if (pastPanel) {
      pastPanel.hidden = !on;
      pastPanel.setAttribute("aria-hidden", on ? "false" : "true");
    }
    if (dateField) {
      dateField.max = todayIso();
      dateField.disabled = !on;
      if (on) {
        dateField.setAttribute("required", "required");
        clampPastDate();
      } else {
        dateField.removeAttribute("required");
        dateField.value = "";
        var shown = dateField.parentNode && dateField.parentNode.querySelector(".ft-date__display");
        if (shown) shown.value = "";
      }
    }
  }

  function syncRecurring() {
    var forced = form.getAttribute("data-force-recurring") === "1";
    if (forced && recurringToggle && !recurringToggle.checked) recurringToggle.checked = true;
    var on = forced || !!(recurringToggle && recurringToggle.checked);
    if (recurringPanel) {
      recurringPanel.classList.toggle("is-enabled", on);
      recurringPanel.setAttribute("aria-hidden", on ? "false" : "true");
    }
    recurringFields.forEach(function (field) {
      field.disabled = !on;
      if (on) {
        if (field.id === "frequency" || field.id === "interval" || field.id === "start_date") {
          field.setAttribute("required", "required");
        }
      } else {
        field.removeAttribute("required");
      }
    });
    if (on && startDate && !startDate.value) {
      startDate.value = todayIso();
    }
    syncIntervalSuffix();
  }

  typeRadios.forEach(function (radio) {
    radio.addEventListener("change", syncTypeUi);
  });

  if (categorySelect) {
    categorySelect.addEventListener("change", loadSubcategories);
  }

  if (recurringToggle) {
    recurringToggle.addEventListener("change", function () {
      if (form.getAttribute("data-force-recurring") === "1") {
        recurringToggle.checked = true;
      }
      syncRecurring();
    });
    recurringToggle.addEventListener("click", function (event) {
      if (form.getAttribute("data-force-recurring") === "1") event.preventDefault();
    });
  }

  if (pastToggle) {
    pastToggle.addEventListener("change", syncPast);
  }

  if (dateField) {
    dateField.addEventListener("change", clampPastDate);
  }

  if (frequencySelect) {
    frequencySelect.addEventListener("change", syncIntervalSuffix);
  }

  syncTypeUi();
  syncPast();
  syncRecurring();
})();
