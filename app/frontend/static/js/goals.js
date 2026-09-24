(function () {
  var root = document.querySelector("[data-goals-page]");
  if (!root) return;

  var goals = {};
  try {
    goals = JSON.parse((document.getElementById("goals-data") || {}).textContent || "{}") || {};
  } catch (_e) {
    goals = {};
  }

  function inr(value) {
    var n = Number(value) || 0;
    return "₹ " + n.toLocaleString("en-IN", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }

  function openDialog(dialog) {
    if (dialog && typeof dialog.showModal === "function") dialog.showModal();
  }

  function wireDialog(dialog) {
    if (!dialog) return;
    dialog.querySelectorAll("[data-dialog-close]").forEach(function (btn) {
      btn.addEventListener("click", function () { dialog.close(); });
    });
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) dialog.close();
    });
  }

  // ---------- Investment picker ----------
  function Picker(el) {
    this.el = el;
    this.search = el.querySelector("[data-picker-search]");
    this.showAll = el.querySelector("[data-picker-show-all]");
    this.summary = el.querySelector("[data-picker-summary]");
    this.tabs = el.querySelectorAll("[data-picker-tab]");
    this.panels = el.querySelectorAll("[data-picker-panel]");
    this.boxes = el.querySelectorAll('input[type="checkbox"][data-kind]');
    var self = this;

    this.tabs.forEach(function (tab) {
      tab.addEventListener("click", function () { self.showTab(tab.getAttribute("data-picker-tab")); });
    });
    if (this.search) this.search.addEventListener("input", function () { self.filter(); });
    if (this.showAll) this.showAll.addEventListener("change", function () { self.filter(); });
    this.boxes.forEach(function (box) {
      box.addEventListener("change", function () { self.updateSummary(); });
    });
  }

  Picker.prototype.showTab = function (name) {
    this.tabs.forEach(function (tab) {
      var on = tab.getAttribute("data-picker-tab") === name;
      tab.classList.toggle("is-on", on);
      tab.setAttribute("aria-selected", on ? "true" : "false");
    });
    this.panels.forEach(function (panel) {
      panel.hidden = panel.getAttribute("data-picker-panel") !== name;
    });
  };

  Picker.prototype.filter = function () {
    var q = (this.search && this.search.value || "").trim().toLowerCase();
    var showAll = !!(this.showAll && this.showAll.checked);
    this.el.querySelectorAll("[data-option]").forEach(function (li) {
      var box = li.querySelector("input");
      var other = li.classList.contains("is-other");
      // Selected rules stay visible even when they are not categorised as investments.
      var allowed = !other || showAll || (box && box.checked);
      var match = !q || (li.getAttribute("data-search") || "").indexOf(q) !== -1;
      li.hidden = !(allowed && match);
    });
  };

  Picker.prototype.reset = function (selected, goalId) {
    var ids = {};
    (selected || []).forEach(function (id) { ids[id] = true; });
    this.boxes.forEach(function (box) {
      box.checked = !!ids[box.value];
      // "Funds <other goal>" is only a warning when the item belongs to a different goal.
      var li = box.closest("[data-option]");
      var note = li && li.querySelector("[data-owner-note]");
      var owner = box.getAttribute("data-owner") || "";
      if (note) note.hidden = !owner || owner === goalId;
    });
    if (this.search) this.search.value = "";
    if (this.showAll) this.showAll.checked = false;
    this.showTab("recurring");
    this.filter();
    this.updateSummary();
  };

  Picker.prototype.setDisabled = function (disabled) {
    this.boxes.forEach(function (box) { box.disabled = disabled; });
  };

  Picker.prototype.updateSummary = function () {
    if (!this.summary) return;
    var rules = 0, monthly = 0, oneTime = 0, oneTimeTotal = 0, moved = 0;
    var goalId = this.el.getAttribute("data-goal-id") || "";
    this.boxes.forEach(function (box) {
      if (!box.checked) return;
      var owner = box.getAttribute("data-owner") || "";
      if (owner && owner !== goalId) moved += 1;
      if (box.getAttribute("data-kind") === "recurring") {
        rules += 1;
        monthly += Number(box.getAttribute("data-monthly")) || 0;
      } else {
        oneTime += 1;
        oneTimeTotal += Number(box.getAttribute("data-amount")) || 0;
      }
    });
    if (!rules && !oneTime) {
      this.summary.textContent = "Nothing selected";
      return;
    }
    var parts = [];
    if (rules) parts.push(rules + " recurring (≈ " + inr(monthly) + "/mo)");
    if (oneTime) parts.push(oneTime + " one-time (" + inr(oneTimeTotal) + ")");
    var text = "Selected: " + parts.join(" · ");
    if (moved) text += " — " + moved + " will move from another goal";
    this.summary.textContent = text;
  };

  // ---------- Create / edit goal ----------
  var goalDialog = document.querySelector("[data-goal-dialog]");
  var goalForm = goalDialog && goalDialog.querySelector("[data-goal-form]");
  var createLinks = goalDialog && goalDialog.querySelector("[data-create-links]");
  var createPicker = createLinks ? new Picker(createLinks.querySelector("[data-picker]")) : null;
  var accountField = goalDialog && goalDialog.querySelector("[data-account-field]");
  var accountSelect = goalDialog && goalDialog.querySelector("[data-account-select]");
  var editing = false;
  wireDialog(goalDialog);

  var editingGoal = null;
  var savedHelp = goalForm && goalForm.querySelector("#goal_current + .gol-help");
  var savedHelpDefault = savedHelp ? savedHelp.textContent : "";

  function applyTracking(event) {
    if (!goalForm) return;
    var checked = goalForm.querySelector("[data-tracking]:checked");
    var mode = checked ? checked.value : "investments";
    var byAccount = mode === "account";
    // Switching an account-tracked goal to investments: start from what the account
    // already holds, so progress doesn't drop to zero.
    if (event && !byAccount && editingGoal && editingGoal.account_balance) {
      var saved = goalForm.elements["current_amount"];
      if (saved && !(Number(saved.value) > 0)) {
        saved.value = editingGoal.account_balance;
        var help = saved.parentNode.querySelector(".gol-help");
        if (help) help.textContent = "Pre-filled with the account’s current balance. Linked investments are added on top.";
      }
    }
    if (accountField) accountField.hidden = !byAccount;
    if (accountSelect) {
      accountSelect.required = byAccount;
      // Investment tracking must clear any previously linked account.
      accountSelect.disabled = false;
      if (!byAccount) accountSelect.value = "";
    }
    if (createLinks) {
      createLinks.hidden = editing || byAccount;
      if (createPicker) createPicker.setDisabled(editing || byAccount);
    }
  }

  if (goalForm) {
    goalForm.querySelectorAll("[data-tracking]").forEach(function (radio) {
      radio.addEventListener("change", applyTracking);
    });
  }

  function setField(name, value) {
    var field = goalForm.elements[name];
    if (!field) return;
    if (field instanceof RadioNodeList) {
      Array.prototype.forEach.call(field, function (r) { r.checked = r.value === value; });
    } else {
      field.value = value == null ? "" : value;
      // Lets format.js refresh its DD/MM/YYYY display for date inputs.
      field.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  function openGoalForm(goal) {
    if (!goalForm) return;
    editing = !!goal;
    editingGoal = goal || null;
    goalForm.reset();
    if (savedHelp) savedHelp.textContent = savedHelpDefault;
    goalForm.action = goal ? "/planning/goals/" + encodeURIComponent(goal.id) + "/edit" : "/planning/goals";
    goalDialog.querySelector("[data-goal-dialog-title]").textContent = goal ? "Edit goal" : "New goal";
    goalDialog.querySelector("[data-goal-submit]").textContent = goal ? "Save changes" : "Create goal";
    if (goal) {
      setField("name", goal.name);
      setField("goal_type", goal.goal_type);
      setField("target_amount", goal.target_amount);
      setField("current_amount", goal.starting_amount || 0);
      setField("target_date", goal.target_date);
      setField("notes", goal.notes);
      setField("tracking", goal.linked_account_id ? "account" : "investments");
      if (accountSelect) accountSelect.value = goal.linked_account_id || "";
    } else {
      setField("target_date", "");
      if (createPicker) createPicker.reset([], "");
    }
    applyTracking();
    if (goal && accountSelect) accountSelect.value = goal.linked_account_id || "";
    openDialog(goalDialog);
    var first = goalForm.querySelector("#goal_name");
    if (first) setTimeout(function () { first.focus(); }, 30);
  }

  document.querySelectorAll("[data-goal-new]").forEach(function (btn) {
    btn.addEventListener("click", function () { openGoalForm(null); });
  });
  root.querySelectorAll("[data-goal-edit]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      closeMenus();
      openGoalForm(goals[btn.getAttribute("data-goal-edit")]);
    });
  });

  // ---------- Link investments ----------
  var linkDialog = document.querySelector("[data-link-dialog]");
  var linkForm = linkDialog && linkDialog.querySelector("[data-link-form]");
  var linkPickerEl = linkDialog && linkDialog.querySelector("[data-picker]");
  var linkPicker = linkPickerEl ? new Picker(linkPickerEl) : null;
  wireDialog(linkDialog);

  root.querySelectorAll("[data-goal-link]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      closeMenus();
      var goal = goals[btn.getAttribute("data-goal-link")];
      if (!goal || !linkForm || !linkPicker) return;
      linkForm.action = "/planning/goals/" + encodeURIComponent(goal.id) + "/links";
      linkDialog.querySelector("[data-link-goal-name]").textContent = goal.name;
      linkPickerEl.setAttribute("data-goal-id", goal.id);
      linkPicker.reset((goal.linked_recurring_ids || []).concat(goal.linked_transaction_ids || []), goal.id);
      openDialog(linkDialog);
    });
  });

  // ---------- Card menus & confirmations ----------
  function closeMenus(except) {
    root.querySelectorAll(".gol-menu[open]").forEach(function (menu) {
      if (menu !== except) menu.removeAttribute("open");
    });
  }

  root.querySelectorAll(".gol-menu").forEach(function (menu) {
    menu.addEventListener("toggle", function () { if (menu.open) closeMenus(menu); });
  });
  document.addEventListener("click", function (event) {
    if (!event.target.closest(".gol-menu")) closeMenus();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeMenus();
  });

  root.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-confirm"))) event.preventDefault();
    });
  });
})();
