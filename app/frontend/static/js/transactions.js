document.addEventListener("DOMContentLoaded", () => {
  const txType = document.getElementById("tx_type");
  const account = document.getElementById("account");
  const targetWrapper = document.getElementById("target-account-wrapper");
  const targetAccount = document.getElementById("target_account");
  const targetLabel = document.getElementById("target-account-label");
  const description = document.getElementById("description");
  const amountInput = document.getElementById("amount");
  const cardPaymentAmounts = document.getElementById("card-payment-amounts");
  const cardPaymentHint = document.getElementById("card-payment-hint");
  const cardPaymentButtons = document.querySelectorAll("[data-amount-source]");

  const category = document.getElementById("category");
  const subcategory = document.getElementById("subcategory");
  const catwrapper = document.getElementById("category-wrapper");

  const recurringCheckbox = document.getElementById("isRecurring");
  const recurringSection = document.getElementById("recurringSection");
  const recurringFrequency = document.getElementById("recurringFrequency");
  const recurringStartDate = document.getElementById("recurringStartDate");
  const recurringEndDate = document.getElementById("recurringEndDate");

  function resetSelect(select, placeholder = "") {
    select.innerHTML = `<option value="" hidden>${placeholder}</option>`;
  }

  function todayISO() {
    return new Date().toISOString().split("T")[0];
  }

  function isFilled(el) {
    return el.value !== null && el.value !== "";
  }

  function optionType(option) {
    return option?.dataset?.accountType || "";
  }

  function maybeSeedCardPaymentDescription() {
    if (!description) return;
    if (txType.value === "card_payment" && description.value.trim() === "") {
      description.value = "Card Payment";
      description.dispatchEvent(new Event("change"));
    }
  }

  function selectedTargetOption() {
    return targetAccount?.selectedOptions?.[0] || null;
  }

  function cardMetric(option, key) {
    if (!option) return 0;
    const raw = option.dataset?.[key] || "0";
    const value = Number.parseFloat(raw);
    return Number.isFinite(value) ? value : 0;
  }

  function formatCurrency(value) {
    return `Rs ${value.toFixed(2)}`;
  }

  function syncCardPaymentAmountButtons() {
    if (!cardPaymentAmounts || !cardPaymentHint) return;

    const isCardPayment = txType.value === "card_payment";
    const option = selectedTargetOption();
    cardPaymentAmounts.classList.toggle("is-hidden", !isCardPayment);

    if (!isCardPayment) {
      return;
    }

    const minimumDue = cardMetric(option, "minimumDue");
    const statementBalance = cardMetric(option, "statementBalance");
    const outstanding = cardMetric(option, "currentOutstanding");

    cardPaymentButtons.forEach((button) => {
      const source = button.dataset.amountSource;
      if (source === "other") {
        button.disabled = false;
        button.textContent = "Other";
        return;
      }
      const amount = source === "minimum_due" ? minimumDue : statementBalance;
      button.disabled = !option || amount <= 0;
      button.textContent = `${source === "minimum_due" ? "Minimum due" : "Statement balance"} · ${formatCurrency(amount)}`;
    });

    if (!option) {
      cardPaymentHint.textContent = "Pick a card to load payment suggestions.";
      return;
    }

    cardPaymentHint.textContent = `Outstanding: ${formatCurrency(outstanding)}`;
  }

  function applyCardPaymentAmount(source) {
    if (!amountInput) return;
    const option = selectedTargetOption();
    if (!option) return;

    if (source === "other") {
      amountInput.focus();
      amountInput.select();
      return;
    }

    const amount = source === "minimum_due"
      ? cardMetric(option, "minimumDue")
      : cardMetric(option, "statementBalance");

    if (amount <= 0) return;

    amountInput.value = amount.toFixed(2);
    amountInput.dispatchEvent(new Event("change"));
    amountInput.focus();
  }

  document.querySelectorAll(".form-field input, .form-field select").forEach((field) => {
    const wrapper = field.closest(".form-field");

    const updateState = () => {
      if (isFilled(field)) {
        wrapper.classList.add("field--active");
        wrapper.classList.remove("field--idle");
      } else {
        wrapper.classList.add("field--idle");
        wrapper.classList.remove("field--active");
      }
    };

    field.addEventListener("focus", () => {
      wrapper.classList.add("field--active");
      wrapper.classList.remove("field--idle");
    });

    field.addEventListener("blur", updateState);
    field.addEventListener("change", updateState);

    if (field.value) updateState();
  });

  txType.addEventListener("change", async () => {
    const rawType = txType.value;
    const categoryType = rawType === "card_payment" ? "transfer" : rawType;

    maybeSeedCardPaymentDescription();
    resetSelect(category);
    resetSelect(subcategory);

    if (!rawType) return;

    const requiresCategory = !(rawType === "transfer" || rawType === "card_payment");
    category.required = requiresCategory;
    subcategory.required = requiresCategory;

    try {
      const res = await fetch(`/api/categories?type=${categoryType}`);
      const data = await res.json();

      data.categories.forEach((cat) => {
        const opt = document.createElement("option");
        opt.value = cat.code;
        opt.textContent = cat.name;
        category.appendChild(opt);
      });

      if ((rawType === "transfer" || rawType === "card_payment") && data.categories.length) {
        category.selectedIndex = 1;
        category.dispatchEvent(new Event("change"));
      }
    } catch (err) {
      console.error("Failed to load categories", err);
    }
  });

  category.addEventListener("change", async () => {
    const categoryCode = category.value;
    const rawType = txType.value;
    const categoryType = rawType === "card_payment" ? "transfer" : rawType;

    resetSelect(subcategory);
    if (!categoryCode || !categoryType) return;

    try {
      const res = await fetch(`/api/categories/${categoryCode}/subcategories?type=${categoryType}`);
      const data = await res.json();

      data.subcategories.forEach((sub) => {
        const opt = document.createElement("option");
        opt.value = sub.code;
        opt.textContent = sub.name;
        subcategory.appendChild(opt);
      });

      if ((rawType === "transfer" || rawType === "card_payment") && data.subcategories.length) {
        subcategory.selectedIndex = 1;
      }
    } catch (err) {
      console.error("Failed to load subcategories", err);
    }
  });

  function syncCardPaymentOptions() {
    const isCardPayment = txType.value === "card_payment";
    const fromValue = account.value;

    Array.from(account.options).forEach((opt) => {
      if (!opt.value) return;
      const accType = optionType(opt);
      opt.hidden = isCardPayment && accType === "credit_card";
      if (opt.hidden && opt.selected) {
        account.value = "";
      }
    });

    Array.from(targetAccount.options).forEach((opt) => {
      if (!opt.value) return;
      const accType = optionType(opt);
      const hideForTransfer = txType.value === "transfer" && opt.value === fromValue;
      const hideForCardPayment = isCardPayment && (accType !== "credit_card" || opt.value === fromValue);
      opt.hidden = hideForTransfer || hideForCardPayment;
      if (opt.hidden && opt.selected) {
        targetAccount.value = "";
      }
    });
  }

  function updateTransferUI() {
    const isTransfer = txType.value === "transfer";
    const isCardPayment = txType.value === "card_payment";

    if (isTransfer || isCardPayment) {
      targetWrapper.classList.remove("tohidden");
      targetAccount.required = true;
      catwrapper.style.display = "none";
      category.required = false;
      subcategory.required = false;
      if (targetLabel) {
        targetLabel.textContent = isCardPayment ? "Pay To Card" : "Transfer To";
      }
      maybeSeedCardPaymentDescription();
      syncCardPaymentOptions();
      syncCardPaymentAmountButtons();
    } else {
      targetWrapper.classList.add("tohidden");
      targetAccount.required = false;
      targetAccount.value = "";
      catwrapper.style.display = "";
      category.required = true;
      subcategory.required = true;
      if (targetLabel) {
        targetLabel.textContent = "Transfer To";
      }
      Array.from(account.options).forEach((opt) => {
        if (opt.value) opt.hidden = false;
      });
      Array.from(targetAccount.options).forEach((opt) => {
        if (opt.value) opt.hidden = false;
      });
      syncCardPaymentAmountButtons();
    }
  }

  txType.addEventListener("change", updateTransferUI);
  account.addEventListener("change", updateTransferUI);

  targetAccount?.addEventListener("change", () => {
    if (targetAccount.value === account.value) {
      alert("From and To accounts cannot be the same");
      targetAccount.value = "";
    }
    syncCardPaymentAmountButtons();
  });

  cardPaymentButtons.forEach((button) => {
    button.addEventListener("click", () => {
      applyCardPaymentAmount(button.dataset.amountSource || "other");
    });
  });

  function enableRecurring() {
    recurringSection.style.display = "block";
    recurringFrequency.required = true;
    recurringStartDate.required = true;

    if (!recurringStartDate.value) {
      recurringStartDate.value = todayISO();
    }
  }

  function disableRecurring() {
    recurringSection.style.display = "none";
    recurringFrequency.required = false;
    recurringStartDate.required = false;

    recurringFrequency.value = "";
    recurringStartDate.value = "";
    recurringEndDate.value = "";
  }

  if (recurringCheckbox.checked) {
    enableRecurring();
  } else {
    disableRecurring();
  }

  recurringCheckbox.addEventListener("change", () => {
    recurringCheckbox.checked ? enableRecurring() : disableRecurring();
  });

  updateTransferUI();
  syncCardPaymentAmountButtons();
  if (txType.value) {
    txType.dispatchEvent(new Event("change"));
  }
});
