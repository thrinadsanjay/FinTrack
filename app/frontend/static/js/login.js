function togglePassword(button) {
  const field = button?.closest(".password-field")?.querySelector("input");
  if (!field) return;
  const isHidden = field.type === "password";
  field.type = isHidden ? "text" : "password";
  const icon = button.querySelector("i");
  if (icon) {
    icon.className = isHidden ? "fa-regular fa-eye-slash" : "fa-regular fa-eye";
  }
  button.setAttribute("aria-label", isHidden ? "Hide password" : "Show password");
}

function normalizeDigits(value) {
  return (value || "").replace(/\D+/g, "").trim();
}

function syncPhoneGroup(container) {
  if (!container) return;
  const country = container.querySelector("[data-phone-country]");
  const local = container.querySelector("[data-phone-local]");
  const full = container.querySelector("[data-phone-full]");
  const hiddenCountry = container.querySelector("[data-phone-country-hidden]");
  if (!local || !full) return;

  const selectedOption = country?.selectedOptions?.[0];
  const countryValue = selectedOption?.dataset.countryCode || "";
  const localValue = normalizeDigits(local.value);
  local.value = localValue;
  full.value = countryValue && localValue ? `+${countryValue}${localValue}` : localValue;
  if (hiddenCountry && country) hiddenCountry.value = country.value;
}

function setPanel(panel, open) {
  if (!panel) return;
  panel.hidden = !open;
}

function setSwitcherState(root, active) {
  root.querySelectorAll(".login-switcher__button").forEach((button) => {
    const isLocal = button.hasAttribute("data-local-toggle");
    const shouldActivate = active === "local" ? isLocal : !isLocal;
    button.classList.toggle("is-active", shouldActivate);
    button.setAttribute("aria-selected", shouldActivate ? "true" : "false");
  });
}

function openLocalPanel(root) {
  setPanel(root.querySelector("[data-local-panel]"), true);
  setPanel(root.querySelector("[data-telegram-panel]"), false);
  setSwitcherState(root, "local");
  root.querySelector("input[name='username']")?.focus();
}

function openTelegramPanel(root) {
  setPanel(root.querySelector("[data-local-panel]"), false);
  setPanel(root.querySelector("[data-telegram-panel]"), true);
  setSwitcherState(root, "telegram");
  root.querySelectorAll("[data-phone-input]").forEach(syncPhoneGroup);
  const otp = root.querySelector("[data-telegram-otp]");
  const phone = root.querySelector("[data-telegram-panel] [data-phone-local]");
  (otp || phone)?.focus();
}

function initLoginPage() {
  const root = document.querySelector("[data-login-page]");
  if (!root) return;

  root.querySelectorAll("[data-password-toggle]").forEach((button) => {
    button.addEventListener("click", () => togglePassword(button));
  });

  root.querySelectorAll("[data-phone-input]").forEach((container) => {
    const country = container.querySelector("[data-phone-country]");
    const local = container.querySelector("[data-phone-local]");
    country?.addEventListener("change", () => syncPhoneGroup(container));
    local?.addEventListener("input", () => syncPhoneGroup(container));
    syncPhoneGroup(container);
  });

  root.querySelector("[data-local-toggle]")?.addEventListener("click", () => openLocalPanel(root));
  root.querySelector("[data-telegram-open]")?.addEventListener("click", () => openTelegramPanel(root));

  const auth = root.dataset.loginState || "";
  const error = root.dataset.loginError || "";
  if (auth === "telegram_otp_sent" || error.startsWith("telegram_")) {
    openTelegramPanel(root);
  } else {
    openLocalPanel(root);
  }
}

document.addEventListener("DOMContentLoaded", initLoginPage);
