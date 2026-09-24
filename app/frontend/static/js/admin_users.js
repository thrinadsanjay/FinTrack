(() => {
  const root = document.querySelector('[data-admin-view="users"]');
  if (!root) return;

  const search = root.querySelector("[data-users-search]");
  const filters = Array.from(root.querySelectorAll("[data-users-filter]"));
  const rows = Array.from(root.querySelectorAll("[data-user-row]"));
  const empty = root.querySelector("[data-users-empty]");
  const createDialog = document.querySelector("[data-users-dialog]");
  const editDialog = document.querySelector("[data-users-edit-dialog]");
  const resetDialog = document.querySelector("[data-users-reset-dialog]");
  const deleteDialog = document.querySelector("[data-users-delete-dialog]");
  const addBtn = root.querySelector("[data-users-add]");
  const createForm = document.querySelector("[data-users-create-form]");
  const editForm = document.querySelector("[data-users-edit-form]");
  const resetForm = document.querySelector("[data-users-reset-form]");
  const deleteForm = document.querySelector("[data-users-delete-form]");
  let activeFilter = "all";
  let openMenu = null;

  function toast(message, tone) {
    if (typeof window.FinTrack?.toast === "function") {
      window.FinTrack.toast(message, tone);
    }
  }

  function matchesFilter(row) {
    const active = row.getAttribute("data-user-active") === "1";
    const admin = row.getAttribute("data-user-admin") === "1";
    if (activeFilter === "enabled") return active;
    if (activeFilter === "disabled") return !active;
    if (activeFilter === "admins") return admin;
    return true;
  }

  function matchesSearch(row) {
    const query = String(search?.value || "").trim().toLowerCase();
    if (!query) return true;
    return String(row.getAttribute("data-user-search") || "").toLowerCase().includes(query);
  }

  function applyFilters() {
    let visible = 0;
    rows.forEach((row) => {
      const show = matchesFilter(row) && matchesSearch(row);
      row.hidden = !show;
      if (show) visible += 1;
    });
    if (empty instanceof HTMLElement) empty.hidden = visible > 0 || rows.length === 0;
  }

  function closeMenus(except) {
    root.querySelectorAll("[data-users-menu]").forEach((menu) => {
      if (menu === except) return;
      menu.classList.remove("is-open");
      const panel = menu.querySelector(".users-menu__panel");
      const trigger = menu.querySelector("[data-users-menu-trigger]");
      if (panel instanceof HTMLElement) {
        panel.hidden = true;
        panel.style.top = "";
        panel.style.right = "";
        panel.style.bottom = "";
        panel.style.left = "";
      }
      if (trigger instanceof HTMLElement) trigger.setAttribute("aria-expanded", "false");
    });
    openMenu = except || null;
  }

  function positionMenuPanel(menu) {
    const trigger = menu.querySelector("[data-users-menu-trigger]");
    const panel = menu.querySelector(".users-menu__panel");
    if (!(trigger instanceof HTMLElement) || !(panel instanceof HTMLElement)) return;

    const rect = trigger.getBoundingClientRect();
    const gap = 8;
    const estimatedHeight = panel.offsetHeight || 260;
    const spaceBelow = window.innerHeight - rect.bottom - gap;
    const openUp = spaceBelow < estimatedHeight && rect.top > spaceBelow;

    panel.style.left = "auto";
    panel.style.right = `${Math.max(12, window.innerWidth - rect.right)}px`;
    if (openUp) {
      panel.style.top = "auto";
      panel.style.bottom = `${Math.max(12, window.innerHeight - rect.top + gap)}px`;
    } else {
      panel.style.bottom = "auto";
      panel.style.top = `${rect.bottom + gap}px`;
    }
  }

  function openMenuPanel(menu) {
    closeMenus(menu);
    menu.classList.add("is-open");
    const panel = menu.querySelector(".users-menu__panel");
    const trigger = menu.querySelector("[data-users-menu-trigger]");
    if (panel instanceof HTMLElement) {
      panel.hidden = false;
      positionMenuPanel(menu);
    }
    if (trigger instanceof HTMLElement) trigger.setAttribute("aria-expanded", "true");
    openMenu = menu;
  }

  function openDialog(dialog) {
    if (!(dialog instanceof HTMLDialogElement)) return;
    if (dialog.parentElement !== document.body) {
      document.body.appendChild(dialog);
    }
    try {
      if (!dialog.open) dialog.showModal();
    } catch (_err) {
      dialog.setAttribute("open", "");
    }
  }

  function closeDialog(dialog) {
    if (!(dialog instanceof HTMLDialogElement)) return;
    if (dialog.open) dialog.close();
    else dialog.removeAttribute("open");
  }

  function bindDialogClose(dialog) {
    if (!(dialog instanceof HTMLDialogElement)) return;
    dialog.querySelectorAll("[data-dialog-close]").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.preventDefault();
        closeDialog(dialog);
      });
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) closeDialog(dialog);
    });
  }

  function setFormAction(form, path) {
    if (form instanceof HTMLFormElement) form.setAttribute("action", path);
  }

  function readRow(row) {
    return {
      id: String(row.getAttribute("data-user-id") || "").trim(),
      username: row.getAttribute("data-user-username") || "",
      firstName: row.getAttribute("data-user-first-name") || "",
      lastName: row.getAttribute("data-user-last-name") || "",
      email: row.getAttribute("data-user-email") || "",
      phone: row.getAttribute("data-user-phone") || "",
      provider: row.getAttribute("data-user-provider") || "local",
      active: row.getAttribute("data-user-active") === "1",
      admin: row.getAttribute("data-user-admin") === "1",
      local: row.getAttribute("data-user-local") === "1",
      canDisable: row.getAttribute("data-user-can-disable") === "1",
      canDelete: row.getAttribute("data-user-can-delete") === "1",
    };
  }

  function openCreateDialog() {
    createForm?.reset();
    const resetToggle = createForm?.querySelector('[name="must_reset_password"]');
    if (resetToggle instanceof HTMLInputElement) resetToggle.checked = true;
    openDialog(createDialog);
    createForm?.querySelector('[name="username"]')?.focus();
  }

  function openEditDialog(row) {
    const user = readRow(row);
    if (!(editForm instanceof HTMLFormElement) || !user.id) return;
    setFormAction(editForm, `/admin/users/${user.id}/update`);
    editForm.reset();
    const usernameInput = editForm.querySelector("[data-users-edit-username]");
    const firstNameInput = editForm.querySelector('[name="first_name"]');
    const lastNameInput = editForm.querySelector('[name="last_name"]');
    const emailInput = editForm.querySelector('[name="email"]');
    const phoneInput = editForm.querySelector('[name="phone"]');
    if (usernameInput instanceof HTMLInputElement) usernameInput.value = user.username;
    if (firstNameInput instanceof HTMLInputElement) firstNameInput.value = user.firstName;
    if (lastNameInput instanceof HTMLInputElement) lastNameInput.value = user.lastName;
    if (emailInput instanceof HTMLInputElement) emailInput.value = user.email;
    if (phoneInput instanceof HTMLInputElement) phoneInput.value = user.phone;
    openDialog(editDialog);
    firstNameInput?.focus();
  }

  function openResetDialog(row) {
    const user = readRow(row);
    if (!(resetForm instanceof HTMLFormElement) || !user.id) return;
    setFormAction(resetForm, `/admin/users/${user.id}/reset-password`);
    resetForm.reset();
    const target = resetForm.querySelector("[data-users-reset-target]");
    const resetToggle = resetForm.querySelector('[name="must_reset_password"]');
    if (target instanceof HTMLElement) {
      target.textContent = `Set a new password for ${user.username || user.email || "this user"}.`;
    }
    if (resetToggle instanceof HTMLInputElement) resetToggle.checked = true;
    openDialog(resetDialog);
    resetForm.querySelector('[name="password"]')?.focus();
  }

  function openDeleteDialog(row) {
    const user = readRow(row);
    if (!(deleteForm instanceof HTMLFormElement) || !user.id) return;
    setFormAction(deleteForm, `/admin/users/${user.id}/delete`);
    const target = deleteForm.querySelector("[data-users-delete-target]");
    if (target instanceof HTMLElement) {
      target.textContent = `Delete ${user.username || user.email || "this user"}? They will lose access immediately.`;
    }
    openDialog(deleteDialog);
  }

  function bindPasswordConfirm(form) {
    form?.addEventListener("submit", (event) => {
      const password = String(form.querySelector('[name="password"]')?.value || "");
      const confirm = String(form.querySelector('[name="confirm_password"]')?.value || "");
      if (password !== confirm) {
        event.preventDefault();
        toast("Passwords do not match.", "error");
      }
    });
  }

  search?.addEventListener("input", applyFilters);
  filters.forEach((btn) => {
    btn.addEventListener("click", () => {
      activeFilter = String(btn.getAttribute("data-users-filter") || "all");
      filters.forEach((item) => {
        const on = item === btn;
        item.classList.toggle("is-active", on);
        item.setAttribute("aria-pressed", on ? "true" : "false");
      });
      applyFilters();
    });
  });

  addBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    openCreateDialog();
  });
  [createDialog, editDialog, resetDialog, deleteDialog].forEach(bindDialogClose);
  bindPasswordConfirm(createForm);
  bindPasswordConfirm(resetForm);

  root.querySelectorAll("[data-users-menu]").forEach((menu) => {
    const trigger = menu.querySelector("[data-users-menu-trigger]");
    trigger?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (menu.classList.contains("is-open")) closeMenus();
      else openMenuPanel(menu);
    });
  });

  root.querySelectorAll("[data-user-action]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const action = btn.getAttribute("data-user-action");
      if (action === "submit-form") {
        const form = btn.closest("form");
        closeMenus();
        if (form instanceof HTMLFormElement) form.submit();
        return;
      }
      const row = btn.closest("[data-user-row]");
      if (!(row instanceof HTMLElement)) return;
      closeMenus();
      if (action === "edit") openEditDialog(row);
      if (action === "reset-password") openResetDialog(row);
      if (action === "delete") openDeleteDialog(row);
    });
  });

  document.addEventListener("click", (event) => {
    if (!(event.target instanceof Node) || !openMenu) return;
    if (openMenu.contains(event.target)) return;
    closeMenus();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenus();
  });

  window.addEventListener("resize", () => {
    if (openMenu) positionMenuPanel(openMenu);
  });
})();
