document.addEventListener("DOMContentLoaded", () => {
  const bankInput = document.getElementById("bank_name");
  const typeSelect = document.getElementById("acc_type");
  const nameInput = document.getElementById("account_name");
  const formToggle = document.getElementById("accountToggle");
  const accountForm = document.getElementById("accountForm");
  const setupRow = document.getElementById("accountSetupRow");
  const setupSummary = document.getElementById("accountSetupSummary");
  const setupTrigger = document.getElementById("accountSetupTrigger");

  const accountBackdrop = document.getElementById("accountModalBackdrop");
  const balanceModal = document.getElementById("balanceModal");
  const creditCardModal = document.getElementById("creditCardModal");
  const balanceInput = document.getElementById("balance_input");
  const balanceHidden = document.getElementById("balance_hidden");
  const saveBalanceConfig = document.getElementById("saveBalanceConfig");
  const saveCreditCardConfig = document.getElementById("saveCreditCardConfig");

  const cardNetworkInput = document.getElementById("card_network");
  const statementBalanceInput = document.getElementById("statement_balance");
  const billingCycleStartDayInput = document.getElementById("billing_cycle_start_day");
  const billingCycleEndDayInput = document.getElementById("billing_cycle_end_day");
  const dueDayInput = document.getElementById("due_day");

  const navItems = document.querySelectorAll("[data-card-target]");
  const detailPanels = document.querySelectorAll("[data-card-panel]");

  const workspaceBackdrop = document.getElementById("workspaceModalBackdrop");
  const emiModal = document.getElementById("emiModal");
  const payBillModal = document.getElementById("payBillModal");
  const emiModalHeading = document.getElementById("emiModalHeading");
  const emiModalTitle = document.getElementById("emiModalTitle");
  const emiModalForm = document.getElementById("emiModalForm");
  const emiModalSubmit = document.getElementById("emiModalSubmit");
  const emiAccountId = document.getElementById("emi_account_id");
  const emiId = document.getElementById("emi_id");
  const emiTitle = document.getElementById("emi_title");
  const emiTotalInstallments = document.getElementById("emi_total_installments");
  const emiRemainingInstallments = document.getElementById("emi_remaining_installments");

  const payBillModalTitle = document.getElementById("payBillModalTitle");
  const payBillTargetAccountId = document.getElementById("pay_bill_target_account_id");
  const payBillCreditBillId = document.getElementById("pay_bill_credit_bill_id");
  const payBillAmount = document.getElementById("pay_bill_amount");
  const payBillOutstanding = document.getElementById("pay_bill_outstanding");
  const payBillMinimumDue = document.getElementById("pay_bill_minimum_due");
  const payBillStatementBalance = document.getElementById("pay_bill_statement_balance");
  const payChoices = document.querySelectorAll("[data-pay-choice]");

  let userEditedName = false;
  let currentSetup = "";
  let activeWorkspaceModal = null;

  function hoistModal(node) {
    if (!node || !document.body || node.parentElement === document.body) {
      return;
    }
    document.body.appendChild(node);
  }

  [accountBackdrop, balanceModal, creditCardModal, workspaceBackdrop, emiModal, payBillModal].forEach(hoistModal);

  function money(value) {
    const parsed = Number.parseFloat(value || "0");
    const safe = Number.isFinite(parsed) ? parsed : 0;
    return `Rs ${safe.toFixed(2)}`;
  }

  function generateName() {
    if (!bankInput || !typeSelect || !nameInput || userEditedName) {
      return;
    }

    const bank = bankInput.value.trim();
    const type = typeSelect.value;
    if (!(bank && type)) {
      nameInput.value = "";
      return;
    }

    const label = typeSelect.options[typeSelect.selectedIndex]?.text || "Account";
    nameInput.value = `${bank}-${label}`;
  }

  function closeAccountModals() {
    [balanceModal, creditCardModal].forEach((modal) => {
      if (modal) {
        modal.classList.add("is-hidden");
        modal.setAttribute("aria-hidden", "true");
      }
    });
    accountBackdrop?.classList.add("is-hidden");
  }

  function openAccountModal(kind) {
    if (!accountBackdrop) {
      return;
    }
    closeAccountModals();
    currentSetup = kind;
    const modal = kind === "credit_card" ? creditCardModal : balanceModal;
    modal?.classList.remove("is-hidden");
    modal?.setAttribute("aria-hidden", "false");
    accountBackdrop.classList.remove("is-hidden");
  }

  function syncSetupSummary() {
    if (!setupRow || !setupSummary || !typeSelect) {
      return;
    }

    const type = typeSelect.value;
    if (!type) {
      setupRow.hidden = true;
      currentSetup = "";
      closeAccountModals();
      return;
    }

    setupRow.hidden = false;

    if (type === "credit_card") {
      const statementBalance = statementBalanceInput?.value || "0";
      const cycleStart = billingCycleStartDayInput?.value || "1";
      const cycleEnd = billingCycleEndDayInput?.value || "30";
      const dueDay = dueDayInput?.value || "5";
      const cardNetwork = cardNetworkInput?.options[cardNetworkInput.selectedIndex]?.text || "Visa";
      setupSummary.innerHTML = `
        <span>Credit card details ready</span>
        <small>${cardNetwork} · Statement ${money(statementBalance)} · Cycle ${cycleStart}-${cycleEnd} · Due day ${dueDay}</small>
      `;
      balanceHidden.value = "0";
    } else {
      const openingBalance = balanceHidden?.value || balanceInput?.value || "0";
      setupSummary.innerHTML = `
        <span>Account setup ready</span>
        <small>Opening balance ${money(openingBalance)}</small>
      `;
    }
  }

  function syncTypeSetup(forceModal = false) {
    if (!typeSelect) {
      return;
    }

    const type = typeSelect.value;
    if (!type) {
      syncSetupSummary();
      return;
    }

    currentSetup = type === "credit_card" ? "credit_card" : "standard";
    if (type !== "credit_card") {
      balanceHidden.value = balanceInput?.value || balanceHidden.value || "0";
    } else {
      balanceHidden.value = "0";
    }

    syncSetupSummary();

    if (forceModal) {
      openAccountModal(type === "credit_card" ? "credit_card" : "standard");
    }
  }

  if (nameInput) {
    nameInput.addEventListener("input", () => {
      userEditedName = true;
    });
  }

  bankInput?.addEventListener("input", generateName);
  cardNetworkInput?.addEventListener("change", () => syncSetupSummary());
  billingCycleStartDayInput?.addEventListener("input", () => syncSetupSummary());
  billingCycleEndDayInput?.addEventListener("input", () => syncSetupSummary());
  dueDayInput?.addEventListener("input", () => syncSetupSummary());
  statementBalanceInput?.addEventListener("input", () => syncSetupSummary());
  typeSelect?.addEventListener("change", () => {
    generateName();
    syncTypeSetup(true);
  });

  formToggle?.addEventListener("click", () => {
    accountForm?.classList.toggle("account-form-collapsed");
    formToggle.classList.toggle("open");
  });

  setupTrigger?.addEventListener("click", () => {
    if (typeSelect?.value === "credit_card") {
      openAccountModal("credit_card");
    } else {
      openAccountModal("standard");
    }
  });

  saveBalanceConfig?.addEventListener("click", () => {
    if (!balanceHidden || !balanceInput) {
      return;
    }
    balanceHidden.value = balanceInput.value || "0";
    syncSetupSummary();
    closeAccountModals();
  });

  saveCreditCardConfig?.addEventListener("click", () => {
    syncSetupSummary();
    closeAccountModals();
  });

  accountBackdrop?.addEventListener("click", closeAccountModals);
  document.querySelectorAll("[data-close-modal]").forEach((button) => {
    button.addEventListener("click", closeAccountModals);
  });

  function closeAllCardMenus() {
    detailPanels.forEach((panel) => {
      const menu = panel.querySelector("[data-card-menu]");
      const toggle = panel.querySelector("[data-card-menu-toggle]");
      menu?.classList.add("is-hidden");
      toggle?.setAttribute("aria-expanded", "false");
    });
  }

  function closeAllEmiMenus() {
    document.querySelectorAll("[data-emi-menu]").forEach((menu) => {
      menu.classList.add("is-hidden");
    });
    document.querySelectorAll("[data-emi-menu-toggle]").forEach((toggle) => {
      toggle.setAttribute("aria-expanded", "false");
    });
  }

  function collapseCardSections(panel) {
    if (!panel) {
      return;
    }
    panel.querySelectorAll("[data-card-section]").forEach((section) => {
      section.hidden = true;
      section.classList.add("is-collapsed");
    });
  }

  function openCardSection(panel, sectionName) {
    if (!panel || !sectionName) {
      return;
    }
    collapseCardSections(panel);
    const section = panel.querySelector(`[data-card-section="${sectionName}"]`);
    if (!section) {
      return;
    }
    section.hidden = false;
    section.classList.remove("is-collapsed");
  }

  function activateCard(cardId) {
    navItems.forEach((item) => {
      item.classList.toggle("is-active", item.dataset.cardTarget === cardId);
    });
    detailPanels.forEach((panel) => {
      const isActive = panel.dataset.cardPanel === cardId;
      panel.classList.toggle("is-active", isActive);
      if (!isActive) {
        collapseCardSections(panel);
      }
    });
    closeAllCardMenus();
    closeAllEmiMenus();
  }

  navItems.forEach((item) => {
    item.addEventListener("click", () => {
      activateCard(item.dataset.cardTarget || "");
    });
  });

  function resetEmiModal() {
    emiModalForm?.setAttribute("action", "/accounts/credit-card/emi/add");
    if (emiModalHeading) {
      emiModalHeading.textContent = "Add New EMI";
    }
    if (emiModalTitle) {
      emiModalTitle.textContent = "Track a new EMI against the selected credit card.";
    }
    if (emiModalSubmit) {
      emiModalSubmit.textContent = "Add EMI";
    }
    if (emiId) {
      emiId.value = "";
    }
    emiModalForm?.setAttribute("data-inline-success-message", "EMI added");
  }

  detailPanels.forEach((panel) => {
    collapseCardSections(panel);

    const toggle = panel.querySelector("[data-card-menu-toggle]");
    const menu = panel.querySelector("[data-card-menu]");

    toggle?.addEventListener("click", (event) => {
      event.stopPropagation();
      const isOpen = !menu?.classList.contains("is-hidden");
      closeAllCardMenus();
      closeAllEmiMenus();
      if (!menu) {
        return;
      }
      if (!isOpen) {
        menu.classList.remove("is-hidden");
        toggle.setAttribute("aria-expanded", "true");
      }
    });

    panel.querySelectorAll("[data-card-section-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        openCardSection(panel, button.dataset.cardSectionToggle || "");
        closeAllCardMenus();
      });
    });

    panel.querySelectorAll(".js-open-pay-modal, .js-open-emi-modal, .credit-card-detail__menu-form").forEach((node) => {
      node.addEventListener("click", () => {
        closeAllCardMenus();
      });
    });
  });

  document.querySelectorAll("[data-emi-menu-toggle]").forEach((toggle) => {
    toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      const wrap = toggle.closest(".credit-card-emi-row-menu-wrap");
      const menu = wrap?.querySelector("[data-emi-menu]");
      const isOpen = !menu?.classList.contains("is-hidden");
      closeAllEmiMenus();
      closeAllCardMenus();
      if (!menu) {
        return;
      }
      if (!isOpen) {
        menu.classList.remove("is-hidden");
        toggle.setAttribute("aria-expanded", "true");
      }
    });
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".credit-card-detail__menu-wrap")) {
      closeAllCardMenus();
    }
    if (!event.target.closest(".credit-card-emi-row-menu-wrap")) {
      closeAllEmiMenus();
    }
  });

  function closeWorkspaceModal() {
    activeWorkspaceModal?.classList.add("is-hidden");
    activeWorkspaceModal?.setAttribute("aria-hidden", "true");
    workspaceBackdrop?.classList.add("is-hidden");
    activeWorkspaceModal = null;
  }

  function openWorkspaceModal(modal) {
    if (!modal || !workspaceBackdrop) {
      return;
    }
    closeWorkspaceModal();
    modal.classList.remove("is-hidden");
    modal.setAttribute("aria-hidden", "false");
    workspaceBackdrop.classList.remove("is-hidden");
    activeWorkspaceModal = modal;
  }

  document.querySelectorAll("[data-close-workspace-modal]").forEach((button) => {
    button.addEventListener("click", () => {
      closeWorkspaceModal();
      resetEmiModal();
    });
  });
  workspaceBackdrop?.addEventListener("click", () => {
    closeWorkspaceModal();
    resetEmiModal();
  });

  document.querySelectorAll(".js-open-emi-modal").forEach((button) => {
    button.addEventListener("click", () => {
      resetEmiModal();
      const cardId = button.dataset.cardId || "";
      const cardName = button.dataset.cardName || "this card";
      if (emiAccountId) {
        emiAccountId.value = cardId;
      }
      if (emiModalTitle) {
        emiModalTitle.textContent = `Track a new EMI for ${cardName}.`;
      }
      if (emiTitle) {
        emiTitle.value = "";
      }
      if (emiTotalInstallments) {
        emiTotalInstallments.value = "";
      }
      if (emiRemainingInstallments) {
        emiRemainingInstallments.value = "";
      }
      emiModalForm?.reset();
      if (emiAccountId) {
        emiAccountId.value = cardId;
      }
      if (emiId) {
        emiId.value = "";
      }
      openWorkspaceModal(emiModal);
    });
  });

  document.querySelectorAll(".js-edit-emi-modal").forEach((button) => {
    button.addEventListener("click", () => {
      resetEmiModal();
      if (emiModalHeading) {
        emiModalHeading.textContent = "Edit EMI";
      }
      if (emiModalTitle) {
        emiModalTitle.textContent = `Update EMI details for ${button.dataset.cardName || "this card"}.`;
      }
      if (emiModalSubmit) {
        emiModalSubmit.textContent = "Save EMI";
      }
      emiModalForm?.setAttribute("action", "/accounts/credit-card/emi/update");
      emiModalForm?.setAttribute("data-inline-success-message", "EMI updated");
      if (emiAccountId) {
        emiAccountId.value = button.dataset.accountId || "";
      }
      if (emiId) {
        emiId.value = button.dataset.emiId || "";
      }
      const formElements = emiModalForm?.elements;
      if (emiTitle) {
        emiTitle.value = button.dataset.emiTitle || "";
      }
      formElements?.namedItem("total_amount") && (formElements.namedItem("total_amount").value = button.dataset.totalAmount || "");
      formElements?.namedItem("monthly_amount") && (formElements.namedItem("monthly_amount").value = button.dataset.monthlyAmount || "");
      if (emiTotalInstallments) {
        emiTotalInstallments.value = button.dataset.totalInstallments || "";
      }
      if (emiRemainingInstallments) {
        emiRemainingInstallments.value = button.dataset.remainingInstallments || "";
      }
      formElements?.namedItem("interest_rate") && (formElements.namedItem("interest_rate").value = button.dataset.interestRate || "");
      formElements?.namedItem("next_due_date") && (formElements.namedItem("next_due_date").value = button.dataset.nextDueDate || "");
      closeAllEmiMenus();
      openWorkspaceModal(emiModal);
    });
  });

  emiTotalInstallments?.addEventListener("input", () => {
    if (!emiRemainingInstallments) {
      return;
    }
    if (!emiRemainingInstallments.value) {
      emiRemainingInstallments.value = emiTotalInstallments.value;
    }
  });

  function setPayChoice(choice) {
    payChoices.forEach((button) => {
      button.classList.toggle("is-active", button.dataset.payChoice === choice);
    });
  }

  document.querySelectorAll(".js-open-pay-modal").forEach((button) => {
    button.addEventListener("click", () => {
      const cardId = button.dataset.cardId || "";
      const cardName = button.dataset.cardName || "this card";
      const statementBalance = Number.parseFloat(button.dataset.cardStatementBalance || "0") || 0;
      const outstanding = Number.parseFloat(button.dataset.cardOutstanding || "0") || 0;
      const minimumDue = Number.parseFloat(button.dataset.cardMinimumDue || "0") || (statementBalance > 0 ? Number((statementBalance * 0.1).toFixed(2)) : 0);
      const creditBillId = button.dataset.cardBillId || "";

      if (payBillTargetAccountId) {
        payBillTargetAccountId.value = cardId;
      }
      if (payBillCreditBillId) {
        payBillCreditBillId.value = creditBillId;
      }
      if (payBillModalTitle) {
        payBillModalTitle.textContent = `Choose how much you want to pay for ${cardName}.`;
      }
      if (payBillOutstanding) {
        payBillOutstanding.textContent = money(outstanding);
      }
      if (payBillMinimumDue) {
        payBillMinimumDue.textContent = money(minimumDue);
      }
      if (payBillStatementBalance) {
        payBillStatementBalance.textContent = money(statementBalance);
      }
      if (payBillAmount) {
        payBillAmount.value = statementBalance > 0 ? statementBalance.toFixed(2) : minimumDue.toFixed(2);
      }
      setPayChoice(statementBalance > 0 ? "full" : "minimum");

      payChoices.forEach((choiceButton) => {
        choiceButton.onclick = () => {
          const kind = choiceButton.dataset.payChoice || "partial";
          setPayChoice(kind);
          if (!payBillAmount) {
            return;
          }
          if (kind === "minimum") {
            payBillAmount.value = minimumDue.toFixed(2);
          } else if (kind === "full") {
            payBillAmount.value = statementBalance.toFixed(2);
          } else {
            payBillAmount.focus();
            payBillAmount.select();
          }
        };
      });

      openWorkspaceModal(payBillModal);
    });
  });

  document.querySelectorAll(".edit-btn").forEach((editBtn) => {
    editBtn.addEventListener("click", () => {
      const row = editBtn.closest("tr");
      row?.querySelectorAll(".editable").forEach((input) => {
        input.disabled = false;
        input.classList.add("editing");
      });
      editBtn.style.display = "none";
      row?.querySelector(".save-btn")?.style.setProperty("display", "inline-flex");
      row?.querySelector(".cancel-btn")?.style.setProperty("display", "inline-flex");
      row?.querySelector(".delete-btn")?.style.setProperty("display", "none");
    });
  });

  document.querySelectorAll(".cancel-btn").forEach((cancelBtn) => {
    cancelBtn.addEventListener("click", () => {
      const row = cancelBtn.closest("tr");
      row?.querySelectorAll(".editable").forEach((input) => {
        input.value = input.dataset.original || "";
        input.disabled = true;
        input.classList.remove("editing");
      });
      row?.querySelector(".edit-btn")?.style.setProperty("display", "inline-flex");
      row?.querySelector(".delete-btn")?.style.setProperty("display", "inline-flex");
      row?.querySelector(".save-btn")?.style.setProperty("display", "none");
      cancelBtn.style.display = "none";
    });
  });

  syncTypeSetup(false);
  resetEmiModal();
  if (navItems[0]) {
    activateCard(navItems[0].dataset.cardTarget || "");
  }
});
