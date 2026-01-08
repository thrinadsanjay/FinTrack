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

    try {
      const res = await fetch(`/api/categories?type=${type}`);
      const data = await res.json();

      data.categories.forEach((cat) => {
        const opt = document.createElement("option");
        opt.value = cat.code;
        opt.textContent = cat.name;
        categorySelect.appendChild(opt);
      });

      categorySelect.disabled = false;
    } catch (err) {
      console.error("Failed to load categories", err);
    }
  });

  // -----------------------------
  // Category → Subcategories
  // -----------------------------
  categorySelect.addEventListener("change", async () => {
    const categoryCode = categorySelect.value;
    const type = typeSelect.value;

    resetSelect(subcategorySelect, "-- Select Subcategory --");

    if (!categoryCode || !type) return;

    try {
      const res = await fetch(
        `/api/categories/${categoryCode}/subcategories?type=${type}`
      );
      const data = await res.json();

      data.subcategories.forEach((sub) => {
        const opt = document.createElement("option");
        opt.value = sub.code;
        opt.textContent = sub.name;
        subcategorySelect.appendChild(opt);
      });

      subcategorySelect.disabled = false;
    } catch (err) {
      console.error("Failed to load subcategories", err);
    }
  });
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

  function updateTransferUI() {
    if (txType.value === "transfer") {
      targetWrapper.classList.remove("tohidden");
      targetAccount.required = true;

      // Disable categories for transfer
      category.disabled = true;
      subcategory.disabled = true;
      category.value = "";
      subcategory.value = "";

      // Hide same account
      const fromValue = fromAccount.value;
      Array.from(targetAccount.options).forEach(opt => {
        if (!opt.value) return;
        opt.hidden = opt.value === fromValue;
      });

    } else {
      targetWrapper.classList.add("tohidden");
      targetAccount.required = false;
      targetAccount.value = "";

      // Re-enable category flow
      category.disabled = false;

      // Reset & disable subcategory until category is selected
      subcategory.value = "";
      subcategory.disabled = true;

      // Trigger reload of categories when switching back
      category.dispatchEvent(new Event("change"));
    }
  }

  txType.addEventListener("change", updateTransferUI);
  fromAccount.addEventListener("change", updateTransferUI);

  targetAccount.addEventListener("change", () => {
    if (targetAccount.value === fromAccount.value) {
      alert("From and To accounts cannot be the same");
      targetAccount.value = "";
    }
  });
});


// Recurring Transactions model

const checkbox = document.getElementById("isRecurring");
const modal = document.getElementById("recurringModal");

checkbox.addEventListener("change", () => {
  modal.style.display = checkbox.checked ? "block" : "none";
});
