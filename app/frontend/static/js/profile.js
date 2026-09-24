(function () {
  var root = document.querySelector("[data-profile-page]");
  if (!root) return;

  function csrf() {
    return window.FinTrack && window.FinTrack.csrfToken
      ? window.FinTrack.csrfToken()
      : (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
  }

  function toast(message, type) {
    if (window.FinTrack && window.FinTrack.toast) {
      window.FinTrack.toast(message, type || "success");
      return;
    }
    window.alert(message);
  }

  async function postJson(url, body) {
    var res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf(),
      },
      body: JSON.stringify(Object.assign({ csrf_token: csrf() }, body || {})),
    });
    var data = {};
    try {
      data = await res.json();
    } catch (_err) {
      data = {};
    }
    if (!res.ok && res.status !== 202) {
      throw new Error(data.detail || "Request failed");
    }
    data.__status = res.status;
    return data;
  }

  /* ---------------- Telegram linking ---------------- */
  (function telegramLink() {
    var sendBtn = root.querySelector("[data-telegram-send]");
    if (!sendBtn) return;

    var mobileInput = root.querySelector("[data-telegram-mobile]");
    var otpRow = root.querySelector("[data-telegram-otp-row]");
    var otpInput = root.querySelector("[data-telegram-otp]");
    var verifyBtn = root.querySelector("[data-telegram-verify]");
    var statusEl = root.querySelector("[data-telegram-status]");
    var botLink = root.querySelector("[data-telegram-bot]");

    function setStatus(text, isError) {
      if (!statusEl) return;
      statusEl.hidden = !text;
      statusEl.textContent = text || "";
      statusEl.style.color = isError ? "var(--ft-negative)" : "var(--ft-accent-ink)";
    }

    sendBtn.addEventListener("click", async function () {
      var mobile = (mobileInput && mobileInput.value) || "";
      if (!mobile.trim()) {
        setStatus("Enter a mobile number.", true);
        return;
      }
      sendBtn.disabled = true;
      setStatus("Sending…");
      try {
        var data = await postJson("/profile/telegram/send-otp", { mobile: mobile.trim() });
        if (data.bot_url && botLink) botLink.href = data.bot_url;
        if (data.status === "awaiting_register" || data.__status === 202) {
          setStatus(
            data.detail || "Open the Telegram bot, send /register, then tap Send OTP again.",
            false
          );
          return;
        }
        if (otpRow) otpRow.hidden = false;
        setStatus("OTP sent to Telegram. Enter the 6-digit code.", false);
        if (otpInput) otpInput.focus();
      } catch (err) {
        setStatus(err.message || "Unable to send OTP.", true);
      } finally {
        sendBtn.disabled = false;
      }
    });

    if (verifyBtn) {
      verifyBtn.addEventListener("click", async function () {
        var otp = (otpInput && otpInput.value) || "";
        if (!/^\d{6}$/.test(otp.trim())) {
          setStatus("Enter the 6-digit OTP.", true);
          return;
        }
        verifyBtn.disabled = true;
        try {
          await postJson("/profile/telegram/verify-otp", { otp: otp.trim() });
          toast("Telegram linked", "success");
          window.location.href = "/profile#telegram";
          window.location.reload();
        } catch (err) {
          setStatus(err.message || "Verification failed.", true);
        } finally {
          verifyBtn.disabled = false;
        }
      });
    }
  })();

  var unlinkBtn = root.querySelector("[data-telegram-unlink]");
  if (unlinkBtn) {
    unlinkBtn.addEventListener("click", async function () {
      if (!window.confirm("Unlink Telegram from this account?")) return;
      unlinkBtn.disabled = true;
      try {
        await postJson("/profile/telegram/deregister", {});
        toast("Telegram unlinked", "success");
        window.location.reload();
      } catch (err) {
        toast(err.message || "Unable to unlink Telegram", "error");
        unlinkBtn.disabled = false;
      }
    });
  }

  /* ---------------- Passkeys / biometric ---------------- */
  (function passkeys() {
    var trigger = root.querySelector("[data-passkey-register]");
    if (!trigger) return;

    var biometricToggle = root.querySelector("[data-biometric-toggle]");
    var deleteAllBtn = root.querySelector("[data-biometric-delete-all]");
    var statusText = root.querySelector("[data-biometric-status-text]");
    var countText = root.querySelector("[data-biometric-count]");
    var controls = root.querySelector("[data-biometric-controls]");
    var passkeyCount = Number((controls && controls.getAttribute("data-passkey-count")) || "0") || 0;
    var biometricEnabled = String((controls && controls.getAttribute("data-biometric-enabled")) || "true") === "true";

    function updateCount(count) {
      passkeyCount = Number(count) || 0;
      if (countText) {
        countText.textContent =
          passkeyCount + " passkey" + (passkeyCount === 1 ? "" : "s");
        countText.classList.toggle("ft-badge--positive", passkeyCount > 0);
      }
      if (deleteAllBtn) deleteAllBtn.disabled = passkeyCount <= 0;
      trigger.disabled = false;
    }

    function setEnabled(enabled) {
      biometricEnabled = !!enabled && passkeyCount > 0;
      if (biometricToggle) {
        biometricToggle.checked = biometricEnabled;
        biometricToggle.disabled = passkeyCount <= 0;
      }
      var label = document.querySelector("[data-biometric-controls] .prf-toggle__label");
      if (statusText) {
        if (passkeyCount <= 0) {
          statusText.textContent = "Not registered — add a passkey before enabling biometric login.";
        } else if (biometricEnabled) {
          statusText.textContent = "Biometric login is enabled.";
        } else {
          statusText.textContent = "Passkeys are registered but biometric login is disabled.";
        }
      }
      if (label) {
        label.textContent = passkeyCount <= 0 ? "Not registered" : biometricEnabled ? "Enabled" : "Disabled";
      }
      updateCount(passkeyCount);
    }

    function b64urlToArrayBuffer(value) {
      var padded =
        value.replace(/-/g, "+").replace(/_/g, "/") +
        "=".repeat((4 - (value.length % 4)) % 4);
      var binary = atob(padded);
      var bytes = new Uint8Array(binary.length);
      for (var i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
      return bytes.buffer;
    }

    function arrayBufferToB64url(buffer) {
      var bytes = new Uint8Array(buffer);
      var binary = "";
      for (var i = 0; i < bytes.byteLength; i += 1) binary += String.fromCharCode(bytes[i]);
      return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
    }

    function toCreateOptions(options) {
      var publicKey = Object.assign({}, options);
      publicKey.challenge = b64urlToArrayBuffer(options.challenge);
      publicKey.user = Object.assign({}, options.user, {
        id: b64urlToArrayBuffer(options.user.id),
      });
      if (Array.isArray(options.excludeCredentials)) {
        publicKey.excludeCredentials = options.excludeCredentials.map(function (cred) {
          return Object.assign({}, cred, { id: b64urlToArrayBuffer(cred.id) });
        });
      }
      return publicKey;
    }

    function serializeAttestation(credential) {
      var transports = credential.response.getTransports
        ? credential.response.getTransports()
        : [];
      return {
        id: credential.id,
        rawId: arrayBufferToB64url(credential.rawId),
        type: credential.type,
        response: {
          attestationObject: arrayBufferToB64url(credential.response.attestationObject),
          clientDataJSON: arrayBufferToB64url(credential.response.clientDataJSON),
          transports: transports,
        },
        clientExtensionResults: credential.getClientExtensionResults
          ? credential.getClientExtensionResults()
          : {},
      };
    }

    async function registerPasskey() {
      if (!window.PublicKeyCredential || !navigator.credentials || !navigator.credentials.create) {
        toast("Passkeys are not supported on this browser/device.", "error");
        return false;
      }
      trigger.disabled = true;
      try {
        var optionsData = await postJson("/profile/passkeys/register/options", {});
        var credential = await navigator.credentials.create({
          publicKey: toCreateOptions(optionsData.options || {}),
        });
        if (!credential) throw new Error("Registration was cancelled.");
        var name =
          window.prompt("Passkey name (optional)", "Device passkey " + (passkeyCount + 1)) || "";
        var verifyData = await postJson("/profile/passkeys/register/verify", {
          name: name,
          credential: serializeAttestation(credential),
        });
        updateCount((verifyData && verifyData.passkey_count) || passkeyCount + 1);
        toast("Passkey registered", "success");
        return true;
      } catch (err) {
        toast(err.message || "Unable to register passkey", "error");
        return false;
      } finally {
        setEnabled(biometricEnabled);
      }
    }

    trigger.addEventListener("click", function (event) {
      event.preventDefault();
      registerPasskey();
    });

    if (biometricToggle) {
      biometricToggle.addEventListener("change", async function () {
        var wantsEnabled = !!biometricToggle.checked;
        try {
          if (!wantsEnabled) {
            if (!window.confirm("Disable biometric login for your account?")) {
              biometricToggle.checked = true;
              return;
            }
            var disabled = await postJson("/profile/passkeys/disable", {});
            setEnabled(Boolean(disabled.biometric_enabled));
            updateCount(disabled.passkey_count || 0);
            toast("Biometric login disabled", "success");
            return;
          }
          var enabled = await postJson("/profile/passkeys/enable", {});
          setEnabled(Boolean(enabled.biometric_enabled));
          updateCount(enabled.passkey_count || 0);
          toast("Biometric login enabled", "success");
          if ((enabled.passkey_count || 0) === 0) await registerPasskey();
        } catch (err) {
          biometricToggle.checked = !wantsEnabled;
          toast(err.message || "Unable to update biometric setting", "error");
        }
      });
    }

    if (deleteAllBtn) {
      deleteAllBtn.addEventListener("click", async function (event) {
        event.preventDefault();
        if (!window.confirm("Delete all registered passkeys?")) return;
        try {
          var data = await postJson("/profile/passkeys/delete-all", {});
          updateCount(data.passkey_count || 0);
          setEnabled(Boolean(data.biometric_enabled));
          toast("All passkeys deleted", "success");
        } catch (err) {
          toast(err.message || "Unable to delete passkeys", "error");
        }
      });
    }

    updateCount(passkeyCount);
    setEnabled(biometricEnabled);
  })();

  /* Password visibility toggles */
  root.querySelectorAll("[data-toggle-password]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var id = btn.getAttribute("data-toggle-password");
      var input = id ? document.getElementById(id) : null;
      if (!input) return;
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      var icon = btn.querySelector("i");
      if (icon) {
        icon.className = show ? "fa-regular fa-eye-slash" : "fa-regular fa-eye";
      }
      btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
    });
  });

  /* Smooth-scroll to hash sections from the profile menu */
  if (window.location.hash) {
    var target = document.querySelector(window.location.hash);
    if (target) {
      setTimeout(function () {
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 60);
    }
  }
})();
