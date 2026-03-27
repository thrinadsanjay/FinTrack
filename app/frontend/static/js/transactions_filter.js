// Filter options for transactions list page

document.addEventListener("DOMContentLoaded", () => {
  const typeSelect = document.querySelector('select[name="tx_type"]');
  const categorySelect = document.getElementById("filter-category");
  const subcategorySelect = document.getElementById("filter-subcategory");
  const quickButtons = document.querySelectorAll("[data-quick-filter]");
  const form = document.getElementById("filterForm");
  const dateFrom = document.querySelector('input[name="date_from"]');
  const dateTo = document.querySelector('input[name="date_to"]');
  const accountSelect = document.querySelector('select[name="account_id"]');
  const searchInput = document.querySelector('input[name="search"]');

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

  function formatDate(d) {
    const month = `${d.getMonth() + 1}`.padStart(2, "0");
    const day = `${d.getDate()}`.padStart(2, "0");
    return `${d.getFullYear()}-${month}-${day}`;
  }

  function clearFilters() {
    if (accountSelect) accountSelect.value = "";
    if (typeSelect) typeSelect.value = "";
    if (dateFrom) dateFrom.value = "";
    if (dateTo) dateTo.value = "";
    if (searchInput) searchInput.value = "";
    reset(categorySelect, "All");
    reset(subcategorySelect, "All");
  }

  function applyQuery(params) {
    const qs = params.toString();
    window.location.search = qs ? `?${qs}` : "";
  }

  quickButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      if (!form) return;
      const now = new Date();
      clearFilters();
      const filter = btn.dataset.quickFilter;
      const params = new URLSearchParams();

      if (filter === "last7") {
        const start = new Date(now);
        start.setDate(now.getDate() - 6);
        params.set("date_from", formatDate(start));
        params.set("date_to", formatDate(now));
      }

      if (filter === "month") {
        const start = new Date(now.getFullYear(), now.getMonth(), 1);
        params.set("date_from", formatDate(start));
        params.set("date_to", formatDate(now));
      }

      if (filter === "transfers") {
        params.set("tx_type", "transfer");
      }

      applyQuery(params);
    });
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

  // Auto-close after submit
  form.addEventListener("submit", () => {
    wrapper.classList.remove("expanded");
    wrapper.classList.add("collapsed");
    toggle.classList.remove("active");
  });
});
