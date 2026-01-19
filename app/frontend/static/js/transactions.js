<<<<<<< HEAD
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

=======
// Dynamic loading of categories and subcategories for transaction form
document.addEventListener("DOMContentLoaded", () => {
  const typeSelect = document.getElementById("tx_type");
  const categorySelect = document.getElementById("category");
  const subcategorySelect = document.getElementById("subcategory");

  function resetSelect(select, placeholder) {
    select.innerHTML = `<option value="">${placeholder}</option>`;
    select.disabled = true;
  }

  // Reset on load
  resetSelect(categorySelect, "-- Select Category --");
  resetSelect(subcategorySelect, "-- Select Subcategory --");

  // -----------------------------
  // Type → Categories
  // -----------------------------
  typeSelect.addEventListener("change", async () => {
    const type = typeSelect.value;

    resetSelect(categorySelect, "-- Select Category --");
    resetSelect(subcategorySelect, "-- Select Subcategory --");

    if (!type) return;

>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271
    try {
      const res = await fetch(`/api/categories?type=${type}`);
      const data = await res.json();

<<<<<<< HEAD
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
=======
      data.categories.forEach((cat) => {
        const opt = document.createElement("option");
        opt.value = cat.code;
        opt.textContent = cat.name;
        categorySelect.appendChild(opt);
      });

      categorySelect.disabled = false;
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271
    } catch (err) {
      console.error("Failed to load categories", err);
    }
  });

<<<<<<< HEAD
  // --------------------------------------------------
  // Category → Subcategories
  // --------------------------------------------------
  category.addEventListener("change", async () => {
    const categoryCode = category.value;
    const type = txType.value;

    resetSelect(subcategory, "-- Select Subcategory --");
=======
  // -----------------------------
  // Category → Subcategories
  // -----------------------------
  categorySelect.addEventListener("change", async () => {
    const categoryCode = categorySelect.value;
    const type = typeSelect.value;

    resetSelect(subcategorySelect, "-- Select Subcategory --");
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271

    if (!categoryCode || !type) return;

    try {
      const res = await fetch(
        `/api/categories/${categoryCode}/subcategories?type=${type}`
      );
      const data = await res.json();

<<<<<<< HEAD
      data.subcategories.forEach(sub => {
        const opt = document.createElement("option");
        opt.value = sub.code;
        opt.textContent = sub.name;
        subcategory.appendChild(opt);
      });
      if (type === "transfer" && data.subcategories.length > 0) {
        subcategory.selectedIndex = 1; // skip placeholder
      }
=======
      data.subcategories.forEach((sub) => {
        const opt = document.createElement("option");
        opt.value = sub.code;
        opt.textContent = sub.name;
        subcategorySelect.appendChild(opt);
      });

      subcategorySelect.disabled = false;
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271
    } catch (err) {
      console.error("Failed to load subcategories", err);
    }
  });
<<<<<<< HEAD

  // --------------------------------------------------
  // Transfer Mode
  // --------------------------------------------------
=======
});

  // ----------------------------------
  // Load To bank in Slef Trasfer Mode
  // ----------------------------------

document.addEventListener("DOMContentLoaded", () => {
  const txType = document.getElementById("tx_type");
  const fromAccount = document.getElementById("account");
  const targetWrapper = document.getElementById("target-account-wrapper");
  const targetAccount = document.getElementById("target_account");
  const category = document.getElementById("category");
  const subcategory = document.getElementById("subcategory");

>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271
  function updateTransferUI() {
    if (txType.value === "transfer") {
      targetWrapper.classList.remove("tohidden");
      targetAccount.required = true;

<<<<<<< HEAD
      catwrapper.style.display = "none";

      category.required = false;
      subcategory.required = false;

      const fromValue = account.value;
=======
      // Disable categories for transfer
      category.disabled = true;
      subcategory.disabled = true;
      category.value = "";
      subcategory.value = "";

      // Hide same account
      const fromValue = fromAccount.value;
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271
      Array.from(targetAccount.options).forEach(opt => {
        if (!opt.value) return;
        opt.hidden = opt.value === fromValue;
      });

    } else {
      targetWrapper.classList.add("tohidden");
      targetAccount.required = false;
      targetAccount.value = "";

<<<<<<< HEAD
      category.required = true;
      subcategory.required = true;
=======
      // Re-enable category flow
      category.disabled = false;

      // Reset & disable subcategory until category is selected
      subcategory.value = "";
      subcategory.disabled = true;

      // Trigger reload of categories when switching back
      category.dispatchEvent(new Event("change"));
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271
    }
  }

  txType.addEventListener("change", updateTransferUI);
<<<<<<< HEAD
  account.addEventListener("change", updateTransferUI);

  targetAccount.addEventListener("change", () => {
    if (targetAccount.value === account.value) {
=======
  fromAccount.addEventListener("change", updateTransferUI);

  targetAccount.addEventListener("change", () => {
    if (targetAccount.value === fromAccount.value) {
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271
      alert("From and To accounts cannot be the same");
      targetAccount.value = "";
    }
  });
<<<<<<< HEAD

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
=======
});


// Recurring Transactions model

const checkbox = document.getElementById("isRecurring");
const modal = document.getElementById("recurringModal");

checkbox.addEventListener("change", () => {
  modal.style.display = checkbox.checked ? "block" : "none";
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271
});
