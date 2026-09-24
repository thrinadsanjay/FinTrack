(function () {
  var root = document.querySelector("[data-login-page]");
  if (!root) return;

  var localPanel = root.querySelector("[data-local-panel]");
  var telegramPanel = root.querySelector("[data-telegram-panel]");
  var localToggle = root.querySelector("[data-local-toggle]");
  var telegramToggle = root.querySelector("[data-telegram-open]");

  function showLocal() {
    if (localPanel) localPanel.hidden = false;
    if (telegramPanel) telegramPanel.hidden = true;
    if (localToggle) localToggle.classList.add("is-active");
    if (telegramToggle) telegramToggle.classList.remove("is-active");
  }

  function showTelegram() {
    if (localPanel) localPanel.hidden = true;
    if (telegramPanel) telegramPanel.hidden = false;
    if (localToggle) localToggle.classList.remove("is-active");
    if (telegramToggle) telegramToggle.classList.add("is-active");
  }

  if (localToggle) localToggle.addEventListener("click", showLocal);
  if (telegramToggle) telegramToggle.addEventListener("click", showTelegram);

  root.querySelectorAll("[data-password-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var input = btn.parentElement.querySelector("input");
      if (!input) return;
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      var icon = btn.querySelector("i");
      if (icon) {
        icon.className = show ? "fa-regular fa-eye-slash" : "fa-regular fa-eye";
      }
    });
  });

  var passkeyBtn = root.querySelector("[data-passkey-login]");
  if (passkeyBtn) {
    passkeyBtn.addEventListener("click", async function () {
      try {
        var usernameInput = document.getElementById("username");
        var username = usernameInput ? usernameInput.value.trim() : "";
        var optionsRes = await fetch("/login/passkey/options", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": window.FinTrack.csrfToken(),
          },
          body: JSON.stringify({ username: username || null }),
        });
        var optionsPayload = await optionsRes.json();
        if (!optionsRes.ok) {
          throw new Error(optionsPayload.detail || "Passkey options failed");
        }
        if (!window.PublicKeyCredential) {
          throw new Error("Passkeys are not supported on this device");
        }
        // Minimal discoverable flow — full WebAuthn decode lives in a later pass.
        window.FinTrack.toast(
          "Passkey challenge issued. Complete biometric prompt when available.",
          "success"
        );
        var verifyRes = await fetch("/login/passkey/verify", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": window.FinTrack.csrfToken(),
          },
          body: JSON.stringify({
            credential: null,
            options: optionsPayload.options,
          }),
        });
        var verifyPayload = await verifyRes.json();
        if (!verifyRes.ok) {
          throw new Error(verifyPayload.detail || "Passkey verify failed");
        }
        window.location.href = verifyPayload.redirect || "/";
      } catch (err) {
        window.FinTrack.toast(err.message || "Passkey login failed", "error");
      }
    });
  }
})();
