document.addEventListener("DOMContentLoaded", () => {

  // --------------------------------------------------
  // Elements
  // --------------------------------------------------
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

  // --------------------------------------------------
  // Helpers
  // --------------------------------------------------
  function resetSelect(select, placeholder) {
    select.innerHTML = `<option value="">${placeholder}</option>`;
  }

  function todayISO() {
    return new Date().toISOString().split("T")[0];
  }

  // --------------------------------------------------
  // Type → Categories
  // --------------------------------------------------
  txType.addEventListener("change", async () => {
    const type = txType.value;

    resetSelect(category, "-- Select Category --");
    resetSelect(subcategory, "-- Select Subcategory --");

    // if (!type || type === "transfer") {
    //   category.required = type !== "transfer";
    //   subcategory.required = type !== "transfer";
    //   return;
    // }

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
      if (type === "transfer" && data.categories.length > 0) {
        category.selectedIndex = 1; // index 0 is placeholder
        category.dispatchEvent(new Event("change"));
      }
    } catch (err) {
      console.error("Failed to load categories", err);
    }
  });

  // --------------------------------------------------
  // Category → Subcategories
  // --------------------------------------------------
  category.addEventListener("change", async () => {
    const categoryCode = category.value;
    const type = txType.value;

    resetSelect(subcategory, "-- Select Subcategory --");

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
      if (type === "transfer" && data.subcategories.length > 0) {
        subcategory.selectedIndex = 1; // skip placeholder
      }
    } catch (err) {
      console.error("Failed to load subcategories", err);
    }
  });

  // --------------------------------------------------
  // Transfer Mode
  // --------------------------------------------------
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

      category.required = true;
      subcategory.required = true;
    }
  }

  txType.addEventListener("change", updateTransferUI);
  account.addEventListener("change", updateTransferUI);

  targetAccount.addEventListener("change", () => {
    if (targetAccount.value === account.value) {
      alert("From and To accounts cannot be the same");
      targetAccount.value = "";
    }
  });

  // --------------------------------------------------
  // Recurring Toggle
  // --------------------------------------------------
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
    if (recurringCheckbox.checked) {
      enableRecurring();
    } else {
      disableRecurring();
    }
  });
});
