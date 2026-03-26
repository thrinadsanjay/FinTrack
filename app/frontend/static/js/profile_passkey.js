(function profilePasskey() {
  const trigger = document.querySelector("[data-passkey-register]");
  if (trigger == null) return;

  const biometricControls = document.querySelector("[data-biometric-controls]");
  const biometricToggle = document.querySelector("[data-biometric-toggle]");
  const deleteAllBtn = document.querySelector("[data-biometric-delete-all]");
  const statusText = document.querySelector("[data-biometric-status-text]");
  const countText = document.querySelector("[data-biometric-count]");

  const modal = document.querySelector("[data-biometric-modal]");
  const modalTitle = modal?.querySelector("[data-biometric-modal-title]");
  const modalMessage = modal?.querySelector("[data-biometric-modal-message]");
  const modalConfirm = modal?.querySelector("[data-biometric-modal-confirm]");
  const modalCancel = modal?.querySelector("[data-biometric-modal-cancel]");
  const modalCloseButtons = modal?.querySelectorAll("[data-biometric-modal-close]") || [];

  function getCsrfToken() {
    const tag = document.querySelector('meta[name="csrf-token"]');
    return tag ? tag.getAttribute("content") || "" : "";
  }

  function showBiometricModal({ title, message, confirmText = "OK", cancelText = "Cancel", showCancel = false }) {
    if (!modal || !modalTitle || !modalMessage || !modalConfirm || !modalCancel) {
      if (showCancel) return Promise.resolve(window.confirm(message || title || "Confirm"));
      window.alert(message || title || "Done");
      return Promise.resolve(true);
    }

    modalTitle.textContent = title || "Biometric Login";
    modalMessage.textContent = message || "";
    modalConfirm.textContent = confirmText;
    modalCancel.textContent = cancelText;
    modalCancel.classList.toggle("hidden", !showCancel);
    modal.classList.remove("hidden");

    return new Promise((resolve) => {
      let settled = false;

      function cleanup(result) {
        if (settled) return;
        settled = true;
        modal.classList.add("hidden");
        modalConfirm.removeEventListener("click", onConfirm);
        modalCancel.removeEventListener("click", onCancel);
        modalCloseButtons.forEach((btn) => btn.removeEventListener("click", onCancel));
        modal.removeEventListener("click", onBackdrop);
        document.removeEventListener("keydown", onEsc);
        resolve(result);
      }

      function onConfirm(event) {
        event.preventDefault();
        cleanup(true);
      }

      function onCancel(event) {
        event?.preventDefault();
        cleanup(false);
      }

      function onBackdrop(event) {
        if (event.target === modal) cleanup(false);
      }

      function onEsc(event) {
        if (event.key === "Escape") cleanup(false);
      }

      modalConfirm.addEventListener("click", onConfirm);
      modalCancel.addEventListener("click", onCancel);
      modalCloseButtons.forEach((btn) => btn.addEventListener("click", onCancel));
      modal.addEventListener("click", onBackdrop);
      document.addEventListener("keydown", onEsc);

      if (showCancel) {
        modalCancel.focus();
      } else {
        modalConfirm.focus();
      }
    });
  }

  async function notify(title, message) {
    await showBiometricModal({ title, message, confirmText: "OK", showCancel: false });
  }

  async function confirmAction(title, message, confirmText = "Confirm") {
    return showBiometricModal({
      title,
      message,
      confirmText,
      cancelText: "Cancel",
      showCancel: true,
    });
  }

  function getPasskeyCount() {
    return Number(trigger.dataset.passkeyCount || "0");
  }

  function getBiometricEnabled() {
    const value = String(trigger.dataset.biometricEnabled || "true").toLowerCase();
    return value === "true";
  }

  function setBiometricEnabled(enabled) {
    const raw = enabled ? "true" : "false";
    trigger.dataset.biometricEnabled = raw;
    if (biometricControls) biometricControls.dataset.biometricEnabled = raw;
    if (biometricToggle) biometricToggle.checked = enabled;
  }

  function updatePasskeyCount(count) {
    const safeCount = Number.isFinite(Number(count)) ? Number(count) : 0;
    trigger.dataset.passkeyCount = String(safeCount);
    if (biometricControls) biometricControls.dataset.passkeyCount = String(safeCount);
    trigger.textContent = safeCount > 0 ? "Add Another Fingerprint" : "Register Fingerprint";
    if (countText) countText.textContent = String(safeCount);
    if (deleteAllBtn) deleteAllBtn.disabled = safeCount <= 0;
  }

  function syncBiometricUi() {
    const enabled = getBiometricEnabled();
    const count = getPasskeyCount();
    trigger.disabled = !enabled;
    if (deleteAllBtn) deleteAllBtn.disabled = count <= 0;
    if (statusText) statusText.textContent = enabled ? "Enabled" : "Disabled";
    if (countText) countText.textContent = String(count);
    if (biometricToggle) biometricToggle.checked = enabled;
  }

  function b64urlToArrayBuffer(value) {
    const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (value.length % 4)) % 4);
    const binary = atob(padded);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes.buffer;
  }

  function arrayBufferToB64url(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let i = 0; i < bytes.byteLength; i += 1) binary += String.fromCharCode(bytes[i]);
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  }

  function toCreateOptions(options) {
    const publicKey = { ...options };
    publicKey.challenge = b64urlToArrayBuffer(options.challenge);
    publicKey.user = { ...options.user, id: b64urlToArrayBuffer(options.user.id) };
    if (Array.isArray(options.excludeCredentials)) {
      publicKey.excludeCredentials = options.excludeCredentials.map((cred) => ({
        ...cred,
        id: b64urlToArrayBuffer(cred.id),
      }));
    }
    return publicKey;
  }

  function serializeAttestation(credential) {
    const transports = credential.response.getTransports ? credential.response.getTransports() : [];
    return {
      id: credential.id,
      rawId: arrayBufferToB64url(credential.rawId),
      type: credential.type,
      response: {
        attestationObject: arrayBufferToB64url(credential.response.attestationObject),
        clientDataJSON: arrayBufferToB64url(credential.response.clientDataJSON),
        transports,
      },
      clientExtensionResults: credential.getClientExtensionResults ? credential.getClientExtensionResults() : {},
    };
  }

  async function postJson(url, body) {
    const csrf = getCsrfToken();
    const resp = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
      },
      credentials: "same-origin",
      body: JSON.stringify(body || {}),
    });
    const data = await resp.json().catch(() => ({}));
    if (resp.ok === false) {
      throw new Error((data && data.detail) || "Request failed.");
    }
    return data;
  }

  async function registerPasskey() {
    if (!getBiometricEnabled()) {
      await notify("Biometric Login", "Biometric login is disabled. Enable it from Profile menu.");
      return false;
    }

    if (window.PublicKeyCredential == null || navigator.credentials == null || navigator.credentials.create == null) {
      await notify("Biometric Login", "Passkey is not supported on this browser/device.");
      return false;
    }

    trigger.disabled = true;
    try {
      const optionsData = await postJson("/profile/passkeys/register/options", {});
      const credential = await navigator.credentials.create({
        publicKey: toCreateOptions(optionsData.options || {}),
      });
      if (credential == null) {
        throw new Error("Fingerprint registration was cancelled.");
      }

      const suggested = `Mobile Passkey ${String(trigger.dataset.passkeyCount || "0")}`;
      const name = window.prompt("Passkey name (optional)", suggested || "Mobile Passkey") || "";
      const verifyData = await postJson("/profile/passkeys/register/verify", {
        name,
        credential: serializeAttestation(credential),
      });

      updatePasskeyCount((verifyData && verifyData.passkey_count) || 0);
      await notify("Biometric Login", "Fingerprint registered successfully.");
      return true;
    } catch (error) {
      await notify("Biometric Login", (error && error.message) || "Unable to register fingerprint.");
      return false;
    } finally {
      syncBiometricUi();
    }
  }

  async function setBiometricState(url, enabledText) {
    const data = await postJson(url, {});
    setBiometricEnabled(Boolean(data && data.biometric_enabled));
    updatePasskeyCount((data && data.passkey_count) || 0);
    syncBiometricUi();
    await notify("Biometric Login", enabledText);
    return data;
  }

  trigger.addEventListener("click", (event) => {
    event.preventDefault();
    registerPasskey();
  });

  if (biometricToggle) {
    biometricToggle.addEventListener("change", async () => {
      const wantsEnabled = Boolean(biometricToggle.checked);

      if (!wantsEnabled) {
        const confirmed = await confirmAction(
          "Disable Biometric Login",
          "Disable biometric login for your account?",
          "Disable"
        );
        if (!confirmed) {
          biometricToggle.checked = true;
          return;
        }

        try {
          await setBiometricState("/profile/passkeys/disable", "Biometric login disabled.");
        } catch (error) {
          await notify("Biometric Login", (error && error.message) || "Unable to disable biometric login.");
          biometricToggle.checked = true;
        }
        return;
      }

      try {
        const data = await setBiometricState("/profile/passkeys/enable", "Biometric login enabled.");
        const count = Number((data && data.passkey_count) || 0);
        if (count === 0) {
          await registerPasskey();
        }
      } catch (error) {
        await notify("Biometric Login", (error && error.message) || "Unable to enable biometric login.");
        biometricToggle.checked = false;
      }
    });
  }

  if (deleteAllBtn) {
    deleteAllBtn.addEventListener("click", async (event) => {
      event.preventDefault();
      const confirmed = await confirmAction(
        "Delete Biometrics",
        "Delete all registered biometrics/passkeys from your account?",
        "Delete"
      );
      if (!confirmed) return;

      try {
        const data = await postJson("/profile/passkeys/delete-all", {});
        updatePasskeyCount((data && data.passkey_count) || 0);
        setBiometricEnabled(Boolean(data && data.biometric_enabled));
        syncBiometricUi();
        await notify("Delete Biometrics", "All registered biometrics were deleted.");
      } catch (error) {
        await notify("Delete Biometrics", (error && error.message) || "Unable to delete biometrics.");
      }
    });
  }

  syncBiometricUi();
})();
