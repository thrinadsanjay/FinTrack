document.addEventListener("DOMContentLoaded", () => {

  /* ==================================================
     ELEMENTS
  ================================================== */
  const txType = document.getElementById("tx_type");
  const account = document.getElementById("account");
  const targetWrapper = document.getElementById("target-account-wrapper");
  const targetAccount = document.getElementById("target_account");

  const category = document.getElementById("category");
  const subcategory = document.getElementById("subcategory");
  const catwrapper = document.getElementById("category-wrapper");

  const recurringCheckbox = document.getElementById("isRecurring");
  const recurringSection = document.getElementById("recurringSection");
  const recurringFrequency = document.getElementById("recurringFrequency");
  const recurringStartDate = document.getElementById("recurringStartDate");
  const recurringEndDate = document.getElementById("recurringEndDate");

  /* ==================================================
     HELPERS
  ================================================== */
  function resetSelect(select, placeholder = "") {
    select.innerHTML = `<option value="" hidden>${placeholder}</option>`;
  }

  function todayISO() {
    return new Date().toISOString().split("T")[0];
  }

  function isFilled(el) {
    return el.value !== null && el.value !== "";
  }

  /* ==================================================
     FLOATING LABELS (single source of truth)
  ================================================== */
  document.querySelectorAll(".form-field input, .form-field select")
    .forEach(field => {
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

      if (field.value) updateState(); // initial load
    });

  /* ==================================================
     TYPE → CATEGORIES
  ================================================== */
  txType.addEventListener("change", async () => {
    const type = txType.value;

    resetSelect(category);
    resetSelect(subcategory);

    if (!type) return;

    category.required = type !== "transfer";
    subcategory.required = type !== "transfer";

    try {
      const res = await fetch(`/api/categories?type=${type}`);
      const data = await res.json();

      data.categories.forEach(cat => {
        const opt = document.createElement("option");
        opt.value = cat.code;
        opt.textContent = cat.name;
        category.appendChild(opt);
      });

      if (type === "transfer" && data.categories.length) {
        category.selectedIndex = 1;
        category.dispatchEvent(new Event("change"));
      }
    } catch (err) {
      console.error("Failed to load categories", err);
    }
  });

  /* ==================================================
     CATEGORY → SUBCATEGORY
  ================================================== */
  category.addEventListener("change", async () => {
    const categoryCode = category.value;
    const type = txType.value;

    resetSelect(subcategory);
    if (!categoryCode || !type) return;

    try {
      const res = await fetch(
        `/api/categories/${categoryCode}/subcategories?type=${type}`
      );
      const data = await res.json();

      data.subcategories.forEach(sub => {
        const opt = document.createElement("option");
        opt.value = sub.code;
        opt.textContent = sub.name;
        subcategory.appendChild(opt);
      });

      if (type === "transfer" && data.subcategories.length) {
        subcategory.selectedIndex = 1;
      }
    } catch (err) {
      console.error("Failed to load subcategories", err);
    }
  });

  /* ==================================================
     TRANSFER MODE
  ================================================== */
  function updateTransferUI() {
    if (txType.value === "transfer") {
      targetWrapper.classList.remove("tohidden");
      targetAccount.required = true;

      catwrapper.style.display = "none";
      category.required = false;
      subcategory.required = false;

      const fromValue = account.value;
      Array.from(targetAccount.options).forEach(opt => {
        if (!opt.value) return;
        opt.hidden = opt.value === fromValue;
      });
    } else {
      targetWrapper.classList.add("tohidden");
      targetAccount.required = false;
      targetAccount.value = "";

      catwrapper.style.display = "";
      category.required = true;
      subcategory.required = true;
    }
  }

  txType.addEventListener("change", updateTransferUI);
  account.addEventListener("change", updateTransferUI);

  targetAccount?.addEventListener("change", () => {
    if (targetAccount.value === account.value) {
      alert("From and To accounts cannot be the same");
      targetAccount.value = "";
    }
  });

  /* ==================================================
     RECURRING TOGGLE
  ================================================== */
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
});
