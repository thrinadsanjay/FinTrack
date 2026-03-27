document.addEventListener("DOMContentLoaded", () => {
  const modal = document.getElementById("edit-modal");
  const cancelBtn = document.getElementById("edit-cancel");
  const cancelAlt = document.getElementById("edit-cancel-alt");

  const txId = document.getElementById("edit-transaction-id");
  const accountSel = document.getElementById("edit-account");
  const amountInp = document.getElementById("edit-amount");
  const categorySel = document.getElementById("edit-category");
  const subcategorySel = document.getElementById("edit-subcategory");
  const descriptionInp = document.getElementById("edit-description");

  function reset(sel, label) {
    sel.innerHTML = `<option value="">${label}</option>`;
    sel.disabled = true;
  }

  async function loadCategories(type, cat, sub) {
    const res = await fetch(`/api/categories?type=${type}`);
    const data = await res.json();

    reset(categorySel, "-- Select Category --");

    data.categories.forEach(c => {
      const o = document.createElement("option");
      o.value = c.code;
      o.textContent = c.name;
      categorySel.appendChild(o);
    });

    categorySel.disabled = false;
    categorySel.value = cat;

    await loadSubcategories(type, cat, sub);
  }

  async function loadSubcategories(type, cat, sub) {
    if (!cat) return;

    const res = await fetch(`/api/categories/${cat}/subcategories?type=${type}`);
    const data = await res.json();

    reset(subcategorySel, "-- Select Subcategory --");

    data.subcategories.forEach(s => {
      const o = document.createElement("option");
      o.value = s.code;
      o.textContent = s.name;
      subcategorySel.appendChild(o);
    });

    subcategorySel.disabled = false;
    subcategorySel.value = sub;
  }

  document.querySelectorAll(".edit-transaction-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      modal.classList.remove("hidden");

      txId.value = btn.dataset.id;
      amountInp.value = btn.dataset.amount;
      descriptionInp.value = btn.dataset.description || "";
      //descriptionInp.value = btn.dataset.description;

      // Populate accounts
      accountSel.innerHTML = "";
      window.ACCOUNTS.forEach(a => {
        const o = document.createElement("option");
        o.value = a.id;
        o.textContent = a.name;
        if (a.id === btn.dataset.account) o.selected = true;
        accountSel.appendChild(o);
      });

      await loadCategories(
        btn.dataset.type,
        btn.dataset.category,
        btn.dataset.subcategory
      );
    });
  });

  function closeModal() {
    modal.classList.add("hidden");
  }

  if (cancelBtn) {
    cancelBtn.addEventListener("click", closeModal);
  }
  if (cancelAlt) {
    cancelAlt.addEventListener("click", closeModal);
  }

  categorySel.addEventListener("change", () => {
    reset(subcategorySel, "-- Select Subcategory --");
    loadSubcategories(
      document.querySelector(".edit-transaction-btn").dataset.type,
      categorySel.value
    );
  });
});
