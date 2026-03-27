// Auto-Generate Account Name

document.addEventListener("DOMContentLoaded", () => {
  const bankInput = document.getElementById("bank_name");
  const typeSelect = document.getElementById("acc_type");
  const nameInput = document.getElementById("account_name");

  if (!bankInput || !typeSelect || !nameInput) {
    return;
  }

  let userEdited = false;

  function generateName() {
    if (userEdited) return;

    const bank = bankInput.value.trim();
    const type = typeSelect.value;

    if (!bank || !type) {
      nameInput.value = "";
      return;
    }

    const typeLabel =
      typeSelect.options[typeSelect.selectedIndex].text;

    nameInput.value = `${bank}-${typeLabel}`;
  }

  // Detect manual edits
  nameInput.addEventListener("input", () => {
    userEdited = true;
  });

  // Re-generate on change
  bankInput.addEventListener("input", generateName);
  typeSelect.addEventListener("change", generateName);
});

// Toggle Add Account Form
document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.getElementById("accountToggle");
  const form = document.getElementById("accountForm");
  if (!toggle || !form) return;
  toggle.addEventListener("click", () => {
    form.classList.toggle("account-form-collapsed");
    toggle.classList.toggle("open");
  });
});


// Edit Account Details

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".edit-btn").forEach((editBtn) => {
    editBtn.addEventListener("click", () => {
      const row = editBtn.closest("tr");

      // Enable editable fields
      row.querySelectorAll(".editable").forEach((input) => {
        input.disabled = false;
        input.classList.add("editing");
      });

      // Toggle buttons
      editBtn.style.display = "none";
      row.querySelector(".save-btn").style.display = "inline";
      row.querySelector(".cancel-btn").style.display = "inline";
      row.querySelector(".delete-btn").style.display = "none";
    });
  });

  document.querySelectorAll(".cancel-btn").forEach((cancelBtn) => {
    cancelBtn.addEventListener("click", () => {
      const row = cancelBtn.closest("tr");

      // Restore original values
      row.querySelectorAll(".editable").forEach((el) => {
        el.value = el.dataset.original;
        el.disabled = true;
        el.classList.remove("editing");
      });

      // Toggle buttons
      row.querySelector(".edit-btn").style.display = "inline";
      row.querySelector(".delete-btn").style.display = "inline";
      row.querySelector(".save-btn").style.display = "none";
      cancelBtn.style.display = "none";
    });
  });

});
