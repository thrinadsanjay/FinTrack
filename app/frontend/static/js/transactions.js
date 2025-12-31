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

const targetWrapper = document.getElementById("target-account-wrapper");
const targetSelect = document.getElementById("target_account");
const accountSelect = document.getElementById("account");

typeSelect.addEventListener("change", () => {
  if (typeSelect.value === "transfer") {
    targetWrapper.style.display = "block";
    targetSelect.required = true;
  } else {
    targetWrapper.style.display = "none";
    targetSelect.required = false;
    targetSelect.value = "";
  }
});

accountSelect.addEventListener("change", () => {
  const source = accountSelect.value;
  [...targetSelect.options].forEach(opt => {
    opt.disabled = opt.value === source && opt.value !== "";
  });
});