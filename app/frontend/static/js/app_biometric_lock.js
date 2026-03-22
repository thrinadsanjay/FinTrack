(function appBiometricLock() {
  const body = document.body;
  if (!body || !body.classList.contains("user-authenticated")) return;

  const isStandalone =
    (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
    window.navigator.standalone === true;
  if (!isStandalone) return;

  const userId = String(body.dataset.userId || "").trim();
  if (!userId) return;

  const unlockKey = `ft_bio_unlock_${userId}`;
  if (sessionStorage.getItem(unlockKey) === "ok") return;

  function getCsrfToken() {
    const tag = document.querySelector('meta[name="csrf-token"]');
    return tag ? tag.getAttribute("content") || "" : "";
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

  function toPublicKeyRequestOptions(options) {
    const publicKey = { ...options };
    publicKey.challenge = b64urlToArrayBuffer(options.challenge);
    if (Array.isArray(options.allowCredentials)) {
      publicKey.allowCredentials = options.allowCredentials.map((cred) => ({
        ...cred,
        id: b64urlToArrayBuffer(cred.id),
      }));
    }
    return publicKey;
  }

  function serializeAssertion(assertion) {
    return {
      id: assertion.id,
      rawId: arrayBufferToB64url(assertion.rawId),
      type: assertion.type,
      response: {
        authenticatorData: arrayBufferToB64url(assertion.response.authenticatorData),
        clientDataJSON: arrayBufferToB64url(assertion.response.clientDataJSON),
        signature: arrayBufferToB64url(assertion.response.signature),
        userHandle: assertion.response.userHandle
          ? arrayBufferToB64url(assertion.response.userHandle)
          : null,
      },
      clientExtensionResults: assertion.getClientExtensionResults ? assertion.getClientExtensionResults() : {},
    };
  }

  function createOverlay() {
    const overlay = document.createElement("div");
    overlay.className = "biometric-lock-overlay hidden";
    overlay.innerHTML = `
      <div class="biometric-lock-card" role="dialog" aria-modal="true" aria-labelledby="bio-lock-title" hidden>
        <h3 id="bio-lock-title">Unlock FinTracker</h3>
        <p class="biometric-lock-message" data-bio-lock-message>Use fingerprint or device biometric to continue.</p>
        <div class="biometric-lock-actions">
          <button type="button" class="primary-btn" data-bio-lock-retry>Unlock</button>
          <a href="/logout" class="ghost-btn" data-bio-lock-logout>Logout</a>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    return {
      root: overlay,
      message: overlay.querySelector("[data-bio-lock-message]"),
      retry: overlay.querySelector("[data-bio-lock-retry]"),
    };
  }

  const ui = createOverlay();

  function showOverlay(message) {
    if (message && ui.message) ui.message.textContent = message;
    ui.root.classList.remove("hidden");
    body.classList.add("biometric-lock-active");
  }

  function hideOverlay() {
    ui.root.classList.add("hidden");
    body.classList.remove("biometric-lock-active");
  }

  async function fetchUnlockStatus() {
    const resp = await fetch("/auth/passkey/unlock/status", {
      method: "GET",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) return { unlock_required: false };
    return data || {};
  }

  async function unlockWithBiometric() {
    const csrf = getCsrfToken();

    const optionsResp = await fetch("/auth/passkey/unlock/options", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
      },
      credentials: "same-origin",
      body: JSON.stringify({}),
    });
    const optionsData = await optionsResp.json().catch(() => ({}));
    if (!optionsResp.ok || !optionsData.options) {
      throw new Error((optionsData && optionsData.detail) || "Unable to start biometric unlock.");
    }

    const assertion = await navigator.credentials.get({
      publicKey: toPublicKeyRequestOptions(optionsData.options),
    });
    if (assertion == null) {
      throw new Error("Biometric verification was cancelled.");
    }

    const verifyResp = await fetch("/auth/passkey/unlock/verify", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
      },
      credentials: "same-origin",
      body: JSON.stringify({ credential: serializeAssertion(assertion) }),
    });
    const verifyData = await verifyResp.json().catch(() => ({}));
    if (!verifyResp.ok) {
      throw new Error((verifyData && verifyData.detail) || "Biometric verification failed.");
    }
  }

  async function beginUnlock(autoAttempt = false) {
    if (window.PublicKeyCredential == null || navigator.credentials == null || navigator.credentials.get == null) {
      showOverlay("Biometric is not supported on this device/browser. Please login again.");
      return;
    }

    showOverlay("Use fingerprint or device biometric to continue.");
    ui.retry.disabled = true;

    try {
      await unlockWithBiometric();
      sessionStorage.setItem(unlockKey, "ok");
      hideOverlay();
    } catch (error) {
      const fallbackMessage = autoAttempt
        ? "Biometric unlock required. Tap Unlock to try again."
        : "Unlock failed. Please try again.";
      showOverlay((error && error.message) || fallbackMessage);
    } finally {
      ui.retry.disabled = false;
    }
  }

  ui.retry.addEventListener("click", (event) => {
    event.preventDefault();
    beginUnlock(false);
  });

  (async function init() {
    try {
      const status = await fetchUnlockStatus();
      if (!status || !status.unlock_required) return;
      await beginUnlock(true);
    } catch (_error) {
      // If status call fails, do not block app.
    }
  })();
})();
