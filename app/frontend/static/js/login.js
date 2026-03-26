// Login page helpers.

function togglePassword() {
  const input = document.getElementById("password");
  if (input == null) return;
  input.type = input.type === "password" ? "text" : "password";
}

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

async function autoPasskeyLogin() {
  if (window.PublicKeyCredential == null || navigator.credentials == null || navigator.credentials.get == null) {
    return;
  }

  const csrf = getCsrfToken();
  try {
    const optionsResp = await fetch("/login/passkey/options", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
      },
      credentials: "same-origin",
      body: JSON.stringify({}),
    });
    const optionsData = await optionsResp.json();
    if (optionsResp.ok === false || (optionsData && optionsData.options) == null) {
      return;
    }

    const assertion = await navigator.credentials.get({
      publicKey: toPublicKeyRequestOptions(optionsData.options),
    });
    if (assertion == null) {
      return;
    }

    const verifyResp = await fetch("/login/passkey/verify", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
      },
      credentials: "same-origin",
      body: JSON.stringify({ credential: serializeAssertion(assertion) }),
    });
    const verifyData = await verifyResp.json();
    if (verifyResp.ok === false) {
      return;
    }

    window.location.replace((verifyData && verifyData.redirect) || "/");
  } catch (_error) {
    // Silent fallback to regular username/password login form.
  }
}

(function initLoginPage() {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", autoPasskeyLogin, { once: true });
  } else {
    autoPasskeyLogin();
  }
})();
