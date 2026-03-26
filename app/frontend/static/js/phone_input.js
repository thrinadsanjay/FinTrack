(function phoneInputHelpers() {
  const WRAPPER_SELECTOR = "[data-phone-input]";

  function normalizeDigits(value) {
    return String(value || "").replace(/\D/g, "");
  }

  function normalizeCode(value) {
    const cleaned = String(value || "").trim();
    if (!cleaned) return "";
    const digits = cleaned.replace(/[^0-9]/g, "");
    return digits ? `+${digits}` : "";
  }

  function getCodeFromSelect(select) {
    if (!select) return "";
    const option = select.options?.[select.selectedIndex];
    return normalizeCode(option?.dataset.countryCode || option?.value || select.value);
  }

  function getDefaultCode(wrapper, select) {
    const explicitCountry = String(wrapper?.dataset.defaultCountry || wrapper?.dataset.defaultCountryCode || "").trim().toUpperCase();
    if (explicitCountry && select) {
      const matched = Array.from(select.options || []).find(
        (option) => String(option.value || "").trim().toUpperCase() === explicitCountry
      );
      if (matched) {
        return normalizeCode(matched.dataset.countryCode || matched.value || "");
      }
    }
    return getCodeFromSelect(select) || "+91";
  }

  function splitByKnownCodes(fullValue, options, defaultCode) {
    const normalized = normalizeCode(fullValue) + normalizeDigits(String(fullValue || "").replace(/^\+/, ""));
    const codeOptions = Array.from(options || [])
      .map((option) => normalizeCode(option?.dataset?.countryCode || option?.value || ""))
      .filter(Boolean)
      .sort((a, b) => b.length - a.length);

    const exactMatch = codeOptions.find((code) => normalized.startsWith(code));
    if (exactMatch) {
      return { code: exactMatch, local: normalized.slice(exactMatch.length) };
    }

    const fallback = normalizeCode(defaultCode || codeOptions[0] || "+91");
    return { code: fallback, local: normalizeDigits(normalized.replace(/^\+/, "").replace(/^\d{1,4}/, "")) };
  }

  function syncHiddenValue(wrapper) {
    const select = wrapper?.querySelector("[data-phone-code]");
    const localInput = wrapper?.querySelector("[data-phone-local]");
    const hiddenInput = wrapper?.querySelector("[data-phone-full]");
    if (!select || !localInput || !hiddenInput) return;
    const code = getCodeFromSelect(select) || getDefaultCode(wrapper, select);
    const local = normalizeDigits(localInput.value);
    hiddenInput.value = local ? `${code}${local}` : "";
  }

  function syncVisibleFromHidden(wrapper) {
    const select = wrapper?.querySelector("[data-phone-code]");
    const localInput = wrapper?.querySelector("[data-phone-local]");
    const hiddenInput = wrapper?.querySelector("[data-phone-full]");
    if (!select || !localInput || !hiddenInput) return;
    const current = String(hiddenInput.value || "").trim();
    if (!current) {
      const defaultCode = getDefaultCode(wrapper, select);
      const matched = Array.from(select.options || []).find((option) => normalizeCode(option.dataset.countryCode || option.value) === defaultCode);
      if (matched) select.value = matched.value;
      localInput.value = "";
      return;
    }

    const options = Array.from(select.options || []);
    const currentCode = normalizeCode((select.options?.[select.selectedIndex] || {}).dataset?.countryCode || select.value);
    const normalized = current.startsWith("+") ? `+${normalizeDigits(current)}` : `+${normalizeDigits(current)}`;
    const matches = options.filter((option) => normalized.startsWith(normalizeCode(option.dataset.countryCode || option.value))).map((option) => ({
      option,
      code: normalizeCode(option.dataset.countryCode || option.value),
    }));

    let chosen = matches[0] || null;
    if (currentCode) {
      const currentMatch = matches.find((item) => item.code === currentCode);
      if (currentMatch) chosen = currentMatch;
    }

    if (chosen) {
      select.value = chosen.option.value;
      localInput.value = normalized.slice(chosen.code.length);
    } else {
      const fallbackCode = getDefaultCode(wrapper, select);
      const matched = options.find((option) => normalizeCode(option.dataset.countryCode || option.value) === fallbackCode);
      if (matched) select.value = matched.value;
      localInput.value = normalizeDigits(normalized.replace(/^\+/, ""));
    }
  }

  function initPhoneInput(wrapper) {
    const select = wrapper?.querySelector("[data-phone-code]");
    const localInput = wrapper?.querySelector("[data-phone-local]");
    const hiddenInput = wrapper?.querySelector("[data-phone-full]");
    if (!select || !localInput || !hiddenInput) return;

    if (!select.value) {
      const defaultCode = getDefaultCode(wrapper, select);
      const defaultOption = Array.from(select.options || []).find((option) => normalizeCode(option.dataset.countryCode || option.value) === defaultCode);
      if (defaultOption) {
        select.value = defaultOption.value;
      }
    }

    syncVisibleFromHidden(wrapper);

    const sync = () => syncHiddenValue(wrapper);
    select.addEventListener("change", sync);
    localInput.addEventListener("input", () => {
      localInput.value = normalizeDigits(localInput.value);
      sync();
    });
    localInput.addEventListener("blur", sync);

    const form = wrapper.closest("form");
    if (form) {
      form.addEventListener("submit", sync);
    }
  }

  function initPhoneInputs(root = document) {
    const scope = root || document;
    scope.querySelectorAll(WRAPPER_SELECTOR).forEach((wrapper) => initPhoneInput(wrapper));
  }

  function focusPhoneLocal(root = document) {
    const input = (root || document).querySelector("[data-phone-local]");
    if (input) input.focus();
  }

  window.FTPhoneInput = {
    initPhoneInputs,
    syncHiddenValue,
    syncVisibleFromHidden,
    focusPhoneLocal,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => initPhoneInputs(), { once: true });
  } else {
    initPhoneInputs();
  }
})();
