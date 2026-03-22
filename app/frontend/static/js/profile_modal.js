(function profileModals() {
  const passwordModal = document.querySelector("[data-reset-password-modal]");
  const passwordOpenButtons = document.querySelectorAll("[data-reset-password-open]");
  const passwordCloseButtons = document.querySelectorAll("[data-reset-password-close]");
  const passwordForm = passwordModal?.querySelector("[data-reset-password-form]");

  function openPasswordModal() {
    if (!passwordModal) return;
    passwordModal.classList.remove("hidden");
    const firstInput = passwordForm?.querySelector("input[name='current_password']");
    if (firstInput) firstInput.focus();
  }

  function closePasswordModal() {
    if (!passwordModal) return;
    passwordModal.classList.add("hidden");
  }

  passwordOpenButtons.forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      openPasswordModal();
    });
  });

  passwordCloseButtons.forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      closePasswordModal();
    });
  });

  if (passwordModal) {
    passwordModal.addEventListener("click", (event) => {
      if (event.target === passwordModal) {
        closePasswordModal();
      }
    });

    const shouldOpen = String(passwordModal.dataset.resetPasswordOpenState || "").toLowerCase() === "true";
    if (shouldOpen) {
      openPasswordModal();
    }
  }

  const accountActionModal = document.querySelector("[data-account-action-modal]");
  const accountActionForms = document.querySelectorAll("[data-account-action-form]");
  const actionTitle = accountActionModal?.querySelector("[data-account-action-title]");
  const actionMessage = accountActionModal?.querySelector("[data-account-action-message]");
  const actionConfirmBtn = accountActionModal?.querySelector("[data-account-action-confirm]");
  const actionCloseButtons = accountActionModal?.querySelectorAll("[data-account-action-close]") || [];
  const actionVerifyWrap = accountActionModal?.querySelector("[data-account-action-verify-wrap]");
  const actionVerifyInput = accountActionModal?.querySelector("[data-account-action-verify-input]");

  let pendingForm = null;

  function isDeleteVerified() {
    return String(actionVerifyInput?.value || "").trim().toUpperCase() === "DELETE";
  }

  function syncDeleteConfirmState() {
    if (!actionConfirmBtn) return;
    const actionType = String(pendingForm?.dataset.accountActionType || "").toLowerCase();
    if (actionType !== "delete") {
      actionConfirmBtn.disabled = false;
      return;
    }
    actionConfirmBtn.disabled = !isDeleteVerified();
  }

  function openAccountActionModal(form) {
    if (!accountActionModal || !form || !actionTitle || !actionMessage || !actionConfirmBtn) return;

    const type = String(form.dataset.accountActionType || "").toLowerCase();
    actionTitle.textContent = form.dataset.accountActionTitle || "Confirm Action";
    actionMessage.textContent = form.dataset.accountActionMessage || "Please confirm this action.";
    actionConfirmBtn.textContent = form.dataset.accountActionConfirm || "Confirm";

    actionConfirmBtn.classList.remove("warning", "critical");
    if (type === "delete") {
      actionConfirmBtn.classList.add("critical");
      if (actionVerifyWrap) actionVerifyWrap.classList.remove("hidden");
      if (actionVerifyInput) actionVerifyInput.value = "";
    } else {
      actionConfirmBtn.classList.add("warning");
      if (actionVerifyWrap) actionVerifyWrap.classList.add("hidden");
      if (actionVerifyInput) actionVerifyInput.value = "";
    }

    pendingForm = form;
    syncDeleteConfirmState();
    accountActionModal.classList.remove("hidden");

    if (type === "delete" && actionVerifyInput) {
      actionVerifyInput.focus();
    } else {
      actionConfirmBtn.focus();
    }
  }

  function closeAccountActionModal() {
    if (!accountActionModal) return;
    pendingForm = null;
    if (actionVerifyInput) actionVerifyInput.value = "";
    if (actionVerifyWrap) actionVerifyWrap.classList.add("hidden");
    if (actionConfirmBtn) actionConfirmBtn.disabled = false;
    accountActionModal.classList.add("hidden");
  }

  accountActionForms.forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      openAccountActionModal(form);
    });
  });

  if (actionVerifyInput) {
    actionVerifyInput.addEventListener("input", () => {
      syncDeleteConfirmState();
    });
  }

  actionCloseButtons.forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      closeAccountActionModal();
    });
  });

  if (actionConfirmBtn) {
    actionConfirmBtn.addEventListener("click", () => {
      if (!pendingForm) return;

      const actionType = String(pendingForm.dataset.accountActionType || "").toLowerCase();
      if (actionType === "delete" && !isDeleteVerified()) {
        if (actionVerifyInput) actionVerifyInput.focus();
        return;
      }

      const formToSubmit = pendingForm;
      closeAccountActionModal();
      formToSubmit.submit();
    });
  }

  if (accountActionModal) {
    accountActionModal.addEventListener("click", (event) => {
      if (event.target === accountActionModal) {
        closeAccountActionModal();
      }
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;

    if (accountActionModal && !accountActionModal.classList.contains("hidden")) {
      closeAccountActionModal();
      return;
    }

    if (passwordModal && !passwordModal.classList.contains("hidden")) {
      closePasswordModal();
    }
  });
})();
