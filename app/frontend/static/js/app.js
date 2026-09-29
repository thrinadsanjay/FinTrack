(function () {
  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") || "" : "";
  }

  function toast(message, tone) {
    var stack = document.getElementById("ft-toast-stack");
    if (!stack || !message) return;
    var el = document.createElement("div");
    el.className = "ft-toast" + (tone ? " ft-toast--" + tone : "");
    el.textContent = message;
    stack.appendChild(el);
    requestAnimationFrame(function () {
      el.classList.add("is-visible");
    });
    setTimeout(function () {
      el.classList.remove("is-visible");
      setTimeout(function () {
        el.remove();
      }, 220);
    }, 3200);
  }

  var darkQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function storedPref() {
    try {
      var value = localStorage.getItem("ft_theme");
      return value === "dark" || value === "system" ? value : "light";
    } catch (_e) {
      return "light";
    }
  }

  function resolveTheme(pref) {
    if (pref === "system") return darkQuery && darkQuery.matches ? "dark" : "light";
    return pref === "dark" ? "dark" : "light";
  }

  // pref: "light" | "dark" | "system". Only the preference is stored (no sensitive data).
  function setThemePref(pref) {
    try {
      localStorage.setItem("ft_theme", pref);
    } catch (_e) {}
    renderTheme(resolveTheme(pref), pref);
  }

  function applyTheme(theme) {
    setThemePref(theme === "dark" ? "dark" : "light");
  }

  function renderTheme(theme, pref) {
    document.documentElement.setAttribute("data-theme", theme);
    document.querySelectorAll("[data-theme-pref]").forEach(function (btn) {
      var on = btn.getAttribute("data-theme-pref") === pref;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-checked", on ? "true" : "false");
    });
    document.querySelectorAll("[data-theme-icon]").forEach(function (icon) {
      icon.className =
        theme === "dark" ? "fa-solid fa-sun" : "fa-solid fa-moon";
    });
    document.querySelectorAll("[data-theme-mode]").forEach(function (btn) {
      var active = btn.getAttribute("data-theme-mode") === theme;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
    document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
      var isDark = theme === "dark";
      btn.setAttribute("aria-pressed", isDark ? "true" : "false");
      btn.setAttribute(
        "aria-label",
        isDark ? "Switch to light theme" : "Switch to dark theme"
      );
      btn.setAttribute(
        "title",
        isDark ? "Switch to light theme" : "Switch to dark theme"
      );
    });
    window.dispatchEvent(new CustomEvent("ft:theme", { detail: { theme: theme } }));
  }

  if (darkQuery) {
    var onSchemeChange = function () {
      if (storedPref() === "system") renderTheme(resolveTheme("system"), "system");
    };
    if (darkQuery.addEventListener) darkQuery.addEventListener("change", onSchemeChange);
    else if (darkQuery.addListener) darkQuery.addListener(onSchemeChange);
  }

  document.addEventListener("click", function (event) {
    var prefBtn = event.target.closest("[data-theme-pref]");
    if (prefBtn) {
      setThemePref(prefBtn.getAttribute("data-theme-pref"));
      return;
    }
    var modeBtn = event.target.closest("[data-theme-mode]");
    if (modeBtn) {
      applyTheme(modeBtn.getAttribute("data-theme-mode") === "dark" ? "dark" : "light");
      return;
    }
    var toggle = event.target.closest("[data-theme-toggle]");
    if (toggle) {
      var current =
        document.documentElement.getAttribute("data-theme") === "dark"
          ? "dark"
          : "light";
      applyTheme(current === "dark" ? "light" : "dark");
      return;
    }
    var chatOpen = event.target.closest("[data-chat-open]");
    if (chatOpen) {
      var message = chatOpen.getAttribute("data-chat-message");
      window.dispatchEvent(
        new CustomEvent("ft:chat-open", {
          detail: message ? { message: message } : {},
        })
      );
    }
  });

  renderTheme(resolveTheme(storedPref()), storedPref());

  var params = new URLSearchParams(window.location.search);
  if (params.get("auth") === "success") {
    toast("Signed in successfully", "success");
  }
  if (params.get("msg")) {
    toast(params.get("msg"), params.get("auth") === "failed" ? "error" : "");
  }
  var flashMessage = document.body.getAttribute("data-flash-message");
  if (flashMessage) {
    toast(flashMessage, document.body.getAttribute("data-flash-tone") || "success");
  }

  window.FinTrack = {
    csrfToken: csrfToken,
    toast: toast,
    applyTheme: applyTheme,
    setThemePref: setThemePref,
  };
})();
