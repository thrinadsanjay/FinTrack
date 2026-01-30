// Filter options for transactions list page

document.addEventListener("DOMContentLoaded", () => {
  const typeSelect = document.querySelector('select[name="tx_type"]');
  const categorySelect = document.getElementById("filter-category");
  const subcategorySelect = document.getElementById("filter-subcategory");

  function reset(select, placeholder) {
    select.innerHTML = `<option value="">${placeholder}</option>`;
    select.disabled = true;
  }

  reset(categorySelect, "All");
  reset(subcategorySelect, "All");

  async function loadCategories(type, selectedCategory) {
    if (!type) return;

    const res = await fetch(`/api/categories?type=${type}`);
    const data = await res.json();

    reset(categorySelect, "All");

    data.categories.forEach((cat) => {
      const opt = document.createElement("option");
      opt.value = cat.code;
      opt.textContent = cat.name;
      if (cat.code === selectedCategory) opt.selected = true;
      categorySelect.appendChild(opt);
    });

    categorySelect.disabled = false;
  }

  async function loadSubcategories(type, category, selectedSub) {
    if (!type || !category) return;

    const res = await fetch(
      `/api/categories/${category}/subcategories?type=${type}`
    );
    const data = await res.json();

    reset(subcategorySelect, "All");

    data.subcategories.forEach((sub) => {
      const opt = document.createElement("option");
      opt.value = sub.code;
      opt.textContent = sub.name;
      if (sub.code === selectedSub) opt.selected = true;
      subcategorySelect.appendChild(opt);
    });

    subcategorySelect.disabled = false;
  }

  // Initial load (for page refresh with filters)
  const initialType = typeSelect.value;
  const initialCategory = categorySelect.dataset.selected;
  const initialSubcategory = subcategorySelect.dataset.selected;

  if (initialType) {
    loadCategories(initialType, initialCategory).then(() => {
      if (initialCategory) {
        loadSubcategories(initialType, initialCategory, initialSubcategory);
      }
    });
  }

  typeSelect.addEventListener("change", () => {
    reset(categorySelect, "All");
    reset(subcategorySelect, "All");
    loadCategories(typeSelect.value);
  });

  categorySelect.addEventListener("change", () => {
    reset(subcategorySelect, "All");
    loadSubcategories(typeSelect.value, categorySelect.value);
  });
});


// Toggle filter panel

document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.getElementById("filterToggle");
  const wrapper = document.getElementById("filterWrapper");
  const arrow = document.getElementById("filterArrow");
  const form = document.getElementById("filterForm");

  if (!toggle || !wrapper || !form) return;

  toggle.addEventListener("click", () => {
    wrapper.classList.toggle("collapsed");
    wrapper.classList.toggle("expanded");
    toggle.classList.toggle("active");
  });

  toggle.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggle.click();
    }
  });

  // Auto-open if filters are active
  if (window.location.search.length > 1) {
    wrapper.classList.remove("collapsed");
    wrapper.classList.add("expanded");
    toggle.classList.add("active");
  }

  // Auto-close after submit
  form.addEventListener("submit", () => {
    wrapper.classList.remove("expanded");
    wrapper.classList.add("collapsed");
    toggle.classList.remove("active");
  });
});
