(function () {
  var root = document.querySelector("[data-accounts-page]");
  if (!root) return;

  var drawer = document.querySelector("[data-add-drawer]");
  var bankForm = document.querySelector('[data-account-form="bank"]');
  var ccForm = document.querySelector('[data-account-form="credit_card"]');
  var loanForm = document.querySelector('[data-account-form="loan"]');
  var tabs = document.querySelectorAll("[data-kind-tab]");
  var holdingsTabs = document.querySelectorAll("[data-holdings-tab]");
  var balanceDialog = document.querySelector("[data-balance-dialog]");
  var successDialog = document.querySelector("[data-success-dialog]");
  var pendingForm = null;

  var bankName = document.querySelector("[data-bank-name]");
  var bankType = document.querySelector("[data-bank-type]");
  var bankTypeValue = document.querySelector("[data-bank-type-value]");
  var displayName = document.querySelector("[data-display-name]");
  var bankBalance = document.querySelector("[data-balance]");
  var ccBank = document.querySelector("[data-cc-bank]");
  var ccDisplay = document.querySelector("[data-cc-display]");
  var ccOutstanding = document.querySelector("[data-cc-outstanding]");
  var ccBalance = document.querySelector("[data-cc-balance]");
  var loanBank = document.querySelector("[data-loan-bank]");
  var loanKind = document.querySelector("[data-loan-kind]");
  var loanIcon = document.querySelector("[data-loan-icon]");
  var loanName = document.querySelector("[data-loan-name]");
  var loanBalance = document.querySelector("[data-loan-balance]");
  var loanPrincipal = document.querySelector("[data-loan-principal]");

  var displayTouched = false;
  var ccDisplayTouched = false;
  var loanNameTouched = false;

  function money(value) {
    if (window.FTFormat) return FTFormat.formatINR(value, { space: true });
    var n = Number(value || 0);
    return "₹ " + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function typeLabel(code) {
    var option = bankType && bankType.querySelector('option[value="' + code + '"]');
    return option ? option.textContent.trim() : String(code || "");
  }

  function syncBankTypeHidden() {
    if (bankType && bankTypeValue) bankTypeValue.value = bankType.value;
  }

  function autoDisplayName() {
    if (!displayName || displayTouched) return;
    var bank = (bankName && bankName.value.trim()) || "";
    var type = bankType ? typeLabel(bankType.value) : "";
    displayName.value = bank ? (type ? bank + " " + type : bank) : "";
  }

  function autoCcDisplay() {
    if (!ccDisplay || ccDisplayTouched) return;
    var bank = (ccBank && ccBank.value.trim()) || "";
    ccDisplay.value = bank ? bank + " Credit Card" : "";
  }

  function loanKindLabel() {
    if (!loanKind || !loanKind.value) return "";
    var option = loanKind.selectedOptions && loanKind.selectedOptions[0];
    return option ? option.textContent.trim() : "";
  }

  function syncLoanIcon() {
    if (!loanIcon) return;
    var option = loanKind && loanKind.selectedOptions && loanKind.selectedOptions[0];
    var icon = (option && option.getAttribute("data-icon")) || "fa-file-invoice-dollar";
    loanIcon.className = "fa-solid " + icon;
  }

  function autoLoanName() {
    if (!loanName || loanNameTouched) return;
    var bank = (loanBank && loanBank.value.trim()) || "";
    var type = loanKindLabel();
    if (bank && type) loanName.value = bank + " " + type;
    else if (bank) loanName.value = bank;
    else loanName.value = "";
  }

  function setKind(kind) {
    tabs.forEach(function (tab) {
      var active = tab.getAttribute("data-kind-tab") === kind;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
    if (bankForm) bankForm.hidden = kind !== "bank";
    if (ccForm) ccForm.hidden = kind !== "credit_card";
    if (loanForm) loanForm.hidden = kind !== "loan";
  }

  function openDrawer(kind) {
    if (!drawer) return;
    drawer.hidden = false;
    document.body.style.overflow = "hidden";
    setKind(kind || "bank");
  }

  function closeDrawer() {
    if (!drawer) return;
    drawer.hidden = true;
    document.body.style.overflow = "";
  }

  function filterHoldings(group) {
    holdingsTabs.forEach(function (tab) {
      var active = tab.getAttribute("data-holdings-tab") === group;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
    root.querySelectorAll("[data-holding-row]").forEach(function (row) {
      row.hidden = group !== "all" && row.getAttribute("data-group") !== group;
    });
  }

  function placeFixed(el, anchor) {
    var rect = anchor.getBoundingClientRect();
    var width = Math.min(el.offsetWidth || 140, window.innerWidth - 16);
    var height = el.offsetHeight || 120;
    var left = Math.min(Math.max(8, rect.right - width), window.innerWidth - width - 8);
    var top = rect.bottom + 6;
    if (top + height > window.innerHeight - 8) {
      top = Math.max(8, rect.top - height - 6);
    }
    el.style.position = "fixed";
    el.style.top = Math.round(top) + "px";
    el.style.left = Math.round(left) + "px";
    el.style.right = "auto";
  }

  function parkMenuPanel(panel) {
    if (!panel) return;
    panel.classList.remove("is-floating");
    var home = document.querySelector('[data-menu-home="' + panel.getAttribute("data-menu-id") + '"]');
    if (home && panel.parentElement !== home) home.appendChild(panel);
  }

  function closeMenus(except) {
    root.querySelectorAll(".acc-menu[open]").forEach(function (menu) {
      if (menu !== except) menu.removeAttribute("open");
    });
    document.querySelectorAll(".acc-menu__panel.is-floating").forEach(function (panel) {
      var home = document.querySelector('[data-menu-home="' + panel.getAttribute("data-menu-id") + '"]');
      if (home && home !== except) parkMenuPanel(panel);
    });
  }

  root.querySelectorAll(".acc-menu").forEach(function (menu, index) {
    var panel = menu.querySelector(".acc-menu__panel");
    if (!panel) return;
    var id = "acc-menu-" + index;
    panel.setAttribute("data-menu-id", id);
    menu.setAttribute("data-menu-home", id);
    menu.addEventListener("toggle", function () {
      if (!menu.open) {
        parkMenuPanel(panel);
        return;
      }
      closeMenus(menu);
      document.body.appendChild(panel);
      panel.classList.add("is-floating");
      placeFixed(panel, menu.querySelector("summary") || menu);
    });
  });

  window.addEventListener("scroll", function () { closeMenus(); }, true);
  window.addEventListener("resize", function () { closeMenus(); });

  function openNamedDialog(attr, id) {
    closeMenus();
    var dialog = document.querySelector("[" + attr + "=\"" + id + "\"]");
    if (dialog && dialog.showModal) dialog.showModal();
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      setKind(tab.getAttribute("data-kind-tab"));
    });
  });

  holdingsTabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      filterHoldings(tab.getAttribute("data-holdings-tab"));
    });
  });

  root.querySelectorAll("[data-open-add]").forEach(function (btn) {
    btn.addEventListener("click", function () { openDrawer("bank"); });
  });
  document.querySelectorAll("[data-close-add]").forEach(function (btn) {
    btn.addEventListener("click", closeDrawer);
  });
  if (drawer) {
    drawer.addEventListener("click", function (event) {
      if (event.target === drawer) closeDrawer();
    });
  }
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && drawer && !drawer.hidden) closeDrawer();
  });

  if (bankType) bankType.addEventListener("change", function () { syncBankTypeHidden(); autoDisplayName(); });
  if (bankName) bankName.addEventListener("input", autoDisplayName);
  if (displayName) displayName.addEventListener("input", function () { displayTouched = true; });
  if (ccBank) ccBank.addEventListener("input", autoCcDisplay);
  if (ccDisplay) ccDisplay.addEventListener("input", function () { ccDisplayTouched = true; });
  if (loanBank) loanBank.addEventListener("input", autoLoanName);
  if (loanKind) loanKind.addEventListener("change", function () { syncLoanIcon(); autoLoanName(); });
  if (loanName) loanName.addEventListener("input", function () { loanNameTouched = true; });

  function monthlyRate(annual) {
    return Number(annual || 0) / 12 / 100;
  }

  function suggestedEmi(principal, annual, months) {
    principal = Math.max(Number(principal || 0), 0);
    months = parseInt(months, 10) || 0;
    if (principal <= 0 || months <= 0) return 0;
    var rate = monthlyRate(annual);
    if (rate <= 0) return Math.round((principal / months) * 100) / 100;
    var factor = Math.pow(1 + rate, months);
    return Math.round((principal * rate * factor / (factor - 1)) * 100) / 100;
  }

  function suggestedTenure(principal, annual, emi) {
    principal = Math.max(Number(principal || 0), 0);
    emi = Math.max(Number(emi || 0), 0);
    if (principal <= 0 || emi <= 0) return 0;
    var rate = monthlyRate(annual);
    if (rate <= 0) return Math.max(1, Math.ceil(principal / emi - 1e-9));
    if (emi <= principal * rate + 0.005) return 0;
    var months = Math.log(emi / (emi - principal * rate)) / Math.log(1 + rate);
    return Math.max(1, Math.round(months));
  }

  function bindLoanCalc(form) {
    if (!form) return;
    var principal = form.querySelector("[data-loan-principal]");
    var outstanding = form.querySelector("[data-loan-balance]");
    var rate = form.querySelector("[data-loan-rate]");
    var emi = form.querySelector("[data-loan-emi]");
    var tenure = form.querySelector("[data-loan-tenure]");
    var hint = form.querySelector("[data-loan-calc-hint]");
    var pref = tenure && tenure.value ? "tenure" : (emi && emi.value ? "emi" : "");
    var filling = false;

    function principalValue() {
      var raw = principal && principal.value ? principal.value : (outstanding && outstanding.value);
      return Number(raw || 0);
    }

    function setHint(text) {
      if (hint) hint.textContent = text;
    }

    function sync() {
      if (filling) return;
      filling = true;
      if (outstanding && principal && !principal.value && outstanding.value) {
        principal.value = outstanding.value;
      }
      var p = principalValue();
      var annual = rate ? rate.value : 0;
      if (pref === "tenure") {
        var nextEmi = suggestedEmi(p, annual, tenure && tenure.value);
        if (nextEmi > 0 && emi) emi.value = nextEmi.toFixed(2);
        setHint(nextEmi > 0
          ? "EMI suggested from principal, rate, and tenure. You can change it."
          : "Fill principal, rate, and tenure to suggest EMI.");
      } else if (pref === "emi") {
        var nextTenure = suggestedTenure(p, annual, emi && emi.value);
        if (nextTenure > 0 && tenure) tenure.value = String(nextTenure);
        setHint(nextTenure > 0
          ? "Tenure suggested from principal, rate, and EMI. You can change it."
          : (Number(emi && emi.value) > 0 && p > 0
            ? "EMI is too low to cover monthly interest."
            : "Fill principal, rate, and EMI to suggest tenure."));
      } else {
        setHint("Fill principal, rate, and either EMI or tenure — the other is suggested and stays editable.");
      }
      filling = false;
    }

    if (outstanding) {
      outstanding.addEventListener("input", function () {
        if (principal && !principal.value) principal.value = outstanding.value;
        sync();
      });
    }
    if (principal) principal.addEventListener("input", sync);
    if (rate) rate.addEventListener("input", sync);
    if (emi) {
      emi.addEventListener("input", function () { pref = "emi"; sync(); });
    }
    if (tenure) {
      tenure.addEventListener("input", function () { pref = "tenure"; sync(); });
    }
  }

  document.querySelectorAll("[data-loan-calc]").forEach(bindLoanCalc);

  document.addEventListener("click", function (event) {
    var viewBtn = event.target.closest("[data-view-account]");
    if (viewBtn) {
      event.preventDefault();
      openNamedDialog("data-view-dialog", viewBtn.getAttribute("data-view-account"));
      return;
    }
    var editBtn = event.target.closest("[data-edit-account]");
    if (editBtn) {
      event.preventDefault();
      openNamedDialog("data-edit-dialog", editBtn.getAttribute("data-edit-account"));
    }
    if (event.target.closest("[data-close-dialog]")) {
      var dialog = event.target.closest("dialog");
      if (dialog) dialog.close();
    }
  });

  function openBalanceConfirm(opts) {
    if (!balanceDialog || !balanceDialog.showModal) {
      if (pendingForm) pendingForm.submit();
      return;
    }
    var title = balanceDialog.querySelector("[data-dialog-title]");
    var copy = balanceDialog.querySelector("[data-dialog-copy]");
    var amount = balanceDialog.querySelector("[data-dialog-amount]");
    if (title) title.textContent = opts.title || "Confirm balance";
    if (copy) copy.textContent = opts.copy || "Review the amount before saving.";
    if (amount) amount.textContent = money(opts.amount || 0);
    balanceDialog.showModal();
  }

  if (balanceDialog) {
    balanceDialog.addEventListener("close", function () {
      if (balanceDialog.returnValue === "confirm" && pendingForm) {
        var form = pendingForm;
        pendingForm = null;
        HTMLFormElement.prototype.submit.call(form);
      } else {
        pendingForm = null;
      }
    });
  }

  if (bankForm) {
    bankForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!bankForm.checkValidity()) { bankForm.reportValidity(); return; }
      syncBankTypeHidden();
      if (displayName && !displayName.value.trim()) { displayTouched = false; autoDisplayName(); }
      pendingForm = bankForm;
      openBalanceConfirm({
        title: "Confirm opening balance",
        copy: "You’re creating “" + ((displayName && displayName.value) || (bankName && bankName.value) || "account") + "” with this opening balance.",
        amount: bankBalance ? bankBalance.value : 0
      });
    });
  }

  if (ccForm) {
    ccForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!ccForm.checkValidity()) { ccForm.reportValidity(); return; }
      var outstanding = Number((ccOutstanding && ccOutstanding.value) || 0);
      if (!isFinite(outstanding) || outstanding < 0) outstanding = 0;
      if (ccBalance) ccBalance.value = String(-Math.abs(outstanding));
      if (ccDisplay && !ccDisplay.value.trim()) { ccDisplayTouched = false; autoCcDisplay(); }
      pendingForm = ccForm;
      openBalanceConfirm({
        title: "Confirm credit card balances",
        copy: "Outstanding will be saved for “" + ((ccDisplay && ccDisplay.value) || (ccBank && ccBank.value) || "card") + "”.",
        amount: outstanding
      });
    });
  }

  if (loanForm) {
    loanForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (loanName && !loanName.value.trim()) { loanNameTouched = false; autoLoanName(); }
      if (!loanForm.checkValidity()) { loanForm.reportValidity(); return; }
      pendingForm = loanForm;
      openBalanceConfirm({
        title: "Confirm loan outstanding",
        copy: "This outstanding is tracked as a liability and is not added to Total cash.",
        amount: loanBalance ? loanBalance.value : 0
      });
    });
  }

  if (root.getAttribute("data-created") === "1" && successDialog && successDialog.showModal) {
    var kind = root.getAttribute("data-created-kind") || "account";
    var bal = Number(root.getAttribute("data-created-balance") || 0);
    var shown = kind === "credit_card" ? Math.abs(bal) : Math.abs(bal);
    var copy = successDialog.querySelector("[data-success-copy]");
    var amount = successDialog.querySelector("[data-success-amount]");
    if (copy) {
      copy.textContent =
        kind === "loan"
          ? "Loan created. Outstanding (not in cash):"
          : kind === "credit_card"
            ? "Credit card created. Outstanding balance:"
            : "Account created. Opening balance:";
    }
    if (amount) amount.textContent = money(shown);
    successDialog.showModal();
    if (window.history && window.history.replaceState) window.history.replaceState({}, "", "/accounts");
  }

  var openView = root.getAttribute("data-open-view");
  if (openView) openNamedDialog("data-view-dialog", openView);

  var holdingsGroup = root.getAttribute("data-holdings-group");
  if (holdingsGroup === "bank" || holdingsGroup === "card" || holdingsGroup === "loan") {
    filterHoldings(holdingsGroup);
  }

  syncBankTypeHidden();
  autoDisplayName();
  syncLoanIcon();
  setKind("bank");
})();
